"""Synthetic PDFs only; no copyrighted books, patient data, or real drives."""
import hashlib
import json
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf", reason="Install backend/requirements-books.txt to test optional local intake")
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from backend.tools.local_orthopedic_library import file_digest, main, scan_library, verify_library_run


def make_pdf(path, text="Synthetic knee source for intake software testing."):
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text is not None:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        contents = DecodedStreamObject()
        contents.set_data(f"BT /F1 12 Tf 10 200 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = contents
    writer.add_metadata({"/Title": "Synthetic Orthopedic Source", "/Author": "Test Fixture"})
    with path.open("wb") as output:
        writer.write(output)


@pytest.fixture
def library_paths(tmp_path):
    source = tmp_path / "orthopedic book کتاب"
    source.mkdir()
    return source, tmp_path / "private output"


def test_text_extraction_binds_file_and_page_without_approving_or_changing_source(library_paths):
    source, output = library_paths
    pdf = source / "Book with spaces.PDF"
    make_pdf(pdf)
    before = pdf.read_bytes()
    destination, manifest = scan_library(source, output)
    book = manifest["books"][0]
    assert manifest["status"] == "extraction_complete"
    assert book["source_file_sha256"] == hashlib.sha256(before).hexdigest()
    page = json.loads((destination / book["pages_artifact"]).read_text().splitlines()[0])
    assert page["pdf_page_number"] == 1
    assert "Synthetic knee source" in page["text"]
    assert page["text_sha256"] == hashlib.sha256(page["text"].encode()).hexdigest()
    assert not page["is_approved_medical_knowledge"]
    assert not page["printed_page_number_verified"] and page["chapter"] is None
    assert book["edition"] is book["publication_year"] is None
    assert manifest["draft_proposition_count"] == manifest["approved_proposition_count"] == 0
    assert not manifest["uploads_performed"]
    assert pdf.read_bytes() == before


def test_blank_pages_need_review_and_do_not_invent_ocr_text(library_paths):
    source, output = library_paths
    make_pdf(source / "blank.pdf", text=None)
    destination, manifest = scan_library(source, output)
    assert manifest["status"] == "requires_review"
    book = manifest["books"][0]
    page = json.loads((destination / book["pages_artifact"]).read_text())
    assert page["text"] == ""
    assert page["status"] == "empty_text_requires_ocr_or_manual_review"


def test_bad_encrypted_and_unsupported_files_do_not_prevent_other_books(library_paths):
    source, output = library_paths
    (source / "bad.pdf").write_text("not a PDF")
    (source / "unsupported.epub").write_bytes(b"not extracted")
    make_pdf(source / "good.pdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt("synthetic-password")
    with (source / "encrypted.pdf").open("wb") as stream:
        writer.write(stream)
    _, manifest = scan_library(source, output)
    states = {book["relative_path"]: book["status"] for book in manifest["books"]}
    assert states == {"bad.pdf": "file_read_error", "encrypted.pdf": "encrypted_requires_local_review",
                      "good.pdf": "text_extracted", "unsupported.epub": "unsupported_format_requires_review"}
    assert manifest["status"] == "requires_review"
    assert "synthetic-password" not in json.dumps(manifest)


def test_duplicate_content_is_extracted_once_and_rerun_preserves_snapshots(library_paths):
    source, output = library_paths
    make_pdf(source / "a.pdf")
    (source / "b.pdf").write_bytes((source / "a.pdf").read_bytes())
    first, manifest = scan_library(source, output)
    second, again = scan_library(source, output)
    assert first != second and (first / "manifest.json").exists()
    assert manifest["books"] == again["books"]
    assert manifest["books"][1]["status"] == "duplicate_file"
    assert manifest["books"][1]["duplicate_of"] == "a.pdf"
    assert len(list(first.rglob("pages.jsonl"))) == 1


def test_empty_library_is_not_reported_as_success(library_paths):
    source, output = library_paths
    assert main(["--source", str(source), "--output", str(output)]) == 1
    manifest = json.loads(next(output.rglob("manifest.json")).read_text())
    assert manifest["status"] == "no_books_found"


def test_missing_source_has_no_output_and_useful_error(library_paths, capsys):
    source, output = library_paths
    assert main(["--source", str(source / "missing"), "--output", str(output)]) == 2
    assert "could not start" in capsys.readouterr().err
    assert not output.exists()


def test_output_inside_source_is_rejected_without_touching_source(library_paths):
    source, _ = library_paths
    with pytest.raises(ValueError, match="outside"):
        scan_library(source, source / "output")
    assert list(source.iterdir()) == []


def test_page_and_file_limits_are_explicit(library_paths):
    source, output = library_paths
    writer = pypdf.PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=300, height=300)
    with (source / "long.pdf").open("wb") as stream:
        writer.write(stream)
    _, manifest = scan_library(source, output, max_pages=1)
    assert manifest["books"][0]["status"] == "page_limit_exceeded"
    with (source / "large.pdf").open("wb") as stream:
        stream.truncate(2 * 1024 * 1024)
    _, manifest = scan_library(source, output, max_file_mib=1)
    assert manifest["books"][0]["status"] == "file_size_limit_exceeded"


def test_symlinks_outside_the_selected_folder_are_not_read(library_paths, tmp_path):
    source, output = library_paths
    outside = tmp_path / "outside.pdf"
    make_pdf(outside)
    (source / "linked.pdf").symlink_to(outside)
    destination, manifest = scan_library(source, output)
    assert manifest["books"][0]["status"] == "linked_file_skipped"
    assert not list(destination.rglob("pages.jsonl"))


def test_complete_page_artifact_and_manifest_are_verified(library_paths):
    source, output = library_paths
    make_pdf(source / "source.pdf")
    destination, manifest = scan_library(source, output)
    assert verify_library_run(destination) == manifest
    assert main(["--verify", str(destination)]) == 0
    artifact = destination / manifest["books"][0]["pages_artifact"]
    page = json.loads(artifact.read_text())
    page["pdf_page_number"] = 2
    artifact.write_text(json.dumps(page) + "\n")
    with pytest.raises(ValueError, match="artifact integrity"):
        verify_library_run(destination)


def test_manifest_metadata_tampering_is_rejected(library_paths):
    source, output = library_paths
    make_pdf(source / "source.pdf")
    destination, manifest = scan_library(source, output)
    manifest["books"][0]["pdf_metadata_unverified"]["Title"] = "Changed title"
    (destination / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest integrity"):
        verify_library_run(destination)
