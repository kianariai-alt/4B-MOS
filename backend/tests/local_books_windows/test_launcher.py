"""Real Windows cmd launcher smoke with synthetic PDFs and private temp output.

Run without backend/API dependencies:
    python -m unittest discover -s backend/tests/local_books_windows -v
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(os.name == "nt", "The .cmd launcher requires Windows.")
class WindowsLocalBookLauncherSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Imported only on Windows; Linux collection needs no optional reader.
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        cls.temporary = tempfile.TemporaryDirectory(prefix="4B MOS کتاب آزمون ")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.checkout = cls.root / "checkout with spaces پوشه"
        cls.source = cls.root / "orthopedic book کتاب"
        cls.local_app_data = cls.root / "private local app data خروجی"
        (cls.checkout / "backend" / "tools").mkdir(parents=True)
        cls.source.mkdir()
        for relative in (
            "Read-Orthopedic-Books.cmd",
            "backend/requirements-books.txt",
            "backend/tools/local_orthopedic_library.py",
        ):
            shutil.copy2(REPOSITORY / relative, cls.checkout / relative)

        cls.book = cls.source / "Synthetic knee fixture کتاب.PDF"
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        contents = DecodedStreamObject()
        contents.set_data(b"BT /F1 12 Tf 10 200 Td (Synthetic local knee fixture.) Tj ET")
        page[NameObject("/Contents")] = contents
        writer.add_metadata({"/Title": "Synthetic local knee fixture"})
        with cls.book.open("wb") as stream:
            writer.write(stream)
        cls.source_bytes = cls.book.read_bytes()
        cls.environment = dict(
            os.environ, LOCALAPPDATA=str(cls.local_app_data), PYTHONUTF8="1",
            # Preserve the launcher's real `py -3` path while selecting the
            # same minor version as the workflow's configured Python runtime.
            PY_PYTHON3=f"{sys.version_info.major}.{sys.version_info.minor}",
        )
        launcher = cls.checkout / "Read-Orthopedic-Books.cmd"
        # Pass the raw command line to CreateProcess on Windows. An argv list
        # would apply C-runtime quote escaping to cmd.exe's own /c expression.
        command = f'cmd.exe /d /s /c ""{launcher}" "{cls.source}""'
        cls.launch = subprocess.run(
            command, cwd=cls.checkout, env=cls.environment, input="\n",
            text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=360, check=False,
        )
        if cls.launch.returncode != 0:
            raise AssertionError(
                f"Windows launcher returned {cls.launch.returncode}\n"
                f"stdout:\n{cls.launch.stdout}\nstderr:\n{cls.launch.stderr}"
            )
        manifests = list(cls.local_app_data.rglob("manifest.json"))
        if len(manifests) != 1:
            raise AssertionError(f"Expected one private extraction manifest, found {manifests}")
        cls.run_directory = manifests[0].parent
        cls.manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        cls.reader_python = cls.checkout / ".venv-books" / "Scripts" / "python.exe"
        cls.script = cls.checkout / "backend" / "tools" / "local_orthopedic_library.py"

    def verify_cli(self, run: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.reader_python), str(self.script), "--verify", str(run)],
            cwd=self.checkout, env=self.environment, text=True, encoding="utf-8",
            errors="replace", capture_output=True, timeout=30, check=False,
        )

    def test_launcher_extracts_source_from_unicode_path_into_private_workspace(self):
        self.assertTrue(self.reader_python.is_file())
        self.assertEqual(self.book.read_bytes(), self.source_bytes)
        self.assertEqual(self.manifest["status"], "extraction_complete")
        self.assertEqual(self.manifest["source_directory"], str(self.source.resolve()))
        self.assertEqual(self.manifest["extractor_version"], "6.21.1")
        self.assertEqual(self.manifest["draft_proposition_count"], 0)
        self.assertEqual(self.manifest["approved_proposition_count"], 0)
        self.assertFalse(self.manifest["uploads_performed"])
        self.assertFalse(self.manifest["is_clinically_validated"])
        self.assertEqual(self.manifest["tool_artifact_sha256"], digest(self.script))
        self.assertFalse(list(self.source.rglob("manifest.json")))
        self.assertFalse(list(self.checkout.rglob("pages.jsonl")))

        manifest_payload = {k: v for k, v in self.manifest.items() if k != "manifest_sha256"}
        serialized = json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.assertEqual(self.manifest["manifest_sha256"], hashlib.sha256(serialized).hexdigest())
        self.assertEqual(len(self.manifest["books"]), 1)
        book = self.manifest["books"][0]
        self.assertEqual(book["relative_path"], self.book.name)
        self.assertEqual(book["source_file_sha256"], hashlib.sha256(self.source_bytes).hexdigest())
        self.assertEqual(book["status"], "text_extracted")
        self.assertEqual(book["page_record_count"], 1)
        pages_path = self.run_directory / book["pages_artifact"]
        self.assertEqual(book["pages_artifact_sha256"], digest(pages_path))
        page = json.loads(pages_path.read_text(encoding="utf-8"))
        self.assertEqual(page["pdf_page_number"], 1)
        self.assertIn("Synthetic local knee fixture.", page["text"])
        self.assertEqual(page["text_sha256"], hashlib.sha256(page["text"].encode("utf-8")).hexdigest())
        self.assertFalse(page["is_approved_medical_knowledge"])
        self.assertFalse(page["printed_page_number_verified"])

        verified = self.verify_cli(self.run_directory)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn("not medical approval", verified.stdout)

    def test_verification_cli_rejects_changed_page_artifact(self):
        copied_run = self.root / "changed copy آزمون"
        shutil.copytree(self.run_directory, copied_run)
        book = self.manifest["books"][0]
        page_path = copied_run / book["pages_artifact"]
        page = json.loads(page_path.read_text(encoding="utf-8"))
        page["pdf_page_number"] = 99
        page_path.write_text(json.dumps(page) + "\n", encoding="utf-8")
        verified = self.verify_cli(copied_run)
        self.assertEqual(verified.returncode, 2, verified.stdout + verified.stderr)
        self.assertIn("integrity check failed", verified.stderr)


if __name__ == "__main__":
    unittest.main()
