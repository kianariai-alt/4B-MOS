"""Exercise generated portable files in Windows Edge, without a backend server."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Requires an actual Windows runner and Microsoft Edge")
class PortableWindowsDemoSmoke(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ["MOS_WINDOWS_DEMO_DIR"])
        self.html = self.folder / "4B-MOS-Windows-Demo.html"

    def test_generated_files_match_manifest_and_portable_launcher(self):
        manifest = json.loads((self.folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["synthetic_only"])
        self.assertEqual(manifest["approved_fact_count"], 0)
        for entry in manifest["files"]:
            content = (self.folder / entry["name"]).read_bytes()
            self.assertEqual(len(content), entry["bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), entry["sha256"])
        launcher = (self.folder / "Run-4B-MOS-Demo.cmd").read_text(encoding="ascii")
        self.assertIn('%~dp04B-MOS-Windows-Demo.html', launcher)
        self.assertNotIn('powershell', launcher.lower())

    def test_actual_edge_loads_embedded_cases_without_server(self):
        candidates = [Path(root) / "Microsoft/Edge/Application/msedge.exe"
                      for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")) if root]
        edge = next((path for path in candidates if path.is_file()), None)
        self.assertIsNotNone(edge, "Microsoft Edge must be present for this Windows browser smoke test")
        # Spaces and Persian characters deliberately exercise local file URLs.
        with tempfile.TemporaryDirectory(prefix="MOS demo ", ignore_cleanup_errors=True) as directory:
            copied = Path(directory) / "آزمایش زانو.html"
            copied.write_bytes(self.html.read_bytes())
            process = subprocess.run([
                str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking",
                "--disable-component-update", "--disable-extensions",
                "--user-data-dir=" + str(Path(directory) / "browser-profile"),
                "--virtual-time-budget=2000", "--dump-dom", copied.as_uri(),
            ], capture_output=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace")[-1500:])
            dom = process.stdout.decode("utf-8", errors="replace")
            self.assertIn('data-demo-ready="true"', dom)
            self.assertIn('data-rendered-case-count="10"', dom)
            self.assertIn('data-assessment-model-ready="true"', dom)
            self.assertIn('id="case-select"', dom)

    def test_actual_edge_renders_a_provisional_assessment_after_answers(self):
        edge = next((Path(root) / "Microsoft/Edge/Application/msedge.exe"
                     for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"))
                     if root and (Path(root) / "Microsoft/Edge/Application/msedge.exe").is_file()), None)
        self.assertIsNotNone(edge)
        with tempfile.TemporaryDirectory(prefix="MOS assessment ", ignore_cleanup_errors=True) as directory:
            process = subprocess.run([
                str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
                "--user-data-dir=" + str(Path(directory) / "profile"), "--virtual-time-budget=2000", "--dump-dom",
                self.html.as_uri() + "#example=oa_pattern",
            ], capture_output=True, timeout=60)
            self.assertEqual(process.returncode, 0)
            dom = process.stdout.decode("utf-8", errors="replace")
            self.assertIn('data-assessment-case="oa_pattern"', dom)
            self.assertIn('data-consideration-id="knee_oa"', dom)
            self.assertIn('data-assessment-status="differential_review"', dom)


if __name__ == "__main__":
    unittest.main(verbosity=2)
