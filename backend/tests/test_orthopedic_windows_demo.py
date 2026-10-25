"""Portable synthetic Windows/browser artifact checks, not clinical validation."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import socket
import zipfile

import pytest

from backend.app.schemas.orthopedic_interview_tree import KneeInterviewTreePreviewRequest
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.services.orthopedic_interview_tree import (
    build_interview_tree, build_interview_tree_preview,
)
from backend.tools import build_orthopedic_windows_demo as demo_builder


class ArtifactHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.payload_chunks = []
        self.tags = []
        self.in_payload = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        self.in_payload = tag == "script" and attributes.get("id") == "mos-demo-data"

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False

    def handle_data(self, data):
        if self.in_payload:
            self.payload_chunks.append(data)


def read_payload(html):
    parsed = ArtifactHTMLParser()
    parsed.feed(html)
    return json.loads("".join(parsed.payload_chunks)), parsed


@pytest.fixture(scope="module")
def built_demo(tmp_path_factory):
    destination = tmp_path_factory.mktemp("windows-demo")
    manifest = demo_builder.build_windows_demo(destination)
    html_name = next(item["name"] for item in manifest["files"] if item["name"].endswith(".html"))
    html = (destination / html_name).read_text(encoding="utf-8")
    payload, parsed = read_payload(html)
    return destination, manifest, payload, html, parsed


def test_portable_package_has_complete_windows_layout_and_verified_bytes(built_demo):
    destination, manifest, payload, html, parsed = built_demo
    assert manifest["schema_id"] == "4b-mos.windows-demo-manifest"
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["version"] == "0.1.0"
    assert re.fullmatch(r"[a-f0-9]{40}", manifest["source_commit"])
    assert manifest["tree_sha256"] == payload["tree"]["tree_sha256"]
    assert manifest["payload_sha256"] == content_digest(payload)
    assert len(manifest["files"]) == 3
    names = {entry["name"] for entry in manifest["files"]}
    assert "Run-4B-MOS-Demo.cmd" in names and "README-FA.txt" in names
    for entry in manifest["files"]:
        raw = (destination / entry["name"]).read_bytes()
        assert entry["bytes"] == len(raw)
        assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
    saved = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    with zipfile.ZipFile(destination / "4B-MOS-Windows-Demo.zip") as archive:
        expected = {f"4B-MOS-Windows-Demo/{name}" for name in names | {"manifest.json"}}
        assert set(archive.namelist()) == expected
        for name in archive.namelist():
            assert "\\" not in name and not name.startswith("/") and ".." not in Path(name).parts
            local_name = name.split("/", 1)[1]
            assert archive.read(name) == (destination / local_name).read_bytes()


def test_embedded_tree_and_all_ten_cases_match_actual_python_engine(built_demo):
    _, manifest, payload, _, _ = built_demo
    tree = build_interview_tree().model_dump(mode="json")
    assert payload["tree"] == tree
    assert {node["number"] for node in tree["nodes"]} == set(range(1, 31))
    assert len(payload["cases"]) == 10
    assert len({case["id"] for case in payload["cases"]}) == 10
    for case in payload["cases"]:
        request = KneeInterviewTreePreviewRequest.model_validate(case["request"])
        expected = build_interview_tree_preview(request).model_dump(mode="json")
        restored = dict(case["preview"], tree=payload["tree"])
        assert restored == expected
        assert restored["result_sha256"] == content_digest({
            key: value for key, value in restored.items() if key != "result_sha256"
        })
        assert restored["governance_status"] == "draft"
        assert restored["approved_fact_count"] == 0
        assert restored["safety_evaluation"] == "not_performed"
        assert not restored["authorizes_treatment"] and not restored["is_clinical_clearance"]


def test_single_html_uses_local_assets_without_requests_or_persistence(built_demo):
    _, _, payload, html, parsed = built_demo
    policies = [attributes.get("content", "") for tag, attributes in parsed.tags
                if tag == "meta" and attributes.get("http-equiv", "").lower() == "content-security-policy"]
    assert len(policies) == 1
    assert "connect-src 'none'" in policies[0]
    assert "default-src 'none'" in policies[0]
    assert not any(tag == "script" and "src" in attributes for tag, attributes in parsed.tags)
    assert not any(tag == "link" and attributes.get("rel") == "stylesheet" for tag, attributes in parsed.tags)
    assert not any(tag in {"iframe", "object", "embed"} for tag, _ in parsed.tags)
    assert "__MOS_DEMO_" not in html
    assert payload["tree"]["bank_export_is_executable_tree"] is False


def test_launcher_opens_supplied_html_without_installation_or_elevation(built_demo):
    destination, manifest, _, _, _ = built_demo
    launcher = (destination / "Run-4B-MOS-Demo.cmd").read_text(encoding="utf-8-sig")
    html_name = next(entry["name"] for entry in manifest["files"] if entry["name"].endswith(".html"))
    assert "%~dp0" in launcher and html_name in launcher
    assert re.search(r"(?im)^\s*start\s+\"\"", launcher)
    assert not re.search(r"(?i)powershell|pip install|npm install|runas|curl|Invoke-WebRequest", launcher)


def test_artifact_contains_metadata_but_no_raw_book_or_patient_files(built_demo):
    destination, manifest, payload, html, _ = built_demo
    with zipfile.ZipFile(destination / "4B-MOS-Windows-Demo.zip") as archive:
        assert not any(name.lower().endswith((".pdf", ".db", ".sqlite", ".env")) for name in archive.namelist())
    assert payload["tree"]["book_source_references"]
    assert all(re.fullmatch(r"[a-f0-9]{64}", source["provenance"]["source_file_sha256"])
               for source in payload["tree"]["book_source_references"])
    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()
    assert not {"patient_id", "patient_name", "date_of_birth", "pdf_bytes", "page_text",
                "extracted_text", "raw_page_text", "source_pdf_path"} & keys(payload)
    assert not re.search(r"[A-Za-z]:\\(?:Users|orthopedic book)\\", html)


def test_build_needs_no_network_and_does_not_modify_knowledge_sources(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    sources = [root / name for name in (
        "backend/app/knowledge/knee_v1.json",
        "backend/app/knowledge/knee_book_review_v1.json",
        "backend/app/services/orthopedic_questions.py",
        "backend/app/services/orthopedic_interview_tree.py",
    )]
    before = {source: source.read_bytes() for source in sources}
    def reject_network(*args, **kwargs):
        raise AssertionError("Offline packaging must not open a network connection.")
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    demo_builder.build_windows_demo(tmp_path / "offline")
    assert before == {source: source.read_bytes() for source in sources}


def test_payload_cannot_close_json_script_and_inject_executable_markup(tmp_path, monkeypatch):
    payload = demo_builder.generate_payload()
    hostile = '</script><script id="injected-script">window.injected=true</script><img id="injected-image">'
    payload["disclaimer_fa"] = hostile
    monkeypatch.setattr(demo_builder, "generate_payload", lambda: payload)
    manifest = demo_builder.build_windows_demo(tmp_path)
    html_name = next(item["name"] for item in manifest["files"] if item["name"].endswith(".html"))
    html = (tmp_path / html_name).read_text(encoding="utf-8")
    decoded, parsed = read_payload(html)
    assert decoded["disclaimer_fa"] == hostile
    assert not any(attributes.get("id") in {"injected-script", "injected-image"}
                   for _, attributes in parsed.tags)
    assert hostile not in html
