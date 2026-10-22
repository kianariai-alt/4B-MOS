"""Offline tests; run without the application/database test fixtures."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.tools.validate_orthopedic_research import main, validate_catalog


CATALOG = (
    Path(__file__).resolve().parents[2]
    / "docs/orthopedic-intelligence/research-catalog.v1.json"
)


class ResearchCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.catalog["sources"] = [copy.deepcopy(self.catalog["sources"][0])]

    def add_artifact(self, content=b"synthetic research fixture", path="sources/sample.txt"):
        source = self.catalog["sources"][0]
        source["acquisition_status"] = "local_artifacts_declared"
        source["artifacts"] = [{
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "acquired_at": "2026-10-19T12:00:00+00:00",
            "source_url": source["url"],
            "media_type": "text/plain",
        }]

    def test_repository_catalog_is_inactive_and_truthfully_incomplete(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        report = validate_catalog(catalog)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.source_count, 8)
        self.assertEqual(report.verified_artifacts, 0)
        self.assertEqual(len(report.warnings), 9)
        self.assertIsNone(catalog["previous_archive"]["sha256"])
        strict = validate_catalog(catalog, require_artifacts=True)
        self.assertFalse(strict.ok)
        self.assertEqual(len(strict.errors), 8)

    def test_explicit_activation_and_licence_guards(self):
        for field in ("clinical_activation", "registry_imported", "commercial_retrieval"):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.catalog)
                altered[field] = True
                self.assertFalse(validate_catalog(altered).ok)
                altered[field] = 0
                self.assertFalse(validate_catalog(altered).ok)
        for field in ("commercial_retrieval_allowed", "image_reuse_allowed"):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.catalog)
                altered["sources"][0]["license_review"][field] = True
                self.assertFalse(validate_catalog(altered).ok)

    def test_cannot_claim_missing_archive_hash_or_download(self):
        self.catalog["previous_archive"]["sha256"] = "a" * 64
        self.assertFalse(validate_catalog(self.catalog).ok)
        self.catalog["previous_archive"]["sha256"] = None
        self.catalog["sources"][0]["acquisition_status"] = "local_artifacts_declared"
        self.assertFalse(validate_catalog(self.catalog).ok)

    def test_no_clinical_or_licence_approval_can_be_smuggled_in(self):
        for field, value in (("clinical_status", "approved"),
                             ("registry_status", "imported"),
                             ("evidence_grade", "high")):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.catalog)
                altered["sources"][0][field] = value
                self.assertFalse(validate_catalog(altered).ok)
        self.catalog["sources"][0]["license_review"]["status"] = "approved"
        self.assertFalse(validate_catalog(self.catalog).ok)

    def test_malformed_metadata_returns_errors_without_crashing(self):
        for value in (None, [], "invalid", 12):
            with self.subTest(value=value):
                self.assertFalse(validate_catalog(value).ok)
        for field, value in (("source_type", []), ("knowledge_layer", {}),
                             ("url", "https://[invalid"),
                             ("publication_date", "2026-02-30"),
                             ("artifacts", None), ("license_review", None)):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.catalog)
                altered["sources"][0][field] = value
                self.assertFalse(validate_catalog(altered).ok)

    def test_duplicate_source_and_artifact_paths_are_rejected(self):
        self.catalog["sources"].append(copy.deepcopy(self.catalog["sources"][0]))
        self.assertFalse(validate_catalog(self.catalog).ok)
        self.catalog["sources"].pop()
        self.add_artifact()
        artifacts = self.catalog["sources"][0]["artifacts"]
        artifacts.append(copy.deepcopy(artifacts[0]))
        self.assertFalse(validate_catalog(self.catalog).ok)

    def test_local_integrity_then_tampering(self):
        self.add_artifact()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sources/sample.txt"
            path.parent.mkdir()
            path.write_bytes(b"synthetic research fixture")
            report = validate_catalog(self.catalog, root=root, require_artifacts=True)
            self.assertTrue(report.ok, report.errors)
            self.assertEqual(report.verified_artifacts, 1)
            path.write_bytes(b"changed")
            report = validate_catalog(self.catalog, root=root)
            self.assertTrue(any("SHA256 mismatch" in error for error in report.errors))

    def test_missing_artifacts_do_not_pass_integrity_validation(self):
        self.add_artifact()
        with tempfile.TemporaryDirectory() as temporary:
            report = validate_catalog(self.catalog, root=Path(temporary))
            self.assertTrue(any("missing local artifact" in error for error in report.errors))
        self.assertFalse(validate_catalog(self.catalog).ok)

    def test_timezone_is_required_for_artifact_acquisition(self):
        self.add_artifact()
        self.catalog["sources"][0]["artifacts"][0]["acquired_at"] = "2026-10-19T12:00:00"
        report = validate_catalog(self.catalog)
        self.assertTrue(any("timezone-aware" in error for error in report.errors))

    def test_portable_artifact_path_containment(self):
        for path in ("../secret", "/tmp/source", "C:/source", "a\\b.txt",
                     "sources/../source", "sources//source", "sources/CON.txt",
                     "sources/name. ", "sources/name."):
            with self.subTest(path=path):
                self.add_artifact(path=path)
                report = validate_catalog(self.catalog)
                self.assertTrue(any("unsafe artifact path" in error for error in report.errors))

    def test_local_symlink_cannot_escape_root(self):
        self.add_artifact(path="linked/sample.txt")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, outside = base / "root", base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "sample.txt").write_bytes(b"synthetic research fixture")
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink creation unavailable on this platform: {exc}")
            report = validate_catalog(self.catalog, root=root)
            self.assertTrue(any("escapes root" in error for error in report.errors))

    def test_zip_hashes_are_verified_without_extraction(self):
        self.add_artifact()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "research.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("sources/sample.txt", b"synthetic research fixture")
            report = validate_catalog(self.catalog, archive_path=archive, require_artifacts=True)
            self.assertTrue(report.ok, report.errors)
            self.assertEqual(report.verified_artifacts, 1)
            self.assertFalse((root / "sources").exists())

    def test_archive_rejects_traversal_case_collision_and_symlink(self):
        for mode in ("traversal", "duplicate", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "unsafe.zip"
                with zipfile.ZipFile(archive, "w") as bundle:
                    if mode == "traversal":
                        bundle.writestr("../source.txt", b"fixture")
                    elif mode == "duplicate":
                        bundle.writestr("sources/A.txt", b"first")
                        bundle.writestr("sources/a.txt", b"second")
                    else:
                        link = zipfile.ZipInfo("sources/link")
                        link.create_system = 3
                        link.external_attr = (stat.S_IFLNK | 0o777) << 16
                        bundle.writestr(link, "../../outside")
                self.assertFalse(validate_catalog(self.catalog, archive_path=archive).ok)

    def test_invalid_archive_and_size_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "source.zip"
            archive.write_bytes(b"not a zip")
            self.assertFalse(validate_catalog(self.catalog, archive_path=archive).ok)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("source.txt", b"fixture")
            with patch("backend.tools.validate_orthopedic_research.MAX_ARCHIVE_BYTES", 1):
                self.assertFalse(validate_catalog(self.catalog, archive_path=archive).ok)

    def test_cli_exit_codes_distinguish_metadata_and_complete_archive(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--catalog", str(CATALOG)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["verified_artifacts"], 0)
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--catalog", str(CATALOG), "--require-artifacts"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue())["clinical_activation"])

    def test_cli_malformed_json_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "invalid.json"
            catalog.write_bytes(b"{")
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--catalog", str(catalog)]), 1)
            self.assertIn("catalog cannot be read", output.getvalue())


if __name__ == "__main__":
    unittest.main()
