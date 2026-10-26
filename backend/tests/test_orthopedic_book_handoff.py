"""Synthetic source bytes and proposals only; no real books or patient records."""
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from backend.app.schemas.medical_knowledge import KnowledgeFactContent, KnowledgeFactCreate
from backend.app.services.medical_knowledge import knowledge_content_digest
from backend.app.services.orthopedic_book_handoff import (
    BookHandoffIntegrityError, book_handoff_digest, prepare_book_draft, validate_book_handoff,
)
from backend.tools.local_orthopedic_library import scan_library
from backend.tools import orthopedic_book_handoff as handoff_tool
from backend.tools.orthopedic_book_handoff import build_handoff, canonical, latest_run, main, strict_json


@pytest.fixture
def proposal():
    return KnowledgeFactCreate(
        fact_key="SYNTHETIC.BOOK.PROVENANCE", title="Synthetic test assertion",
        statement="Synthetic assertion for software provenance testing only.",
        clinical_domain="orthopedics_knee", population="Synthetic test population",
        indication="Synthetic authoring verification", evidence_grade="ungraded",
        sources=[dict(source_type="textbook", title="Synthetic textbook",
                      citation="Test fixture, synthetic chapter; no clinical evidence.",
                      accessed_at=date(2026, 10, 20))],
    )


@pytest.fixture
def handoff():
    payload = dict(
        schema_id="4b-mos.book-source-handoff", schema_version="1.0.0",
        scope="available_extracted_pages", omitted_entry_count=0, unresolved_entry_count=0,
        traversal_error_count=0, extraction_manifest_sha256="1" * 64,
        verifier_artifact_sha256="2" * 64,
        sources=[dict(source_file_sha256="3" * 64, filename="synthetic.pdf",
                      source_pdf_verified=True, pages_artifact_sha256="4" * 64, verification_error=None)],
        pages=[dict(source_file_sha256="3" * 64, pdf_page_number=1,
                    text_sha256=hashlib.sha256(b"Synthetic source text").hexdigest(), status="text_extracted")],
        uploads_performed=False, is_clinically_validated=False, registry_write_performed=False,
    )
    payload["handoff_sha256"] = book_handoff_digest(payload)
    return payload


def refs(handoff):
    return [{"source_file_sha256": handoff["pages"][0]["source_file_sha256"], "pdf_page_number": 1}]


def preview(proposal, handoff, **kwargs):
    return prepare_book_draft(proposal, handoff, refs(handoff), "Synthetic chapter",
                              proposal_origin="ai_assisted_draft", **kwargs)


@pytest.fixture
def snapshot(tmp_path):
    pytest.importorskip("pypdf")
    from backend.tests.test_local_orthopedic_library import make_pdf
    source = tmp_path / "books with spaces"
    source.mkdir()
    make_pdf(source / "synthetic.pdf")
    run, manifest = scan_library(source, tmp_path / "private extraction")
    return source, run, manifest


def test_real_extractor_to_handoff_to_existing_registry_draft_without_writes(snapshot, proposal):
    source, run, _ = snapshot
    before = {path: path.read_bytes() for root in (source, run) for path in root.rglob("*") if path.is_file()}
    packet = build_handoff(run, source)
    validate_book_handoff(packet)
    result = preview(proposal, packet, reported_printed_pages="Reported label; not verified")
    assert result.status == "draft" and result.requires_independent_review
    assert result.clinical_source_review == "pending" and not result.registry_write_performed
    assert result.provenance.source_entailment_review == "pending"
    assert result.provenance.bibliographic_identity_review == "pending"
    assert result.provenance.printed_page_verification == "unverified"
    assert result.provenance.proposal_origin == "ai_assisted_draft"
    assert result.provenance.pages[0].text_sha256 == packet["pages"][0]["text_sha256"]
    assert "Synthetic knee source" not in canonical(packet)
    assert str(source) not in canonical(packet) and str(run) not in canonical(packet)
    assert {path: path.read_bytes() for root in (source, run) for path in root.rglob("*") if path.is_file()} == before


def test_provenance_is_bound_to_existing_registry_hash_and_input_is_preserved(proposal, handoff):
    before = proposal.model_dump(mode="json")
    result = preview(proposal, handoff)
    content = KnowledgeFactContent.model_validate(result.proposal.model_dump(exclude={"fact_key"}))
    assert result.content_sha256 == knowledge_content_digest(fact_key=result.proposal.fact_key, version=1, content=content)
    assert result.provenance.handoff_sha256 in result.proposal.statement
    assert proposal.model_dump(mode="json") == before
    changed = preview(proposal, handoff, reported_printed_pages="Different unverified locator")
    assert changed.content_sha256 != result.content_sha256


def test_tampering_cannot_reuse_an_old_handoff_digest(handoff):
    handoff["pages"][0]["text_sha256"] = "a" * 64
    with pytest.raises(BookHandoffIntegrityError):
        validate_book_handoff(handoff)


