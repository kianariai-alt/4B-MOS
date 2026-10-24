"""Bounded private source review; every text/PDF byte here is synthetic."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from backend.tools import orthopedic_book_page_review as review
from backend.tools.local_orthopedic_library import _json
from backend.tools.orthopedic_book_handoff import canonical


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def snapshot(tmp_path):
    """Preexisting synthetic extraction: the exporter must never parse a PDF."""
    source = tmp_path / "source کتاب"
    run = tmp_path / "existing extraction"
    source.mkdir()
    run.mkdir()
    original = source / "Synthetic.pdf"
    original.write_bytes(b"Synthetic original bytes, not a clinical book or PDF parser fixture.")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    artifact = run / "books" / digest / "pages.jsonl"
    artifact.parent.mkdir(parents=True)
    pages = [dict(source_file_sha256=digest, pdf_page_number=number,
                  text=f"Synthetic page {number}: متن ساختگی", text_sha256="",
                  status="text_extracted", error_type=None, is_approved_medical_knowledge=False,
                  pdf_page_label_unverified=str(number + 100), printed_page_number_verified=False)
             for number in range(1, 51)]
    book = dict(source_file_sha256=digest, relative_path=original.name,
                pages_artifact=artifact.relative_to(run).as_posix(), page_record_count=len(pages),
                status="text_extracted", pages_artifact_sha256="")
    manifest = dict(schema_version="1.0.0", books=[book], traversal_errors=[])

    def refresh():
        for page in pages:
            page["text_sha256"] = sha(page["text"])
        artifact.write_text("".join(_json(page) + "\n" for page in pages), encoding="utf-8")
        book["pages_artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = sha(_json(manifest))
        (run / "manifest.json").write_text(_json(manifest), encoding="utf-8")

    refresh()
    return source, run, manifest, pages, refresh


def build(snapshot, numbers=(2,), **kwargs):
    source, run, manifest, _, _ = snapshot
    return review.build_page_review(run, source, manifest_sha256=manifest["manifest_sha256"],
                                    selection=[(manifest["books"][0]["source_file_sha256"], n)
                                               for n in numbers], **kwargs)


def test_exact_text_context_hashes_and_no_source_or_snapshot_changes(snapshot):
    source, run, manifest, original, _ = snapshot
    before = {p: p.read_bytes() for root in (source, run) for p in root.rglob("*") if p.is_file()}
    packet = build(snapshot, numbers=(1, 2))
    assert [p["pdf_page_number"] for p in packet["pages"]] == [1, 2, 3]
    assert [p["role"] for p in packet["pages"]] == ["target", "target", "context"]
    assert [p["text"] for p in packet["pages"]] == [p["text"] for p in original[:3]]
    assert packet["text_utf8_bytes"] == sum(len(p["text"].encode("utf-8")) for p in original[:3])
    assert packet["bundle_sha256"] == sha(canonical({k: v for k, v in packet.items() if k != "bundle_sha256"}))
    assert packet["extraction_manifest_sha256"] == manifest["manifest_sha256"]
    assert packet["contains_book_text"] and packet["source_text_is_untrusted_data"]
    assert packet["source_text_review"] == "pending"
    for flag in ("uploads_performed", "registry_write_performed", "is_clinically_validated"):
        assert packet[flag] is False
    assert all(not p["printed_page_number_verified"] and not p["visual_verification_performed"]
               for p in packet["pages"])
    assert str(source) not in canonical(packet) and str(run) not in canonical(packet)
    assert before == {p: p.read_bytes() for root in (source, run) for p in root.rglob("*") if p.is_file()}


def test_page_roles_are_bound_to_each_book_not_just_page_number(snapshot):
    source, run, manifest, first_pages, _ = snapshot
    second = source / "Another synthetic.pdf"
    second.write_bytes(b"Different synthetic original")
    second_digest = hashlib.sha256(second.read_bytes()).hexdigest()
    artifact = run / "books" / second_digest / "pages.jsonl"
    artifact.parent.mkdir(parents=True)
    second_pages = [{**p, "source_file_sha256": second_digest} for p in first_pages]
    artifact.write_text("".join(_json(p) + "\n" for p in second_pages), encoding="utf-8")
    manifest["books"].append({**manifest["books"][0], "source_file_sha256": second_digest,
                              "relative_path": second.name,
                              "pages_artifact": artifact.relative_to(run).as_posix(),
                              "pages_artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = sha(_json(manifest))
    (run / "manifest.json").write_text(_json(manifest), encoding="utf-8")
    first_digest = manifest["books"][0]["source_file_sha256"]
    packet = review.build_page_review(run, source, manifest_sha256=manifest["manifest_sha256"],
                                      selection=[(first_digest, 2), (second_digest, 3)])
    roles = {(p["source_file_sha256"], p["pdf_page_number"]): p["role"] for p in packet["pages"]}
    assert roles[first_digest, 2] == roles[second_digest, 3] == "target"
    assert roles[first_digest, 3] == roles[second_digest, 2] == "context"


@pytest.mark.parametrize("status", ["empty_text_requires_ocr_or_manual_review", "page_extraction_error"])
def test_adjacent_unusable_page_is_an_explicit_gap_but_required_target_fails(snapshot, status):
    _, _, _, pages, refresh = snapshot
    pages[0].update(text="", status=status, error_type="SyntheticError" if "error" in status else None)
    refresh()
    packet = build(snapshot)
    assert packet["context_gap_count"] == 1
    gap = packet["pages"][0]
    assert gap["status"] == status and gap["text"] is None and not gap["eligible_as_source_text"]
    with pytest.raises(ValueError, match="empty|error"):
        build(snapshot, numbers=(1,))


@pytest.mark.parametrize("numbers", [(), (True,), (0,), (-1,), (1.0,), ("1",), (1, 1), (51,)])
def test_selection_is_explicit_unique_positive_and_existing(snapshot, numbers):
    with pytest.raises(ValueError):
        build(snapshot, numbers=numbers)


def test_context_page_limit_and_text_byte_limit_fail_without_truncation(snapshot, monkeypatch):
    with pytest.raises(ValueError, match="page limit"):
        build(snapshot, numbers=range(1, 41))  # 40 targets plus page 41 as context
    packet = build(snapshot, numbers=(2,), context=0)
    text = packet["pages"][0]["text"]
    assert len(text.encode("utf-8")) > len(text)
    monkeypatch.setattr(review, "MAX_TEXT_BYTES", len(text.encode("utf-8")) - 1)
    with pytest.raises(ValueError, match="UTF-8 byte limit"):
        build(snapshot, context=0)


def test_manifest_pin_source_and_artifact_tampering_fail(snapshot):
    source, run, manifest, _, _ = snapshot
    digest = manifest["books"][0]["source_file_sha256"]
    with pytest.raises(ValueError, match="pinned"):
        review.build_page_review(run, source, manifest_sha256="f" * 64, selection=[(digest, 2)])
    (source / "Synthetic.pdf").write_bytes(b"Changed original PDF bytes")
    with pytest.raises(ValueError, match="original PDF"):
        build(snapshot)


def test_page_artifact_tampering_cannot_be_exported(snapshot):
    _, run, manifest, _, _ = snapshot
    artifact = run / manifest["books"][0]["pages_artifact"]
    artifact.write_text(artifact.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        build(snapshot)


def test_reread_text_tampering_after_snapshot_verification_is_detected(snapshot, monkeypatch):
    _, run, manifest, pages, _ = snapshot
    original = review.handoff.build_handoff

    def changed(*args, **kwargs):
        checked = original(*args, **kwargs)
        pages[1]["text"] = "Changed text after verification, stale text hash"
        path = run / manifest["books"][0]["pages_artifact"]
        path.write_text("".join(_json(p) + "\n" for p in pages), encoding="utf-8")
        return checked

    monkeypatch.setattr(review.handoff, "build_handoff", changed)
    with pytest.raises(ValueError, match="provenance"):
        build(snapshot)


def test_standalone_cli_uses_no_site_packages_protects_output_and_never_prints_book_text(snapshot, tmp_path):
    source, run, manifest, pages, _ = snapshot
    output = tmp_path / "private output" / "review.json"
    command = [sys.executable, "-B", "-S", str(Path(review.__file__).resolve()),
               "--run", str(run), "--source", str(source), "--manifest-sha256", manifest["manifest_sha256"],
               "--page", f"{manifest['books'][0]['source_file_sha256']}:2", "--output", str(output)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    content = output.read_bytes()
    assert json.loads(content)["page_count"] == 3
    assert pages[1]["text"] not in result.stdout + result.stderr
    repeated = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert repeated.returncode == 2 and output.read_bytes() == content
    unsafe = command[:-1] + [str(source / "forbidden.json")]
    assert subprocess.run(unsafe, capture_output=True, timeout=30).returncode == 2
    assert not (source / "forbidden.json").exists()
