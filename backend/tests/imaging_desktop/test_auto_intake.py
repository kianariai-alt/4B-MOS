from dataclasses import replace
from email.message import Message
from io import BytesIO
import gzip
import hashlib
import json
import struct
import tarfile
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from backend.app.imaging_intelligence.intake import inventory, IntakeError
from backend.imaging_desktop.discovery import discover_downloads
from backend.imaging_desktop.received import receive
from backend.imaging_desktop.sources import _download_stream, read_artifact


def zipped(entries):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


class IntakeTests(unittest.TestCase):
    def test_content_signatures_cover_documents_images_video_archives_and_unknown(self):
        fixtures = {
            "pdf": b"%PDF-1.7\nprivate patient report", "png": b"\x89PNG\r\n\x1a\nprivate",
            "jpeg": b"\xff\xd8\xffimage", "gif": b"GIF89a", "tiff": b"II*\x00",
            "bmp": b"BM123", "webp": b"RIFF1234WEBP", "avi": b"RIFF1234AVI ",
            "iso_media": b"\x00\x00\x00\x20ftypisom", "matroska": b"\x1a\x45\xdf\xa3video",
            "mpeg": b"\x00\x00\x01\xba123", "nrrd": b"NRRD0005\n", "metaimage": b"ObjectType = Image\n",
            "rar": b"Rar!\x1a\x07\x01\x00", "seven_zip": b"7z\xbc\xaf\x27\x1c",
            "rtf": b"{\\rtf1 report}", "xml": b"<?xml version='1.0'?><report/>",
            "structured_text": b'{"patient":"private"}', "html": b"<!doctype html><html>Login</html>",
            "text": b"plain clinical report", "unknown": b"\xff\x00\xfe\x01", "executable": b"MZunsafe.exe",
            "ole_document": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        }
        for kind, raw in fixtures.items():
            with self.subTest(kind=kind):
                result = inventory(raw)
                self.assertEqual(result.kind, kind)
                self.assertEqual(result.content_sha256, hashlib.sha256(raw).hexdigest())
                self.assertNotIn("private", json.dumps(result.to_dict()))
                self.assertFalse(result.clinically_validated)

    def test_nifti_versions_endianness_and_gzip(self):
        for endian in ("<", ">"):
            nii = struct.pack(endian+"I", 348) + b"\x00"*340 + b"n+1\x00"
            self.assertEqual(inventory(nii).kind, "nifti")
            result = inventory(gzip.compress(nii))
            self.assertEqual(dict(result.member_kinds), {"nifti": 1})
            nii2 = struct.pack(endian+"I", 540) + b"n+2\x00\r\n\x1a\n" + b"\x00"*528
            self.assertEqual(inventory(nii2).kind, "nifti")

    def test_mixed_zip_inventory_is_content_based_and_does_not_expose_names(self):
        raw = zipped([("Secret Patient/report.dcm", b"%PDF-1.7 report"),
                      ("wrong-extension.txt", b"\xff\xd8\xffimage"), ("macro.exe", b"MZbad")])
        result = inventory(raw)
        self.assertEqual(dict(result.member_kinds), {"pdf": 1, "jpeg": 1, "executable": 1})
        self.assertIn("quarantined_no_processor", result.issues)
        self.assertNotIn("Secret", json.dumps(result.to_dict()))

    def test_zip_and_tar_traversal_links_and_bombs_are_blocked(self):
        for name in ("../private.pdf", "/private.pdf", "C:/private.pdf", "..\\private.pdf"):
            with self.subTest(name=name), self.assertRaisesRegex(IntakeError, "unsafe_archive_entry"):
                inventory(zipped([(name, b"%PDF-1.7")]))
        output = BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            item = tarfile.TarInfo("private.pdf")
            item.type = tarfile.SYMTYPE
            item.linkname = "/etc/passwd"
            archive.addfile(item)
        with self.assertRaisesRegex(IntakeError, "unsafe_archive_entry"):
            inventory(output.getvalue())
        with patch("backend.app.imaging_intelligence.intake.MAX_INSPECTED_BYTES", 100):
            with self.assertRaisesRegex(IntakeError, "archive_expansion_limit"):
                inventory(gzip.compress(b"a"*1000))

    def test_tar_nested_archives_and_inspection_budget(self):
        output = BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            item = tarfile.TarInfo("report.pdf")
            item.size = 8
            archive.addfile(item, BytesIO(b"%PDF-1.7"))
        self.assertEqual(dict(inventory(output.getvalue()).member_kinds), {"pdf": 1})
        nested = b"%PDF-1.7"
        for _ in range(4):
            nested = zipped([("nested.zip", nested)])
        self.assertIn("nested_archive_inspection_limit", inventory(nested).issues)
        with patch("backend.app.imaging_intelligence.intake.MAX_INSPECTED_BYTES", 2):
            self.assertIn("archive_inspection_byte_limit", inventory(zipped([("report", b"%PDF-1.7")])).issues)

    def test_any_format_download_even_with_wrong_mime_and_extension(self):
        for kind, raw in (("pdf", b"%PDF-1.7 report"), ("unknown", b"\xff\x00\xfe"),
                          ("html", b"<html>Login</html>")):
            response = BytesIO(raw)
            response.headers = Message()
            response.headers["Content-Type"] = "application/dicom"
            data = _download_stream(response, allow_any_format=True)
            result = receive(data)
            self.assertEqual(result.payload, raw)
            self.assertEqual(result.inventory.kind, kind)
            self.assertIsNone(result.catalog)
            self.assertEqual(result.report()["clinical_findings"], [])
        with TemporaryDirectory() as folder:
            path = Path(folder)/"wrong.dcm"
            path.write_bytes(b"%PDF-1.7")
            self.assertEqual(receive(read_artifact(path)).inventory.kind, "pdf")

    def test_corrupt_unsafe_unknown_and_executable_remain_downloadable_but_quarantined(self):
        for raw in (b"PK\x03\x04broken", zipped([("../x", b"secret")]), b"MZunsafe", b"\xff\x00"):
            result = receive(raw)
            self.assertEqual(result.payload, raw)
            self.assertIsNone(result.catalog)
            self.assertTrue(result.inventory.issues)

    def test_generated_dicom_reaches_existing_validator_and_volume(self):
        from backend.imaging_desktop.volume import load_series
        from backend.tools.synthetic_knee_fixture import generate_knee_dicom
        with TemporaryDirectory() as folder:
            fixture = generate_knee_dicom(Path(folder), size=32)
            raw = zipped([(f"slice-{i}.bin", item.path.read_bytes()) for i, item in enumerate(fixture.source.instances)])
        result = receive(raw)
        self.assertEqual(result.processing_code, "volume_catalog_ready")
        self.assertEqual(load_series(result.catalog.series[0]).voxels.shape, (32, 32, 32))
        report = result.report()
        validation = report["technical_validations"][0]
        self.assertEqual(validation["status"], "needs_data")
        self.assertEqual(len(validation["rules_sha256"]), 64)
        self.assertFalse(report["is_diagnosis"])