@pytest.mark.parametrize("flag", ["uploads_performed", "is_clinically_validated", "registry_write_performed"])
@pytest.mark.parametrize("value", [True, 0, "false"])
def test_governance_flags_cannot_claim_writes_approval_or_coerce_false(handoff, flag, value):
    handoff[flag] = value
    with pytest.raises(ValidationError):
        validate_book_handoff(handoff)


@pytest.mark.parametrize("value", [True, 0, -1, 1.0, "1"])
def test_page_number_is_strict_positive_integer(handoff, value):
    handoff["pages"][0]["pdf_page_number"] = value
    with pytest.raises(ValidationError):
        validate_book_handoff(handoff)


@pytest.mark.parametrize("filename", ["../private.pdf", "C:\\private.pdf", "/private.pdf", "folder\\private.pdf"])
def test_handoff_rejects_machine_paths_in_filename(handoff, filename):
    handoff["sources"][0]["filename"] = filename
    with pytest.raises(ValidationError):
        validate_book_handoff(handoff)


def test_duplicate_and_dangling_page_references_fail(handoff):
    bad = copy.deepcopy(handoff)
    bad["pages"].append(copy.deepcopy(bad["pages"][0]))
    with pytest.raises(ValidationError, match="Duplicate"):
        validate_book_handoff(bad)
    handoff["pages"][0]["source_file_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="unknown"):
        validate_book_handoff(handoff)


@pytest.mark.parametrize("status", ["empty_text_requires_ocr_or_manual_review", "page_extraction_error"])
def test_selected_unusable_pages_cannot_become_draft_provenance(proposal, handoff, status):
    handoff["pages"][0]["status"] = status
    handoff["handoff_sha256"] = book_handoff_digest(handoff)
    with pytest.raises(ValueError, match="nonempty"):
        preview(proposal, handoff)


def test_empty_text_digest_cannot_be_relabelled_as_success(proposal, handoff):
    handoff["pages"][0]["text_sha256"] = hashlib.sha256(b"").hexdigest()
    handoff["handoff_sha256"] = book_handoff_digest(handoff)
    with pytest.raises(ValueError, match="nonempty"):
        preview(proposal, handoff)


def test_unverified_original_pdf_blocks_draft_preparation(proposal, handoff):
    handoff["sources"][0].update(source_pdf_verified=False, verification_error="source_pdf_hash_mismatch")
    handoff["handoff_sha256"] = book_handoff_digest(handoff)
    with pytest.raises(ValueError, match="original source PDF"):
        preview(proposal, handoff)


def test_draft_requires_explicit_single_book_reference_and_source_date(proposal, handoff):
    with pytest.raises(ValueError, match="At least"):
        prepare_book_draft(proposal, handoff, [], "Chapter", proposal_origin="human_authored")
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_book_draft(proposal, handoff, refs(handoff) * 2, "Chapter", proposal_origin="human_authored")
    missing = [{"source_file_sha256": "3" * 64, "pdf_page_number": 2}]
    with pytest.raises(ValueError, match="does not exist"):
        prepare_book_draft(proposal, handoff, missing, "Chapter", proposal_origin="human_authored")
    proposal.sources[0].model_fields_set.discard("accessed_at")
    with pytest.raises(ValueError, match="explicitly supplied"):
        preview(proposal, handoff)


def test_no_automatic_evidence_upgrade_or_nested_preview(proposal, handoff):
    proposal.evidence_grade = "high"
    with pytest.raises(ValueError, match="ungraded"):
        preview(proposal, handoff)
    proposal.evidence_grade = "ungraded"
    result = preview(proposal, handoff)
    with pytest.raises(ValueError, match="already contains"):
        preview(result.proposal, handoff)


@pytest.mark.parametrize("change", ["changed", "missing"])
def test_current_pdf_bytes_are_checked_against_snapshot(snapshot, proposal, change):
    source, run, _ = snapshot
    pdf = source / "synthetic.pdf"
    if change == "changed":
        pdf.write_bytes(pdf.read_bytes() + b"\nchanged source bytes")
    else:
        pdf.unlink()
    packet = build_handoff(run, source)
    assert not packet["sources"][0]["source_pdf_verified"]
    with pytest.raises(ValueError, match="original source PDF"):
        preview(proposal, packet)


def test_artifact_tampering_blocks_handoff(snapshot):
    source, run, manifest = snapshot
    path = run / manifest["books"][0]["pages_artifact"]
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        build_handoff(run, source)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(text):
    with pytest.raises(ValueError):
        strict_json(text)


@pytest.mark.parametrize("unsafe", ["../outside.pdf", "/absolute.pdf", "C:/absolute.pdf", "folder\\source.pdf"])
def test_manifest_source_path_escape_is_rejected_before_reading(snapshot, unsafe):
    source, run, manifest = snapshot
    manifest["books"][0]["relative_path"] = unsafe
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="relative"):
        build_handoff(run, source)


