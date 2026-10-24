"""Adversarial local-source tests; all PDFs and paths are synthetic fixtures."""
import importlib.metadata
import json
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")

from backend.tools import local_orthopedic_library as library


def blank_pdf(path: Path) -> None:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as stream:
        writer.write(stream)


def test_linked_file_and_directory_cannot_expand_selected_source_scope(tmp_path):
    source = tmp_path / "selected"
    source.mkdir()
    outside = tmp_path / "unselected"
    outside.mkdir()
    blank_pdf(outside / "outside.pdf")
    try:
        (source / "linked.pdf").symlink_to(outside / "outside.pdf")
        (source / "linked-dir").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating test symlinks requires OS support/permission.")
    run, manifest = library.scan_library(source, tmp_path / "output")
    statuses = {entry["relative_path"]: entry["status"] for entry in manifest["books"]}
    assert statuses == {"linked-dir": "linked_directory_skipped", "linked.pdf": "linked_file_skipped"}
    assert manifest["status"] == "requires_review"
    assert not list(run.rglob("pages.jsonl"))
    assert "outside.pdf" not in json.dumps(manifest)


def test_source_digest_change_discards_untrustworthy_page_artifact(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    book = source / "changed-during-read.pdf"
    blank_pdf(book)
    digest = library.file_digest(book)
    original_digest = library.file_digest
    calls = 0

    def changing_digest(path):
        nonlocal calls
        if path != book:
            return original_digest(path)
        calls += 1
        return digest if calls == 1 else "0" * 64

    monkeypatch.setattr(library, "file_digest", changing_digest)
    run, manifest = library.scan_library(source, tmp_path / "output")
    assert calls == 2
    assert manifest["status"] == "requires_review"
    entry = manifest["books"][0]
    assert entry["status"] == "source_changed_during_read"
    assert "pages_artifact" not in entry
    assert not list(run.rglob("pages.jsonl*"))
    assert not (run / "books" / digest).exists()


def test_missing_dependency_fails_before_creating_any_output(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"

    def missing_distribution(name):
        assert name == "pypdf"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(library.importlib.metadata, "version", missing_distribution)
    assert library.main(["--source", str(source), "--output", str(output)]) == 2
    assert not output.exists()
    assert "requirements-books.txt" in capsys.readouterr().err


def test_page_parser_error_is_not_copied_into_book_text_or_report(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    blank_pdf(source / "parser-error.pdf")
    sensitive_parser_message = "DO_NOT_COPY_UNSELECTED_PATH_OR_MEDICAL_CLAIM"

    def broken_extract(self, *args, **kwargs):
        raise RuntimeError(sensitive_parser_message)

    monkeypatch.setattr(pypdf._page.PageObject, "extract_text", broken_extract)
    run, manifest = library.scan_library(source, tmp_path / "output")
    assert manifest["status"] == "requires_review"
    entry = manifest["books"][0]
    assert entry["page_status_counts"] == {"page_extraction_error": 1}
    pages = [json.loads(line) for line in (run / entry["pages_artifact"]).read_text().splitlines()]
    assert len(pages) == 1
    assert pages[0]["text"] == ""
    assert pages[0]["error_type"] == "RuntimeError"
    assert pages[0]["is_approved_medical_knowledge"] is False
    for artifact in run.rglob("*"):
        if artifact.is_file():
            assert sensitive_parser_message not in artifact.read_text(encoding="utf-8")