class DiscoveryTests(unittest.TestCase):
    def anchor(self, href, **kw):
        return {"href": href, "text": "", "visible": True, "download": False, **kw}

    def test_discovers_all_explicit_formats_and_signed_extensionless_downloads(self):
        result = discover_downloads("https://center.example/Patient?secret=hidden", [
            self.anchor("/report.pdf"), self.anchor("/scan.zip"), self.anchor("/video.mp4"),
            self.anchor("/opaque?signature=private", download=True),
            self.anchor("/export?key=hidden", text="دریافت فایل"),
        ])
        self.assertEqual(result.status, "downloads_found")
        self.assertEqual(len(result.urls), 5)
        self.assertNotIn("private", repr(result))

    def test_cross_origin_hidden_credentials_insecure_links_and_unlabelled_pages_are_ignored(self):
        result = discover_downloads("https://center.example/Patient", [
            self.anchor("https://evil.example/scan.zip"), self.anchor("http://center.example/report.pdf"),
            self.anchor("https://u:p@center.example/scan.zip"), self.anchor("javascript:logout()", download=True),
            self.anchor("data:application/pdf,secret", download=True), self.anchor("/scan.zip", visible=False),
            self.anchor("/logout"), self.anchor("/terms"),
        ])
        self.assertFalse(result.urls)
        self.assertEqual(result.status, "manual_export_required")

    def test_candidate_limit_deduplication_and_origin_port(self):
        anchors = [self.anchor("/scan.zip")]*3
        self.assertEqual(len(discover_downloads("https://center.example:5010/Patient", anchors).urls), 1)
        self.assertFalse(discover_downloads("https://center.example:5010/Patient", [self.anchor("https://center.example/a.pdf")]).urls)
        self.assertEqual(discover_downloads("https://center.example/Patient", [self.anchor(f"/{i}.pdf") for i in range(9)]).status,
                         "too_many_download_candidates")
        self.assertEqual(discover_downloads("https://center.example/Patient", anchors*100).status, "portal_inspection_limit")


if __name__ == "__main__":
    unittest.main()
