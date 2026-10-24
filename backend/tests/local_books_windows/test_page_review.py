"""Real Windows, stdlib-only page-review CLI with synthetic source text."""
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


@unittest.skipUnless(os.name == "nt", "The path and process smoke requires Windows.")
class WindowsBookPageReviewSmoke(unittest.TestCase):
    def test_private_bounded_text_export_without_optional_packages_or_source_changes(self):
        # pypdf is used only to create and extract this synthetic fixture. The
        # subprocess uses -S, so its page review cannot depend on site-packages.
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        from backend.tools.local_orthopedic_library import scan_library

        with tempfile.TemporaryDirectory(prefix="4B MOS page review کتاب ") as temporary:
            root = Path(temporary)
            checkout = root / "tools checkout پوشه"
            source = root / "orthopedic book کتاب"
            source.mkdir()
            tools_directory = checkout / "backend" / "tools"
            tools_directory.mkdir(parents=True)
            for name in ("local_orthopedic_library.py", "orthopedic_book_handoff.py",
                         "orthopedic_book_page_review.py"):
                shutil.copy2(REPOSITORY / "backend" / "tools" / name, tools_directory / name)

            writer = PdfWriter()
            for number in range(1, 4):
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
                contents.set_data(
                    f"BT /F1 12 Tf 10 200 Td (Synthetic review page {number}.) Tj ET".encode("ascii")
                )
                page[NameObject("/Contents")] = contents
            with (source / "Synthetic source کتاب.pdf").open("wb") as stream:
                writer.write(stream)

            run, manifest = scan_library(source, root / "private extraction خروجی")
            book = manifest["books"][0]
            records = [json.loads(line) for line in
                       (run / book["pages_artifact"]).read_text(encoding="utf-8").splitlines()]
            before = {str(path): path.read_bytes() for directory in (source, run)
                      for path in directory.rglob("*") if path.is_file()}
            output = root / "private review خروجی" / "page review.json"
            command = [
                sys.executable, "-B", "-S", str(tools_directory / "orthopedic_book_page_review.py"),
                "--run", str(run), "--source", str(source),
                "--manifest-sha256", manifest["manifest_sha256"],
                "--page", f"{book['source_file_sha256']}:2", "--context", "1",
                "--output", str(output),
            ]
            environment = dict(os.environ, PYTHONUTF8="1")
            launched = subprocess.run(command, cwd=root, env=environment, text=True,
                                      encoding="utf-8", errors="replace", capture_output=True,
                                      timeout=60, check=False)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            packet = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(packet["schema_id"], "4b-mos.book-page-review")
            self.assertEqual(packet["schema_version"], "1.0.0")
            self.assertEqual(packet["extraction_manifest_sha256"], manifest["manifest_sha256"])
            self.assertFalse(packet["uploads_performed"])
            self.assertFalse(packet["registry_write_performed"])
            self.assertFalse(packet["is_clinically_validated"])
            self.assertEqual([page["pdf_page_number"] for page in packet["pages"]], [1, 2, 3])
            self.assertEqual([page["role"] for page in packet["pages"]], ["context", "target", "context"])
            for page, original in zip(packet["pages"], records):
                self.assertEqual(page["text"], original["text"])
                self.assertEqual(page["text_sha256"], hashlib.sha256(page["text"].encode("utf-8")).hexdigest())
                self.assertFalse(page["printed_page_number_verified"])
            payload = {key: value for key, value in packet.items() if key != "bundle_sha256"}
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.assertEqual(packet["bundle_sha256"], hashlib.sha256(canonical).hexdigest())
            serialized = json.dumps(packet, ensure_ascii=False)
            self.assertNotIn(json.dumps(str(source), ensure_ascii=False)[1:-1], serialized)
            self.assertNotIn(json.dumps(str(run), ensure_ascii=False)[1:-1], serialized)
            self.assertFalse(list(checkout.rglob("page review.json")))

            content = output.read_bytes()
            repeated = subprocess.run(command, cwd=root, env=environment, text=True,
                                      encoding="utf-8", errors="replace", capture_output=True,
                                      timeout=60, check=False)
            self.assertEqual(repeated.returncode, 2, repeated.stdout + repeated.stderr)
            self.assertEqual(output.read_bytes(), content)
            after = {str(path): path.read_bytes() for directory in (source, run)
                     for path in directory.rglob("*") if path.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
