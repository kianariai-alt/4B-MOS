"""Build a self-contained, offline physician-review demo for Windows browsers.

The ten fixed cases are computed by the existing Python service. The editable
form is explicitly a UI simulator, not another medical decision engine. This
builder uses synthetic fixtures only and never queries a database or network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from backend.app.schemas.orthopedic_interview_tree import (
    BOOLEAN_FIELDS, CHOICES, TEXT_FIELDS, KneeInterviewTreePreviewRequest,
)
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.services.orthopedic_interview_tree import (
    build_interview_tree, build_interview_tree_preview,
)
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_assessment import build_knee_assessment, export_offline_assessment
from backend.tools.orthopedic_interview_tree_demo import CASES_PATH, run_synthetic_cases


VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name("orthopedic_windows_demo")
HTML_NAME = "4B-MOS-Windows-Demo.html"
ZIP_NAME = "4B-MOS-Windows-Demo.zip"
FOLDER_NAME = "4B-MOS-Windows-Demo"
LAUNCHER_NAME = "Run-4B-MOS-Demo.cmd"

LAUNCHER = """@echo off
setlocal
set "DEMO_FILE=%~dp04B-MOS-Windows-Demo.html"
if not exist "%DEMO_FILE%" (
  echo ERROR: Extract the complete demo ZIP first.
  echo Keep this launcher next to 4B-MOS-Windows-Demo.html.
  pause
  exit /b 1
)
start "" "%DEMO_FILE%"
if errorlevel 1 (
  echo Open 4B-MOS-Windows-Demo.html with Microsoft Edge or Google Chrome.
  pause
  exit /b 1
)
exit /b 0
"""


def _source_revision() -> tuple[str | None, bool | None]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{40}", head):
            return None, None
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return head, bool(dirty)
    except (OSError, subprocess.SubprocessError):
        return None, None


def generate_payload() -> dict:
    """Return real fixed-case previews and the source-bound static tree."""
    # Validate actual fixture expectations before producing a distributable.
    summary = run_synthetic_cases()
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    tree = build_interview_tree()
    tree_json = tree.model_dump(mode="json")
    cases = []
    for case in fixture["cases"]:
        request = KneeInterviewTreePreviewRequest.model_validate(case["request"])
        preview = build_interview_tree_preview(request)
        if preview.tree.model_dump(mode="json") != tree_json:
            raise ValueError("Every embedded case must use the same versioned tree.")
        cases.append({
            "id": case["id"], "description_fa": case["description_fa"],
            "request": request.model_dump(mode="json"),
            # Reattach the shared top-level tree to verify result_sha256.
            "preview": preview.model_dump(mode="json", exclude={"tree"}),
            "assessment": build_knee_assessment(request).model_dump(mode="json"),
        })
    assessment_cases = json.loads((ROOT / "docs/examples/orthopedic-assessment-cases-v1.json").read_text(encoding="utf-8"))
    if assessment_cases.get("synthetic_only") is not True:
        raise ValueError("Assessment quick-fill examples must be explicitly synthetic.")
    examples = []
    assessment_parity_cases = []
    wanted = assessment_cases["quickfill_case_ids"]
    for case in assessment_cases["cases"]:
        request = KneeInterviewTreePreviewRequest.model_validate(case["request"])
        item = {
            "id": case["id"], "label_fa": case["label_fa"], "request": request.model_dump(mode="json"),
            "assessment": build_knee_assessment(request).model_dump(mode="json"),
        }
        assessment_parity_cases.append(item)
        if case["id"] in wanted:
            examples.append(item)
    if len(examples) != len(set(wanted)):
        raise ValueError("Every selected synthetic assessment example must occur once.")
    revision, dirty = _source_revision()
    return {
        "schema_version": "1.0.0",
        "build": {
            "version": VERSION, "source_commit": revision,
            "working_tree_dirty": dirty, "synthetic_only": True,
            "governance_status": "draft", "approved_fact_count": 0,
            "fixed_case_count": summary["case_count"],
            "fixed_case_passed_count": summary["passed_cases"],
            "custom_form_executes_python_engine": False,
            "custom_form_uses_compiled_draft_assessment": True,
            "network_required": False, "persistent_answer_storage": False,
        },
        "tree": tree_json,
        "fact_sources": {fact.fact.fact_key: list(fact.source_keys) for fact in load_knee_pack().facts},
        "choices": {key: list(values) for key, values in CHOICES.items()},
        "boolean_fields": sorted(BOOLEAN_FIELDS), "text_fields": sorted(TEXT_FIELDS),
        "cases": cases,
        "assessment_model": export_offline_assessment(),
        "assessment_examples": examples,
        "assessment_parity_cases": assessment_parity_cases,
        "disclaimer_fa": "نسخهٔ آزمایشی برای دادهٔ ساختگی و بازبینی پزشک؛ همهٔ محتوا پیش‌نویس است. اطلاعات بیمار واقعی وارد نکنید.",
    }


def _inline_json(value: dict) -> str:
    # JSON is data, never HTML or executable source. Escape HTML termination and
    # JS line separators so even adversarial text cannot break out of the tag.
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _render_html(payload: dict) -> str:
    template = (ASSETS / "ui.html").read_text(encoding="utf-8")
    style = (ASSETS / "ui.css").read_text(encoding="utf-8")
    script = (ASSETS / "ui.js").read_text(encoding="utf-8")
    if re.search(r"</script", script, re.IGNORECASE) or re.search(r"</style", style, re.IGNORECASE):
        raise ValueError("UI source contains an unsafe embedded-tag terminator.")
    replacements = {
        "__MOS_DEMO_DATA__": _inline_json(payload),
        "__MOS_DEMO_STYLE__": style,
        "__MOS_DEMO_SCRIPT__": script,
    }
    # Substitute in a single pass: content cannot be interpreted as a marker.
    for marker in replacements:
        if template.count(marker) != 1:
            raise ValueError("Expected exactly one trusted template marker: " + marker)
    return re.sub(r"__MOS_DEMO_(?:DATA|STYLE|SCRIPT)__", lambda match: replacements[match[0]], template)


def build_windows_demo(output_dir: str | Path) -> dict:
    """Create a portable HTML and ZIP in an explicit output directory."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    payload = generate_payload()
    contents = {
        HTML_NAME: _render_html(payload).encode("utf-8"),
        LAUNCHER_NAME: LAUNCHER.replace("\n", "\r\n").encode("ascii"),
        "README-FA.txt": b"\xef\xbb\xbf" + (ASSETS / "README-FA.txt").read_text(encoding="utf-8").encode("utf-8"),
    }
    manifest = {
        "schema_id": "4b-mos.windows-demo-manifest", "schema_version": "1.0.0",
        "version": VERSION, "source_commit": payload["build"]["source_commit"],
        "working_tree_dirty": payload["build"]["working_tree_dirty"],
        "synthetic_only": True, "governance_status": "draft", "approved_fact_count": 0,
        "payload_sha256": content_digest(payload),
        "tree_sha256": payload["tree"]["tree_sha256"],
        "files": [{"name": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                  for name, content in sorted(contents.items())],
    }
    contents["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for name, content in contents.items():
        (output / name).write_bytes(content)
    with zipfile.ZipFile(output / ZIP_NAME, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(contents.items()):
            entry = zipfile.ZipInfo(FOLDER_NAME + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build_windows_demo(args.output_dir)
    print(json.dumps({
        "version": manifest["version"], "output_dir": str(args.output_dir.resolve()),
        "html": HTML_NAME, "zip": ZIP_NAME, "case_count": 10,
        "tree_sha256": manifest["tree_sha256"], "governance_status": "draft",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