def test_linked_original_is_not_read(snapshot, tmp_path):
    source, run, _ = snapshot
    original = source / "synthetic.pdf"
    external = tmp_path / "external.pdf"
    external.write_bytes(original.read_bytes())
    original.unlink()
    try:
        original.symlink_to(external)
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    with pytest.raises(ValueError, match="Linked"):
        build_handoff(run, source)


def test_selected_good_page_survives_unrelated_extraction_problem(tmp_path, proposal):
    pytest.importorskip("pypdf")
    from backend.tests.test_local_orthopedic_library import make_pdf
    source = tmp_path / "books"
    source.mkdir()
    make_pdf(source / "good.pdf")
    make_pdf(source / "blank.pdf", text=None)
    (source / "unsupported.zip").write_bytes(b"synthetic unsupported source")
    run, manifest = scan_library(source, tmp_path / "output")
    good = next(book for book in manifest["books"] if book["relative_path"] == "good.pdf")
    packet = build_handoff(run, source, selection=[(good["source_file_sha256"], 1)])
    assert packet["scope"] == "selected_extracted_pages"
    assert packet["unresolved_entry_count"] == 2 and packet["omitted_entry_count"] == 2
    assert len(packet["sources"]) == len(packet["pages"]) == 1
    assert preview(proposal, packet).status == "draft"
    assert main(["--source", str(source), "--run", str(run), "--output", str(tmp_path / "all.json")]) == 1


def test_cli_is_standard_library_only_and_output_is_metadata(snapshot, tmp_path):
    source, run, _ = snapshot
    tool = Path(__file__).resolve().parents[1] / "tools" / "orthopedic_book_handoff.py"
    destination = tmp_path / "private" / "handoff.json"
    result = subprocess.run([sys.executable, "-S", "-B", str(tool), "--source", str(source),
                             "--run", str(run), "--output", str(destination)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(destination.read_text(encoding="utf-8"))
    validate_book_handoff(payload)
    assert "text" not in payload["pages"][0]
    before = destination.read_bytes()
    assert main(["--source", str(source), "--run", str(run), "--output", str(destination)]) == 2
    assert destination.read_bytes() == before


def test_output_cannot_modify_books_or_extraction_snapshot(snapshot):
    source, run, _ = snapshot
    for destination in (source / "handoff.json", run / "handoff.json"):
        assert main(["--source", str(source), "--run", str(run), "--output", str(destination)]) == 2
        assert not destination.exists()


def test_latest_ignores_unfinished_attempt_but_not_new_corrupted_manifest(snapshot):
    _, run, _ = snapshot
    unfinished = run.parent / "run-99999998"
    unfinished.mkdir()
    assert latest_run(run.parent) == run
    corrupt = run.parent / "run-99999999"
    corrupt.mkdir()
    (corrupt / "manifest.json").write_text("invalid", encoding="utf-8")
    assert latest_run(run.parent) == corrupt


def test_omitted_unsupported_source_does_not_report_full_success(tmp_path):
    pytest.importorskip("pypdf")
    from backend.tests.test_local_orthopedic_library import make_pdf
    source = tmp_path / "books"
    source.mkdir()
    make_pdf(source / "good.pdf")
    (source / "unread.zip").write_bytes(b"synthetic unsupported source")
    run, _ = scan_library(source, tmp_path / "extraction")
    output = tmp_path / "handoff.json"
    assert main(["--source", str(source), "--run", str(run), "--output", str(output)]) == 1
    packet = json.loads(output.read_text(encoding="utf-8"))
    assert packet["omitted_entry_count"] == packet["unresolved_entry_count"] == 1
    assert all(page["status"] == "text_extracted" for page in packet["pages"])
    validate_book_handoff(packet)


def test_verifier_digest_also_tracks_current_snapshot_verifier(snapshot, monkeypatch):
    source, run, _ = snapshot
    first = build_handoff(run, source)
    actual_digest = handoff_tool.file_digest
    def changed_dependency(path):
        return "d" * 64 if path.name == "local_orthopedic_library.py" else actual_digest(path)
    monkeypatch.setattr(handoff_tool, "file_digest", changed_dependency)
    second = build_handoff(run, source)
    assert first["verifier_artifact_sha256"] != second["verifier_artifact_sha256"]
    assert first["handoff_sha256"] != second["handoff_sha256"]


def test_malformed_manifest_entry_returns_documented_error(tmp_path, capsys):
    source = tmp_path / "books"
    source.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text('{"books":[null]}', encoding="utf-8")
    assert main(["--source", str(source), "--run", str(run)]) == 2
    assert "must be an object" in capsys.readouterr().err
