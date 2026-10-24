"""Read local PDFs into a private, page-referenced source workspace.

No backend imports, database writes, network calls, medical extraction, or OCR.
Run on the computer holding the books, not on a remote cloud executor.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import uuid


VERSION = "1.0.0"
DEFAULT_SOURCE = r"D:\orthopedic book"
BOOK_SUFFIXES = {".pdf", ".epub", ".djvu", ".djv", ".doc", ".docx", ".chm", ".zip"}


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def default_output() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "4B-MOS" / "orthopedic-library"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_json(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def _extract_pdf(path: Path, destination: Path, digest: str, max_pages: int, show_progress: bool = False) -> dict:
    # Optional dependency: API deployments can import the module without pypdf.
    from pypdf import PdfReader

    details: dict = {"source_file_sha256": digest, "clinical_approval": "not_reviewed"}
    with path.open("rb") as stream:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            return {**details, "status": "encrypted_requires_local_review"}
        page_count = len(reader.pages)
        details["pdf_page_count"] = page_count
        if page_count > max_pages:
            return {**details, "status": "page_limit_exceeded", "configured_page_limit": max_pages}
        metadata = reader.metadata or {}
        details["pdf_metadata_unverified"] = {
            key[1:]: str(metadata[key])[:2000]
            for key in ("/Title", "/Author", "/Subject", "/CreationDate") if metadata.get(key)
        }
        # PDF creation dates are not publication dates; edition/chapter are not
        # inferred from the filename, metadata, page number or extracted prose.
        details.update(publication_year=None, edition=None, bibliographic_review="required")
        try:
            labels = reader.page_labels
        except Exception:
            labels = []
        destination.mkdir(parents=True, exist_ok=False)
        temporary = destination / "pages.jsonl.tmp"
        counts: Counter = Counter()
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            for index, page in enumerate(reader.pages, start=1):
                text = ""
                error_type = None
                try:
                    text = page.extract_text() or ""
                    status = "text_extracted" if text.strip() else "empty_text_requires_ocr_or_manual_review"
                except Exception as error:
                    status = "page_extraction_error"
                    error_type = type(error).__name__
                counts[status] += 1
                output.write(_json({
                    "schema_version": VERSION,
                    "source_file_sha256": digest,
                    "pdf_page_number": index,
                    "pdf_page_label_unverified": labels[index - 1] if index <= len(labels) else None,
                    "printed_page_number_verified": False,
                    "chapter": None,
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "status": status,
                    "error_type": error_type,
                    "is_approved_medical_knowledge": False,
                }) + "\n")
                if show_progress and (index % 25 == 0 or index == page_count):
                    print(f"  PDF pages: {index}/{page_count}", flush=True)
        # A changed source cannot be attributed to its earlier content digest.
        if file_digest(path) != digest:
            temporary.unlink()
            destination.rmdir()
            return {**details, "status": "source_changed_during_read"}
        temporary.replace(destination / "pages.jsonl")
        details["page_status_counts"] = dict(counts)
        details["page_record_count"] = sum(counts.values())
        details["pages_artifact_sha256"] = file_digest(destination / "pages.jsonl")
        details["status"] = "text_extracted" if counts.get("text_extracted", 0) == page_count and page_count else "requires_review"
        details["pages_artifact"] = f"books/{digest}/pages.jsonl"
        return details


def scan_library(
    source: Path, output: Path, *, max_file_mib: int = 1024, max_pages: int = 10000,
    show_progress: bool = False,
) -> tuple[Path, dict]:
    """Only read the selected local directory. Every run has a new output folder."""
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if not source.is_dir():
        raise ValueError("Source must be a directory.")
    if output == source or output.is_relative_to(source):
        raise ValueError("Output must be outside the source directory.")
    if max_file_mib < 1 or max_pages < 1:
        raise ValueError("File and page limits must be positive.")
    # Fail before writing anything if the optional PDF reader is unavailable.
    importlib.metadata.version("pypdf")
    started = datetime.now(timezone.utc)
    run_directory = output / (started.strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    run_directory.mkdir(parents=True, exist_ok=False)
    candidates: list[Path] = []
    entries: list[dict] = []
    traversal_errors: list[str] = []

    def walk_error(error: OSError) -> None:
        traversal_errors.append(type(error).__name__)

    for directory, names, files in os.walk(source, followlinks=False, onerror=walk_error):
        # Do not follow linked/reparse directories into an unselected folder.
        for name in list(names):
            child = Path(directory) / name
            if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                names.remove(name)
                entries.append({"relative_path": child.relative_to(source).as_posix(), "status": "linked_directory_skipped"})
        for name in files:
            candidate = Path(directory) / name
            if candidate.suffix.casefold() in BOOK_SUFFIXES:
                candidates.append(candidate)
    seen: dict[str, dict] = {}
    for index, path in enumerate(sorted(candidates, key=lambda item: item.relative_to(source).as_posix()), start=1):
        entry = {"relative_path": path.relative_to(source).as_posix()}
        if show_progress:
            print(f"Reading {index}/{len(candidates)}: {entry['relative_path']}", flush=True)
        try:
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
                entry["status"] = "linked_file_skipped"
            elif path.suffix.casefold() != ".pdf":
                entry["status"] = "unsupported_format_requires_review"
            elif path.stat().st_size > max_file_mib * 1024 * 1024:
                entry["status"] = "file_size_limit_exceeded"
            else:
                digest = file_digest(path)
                entry["source_file_sha256"] = digest
                if digest in seen:
                    entry.update(status="duplicate_file", duplicate_of=seen[digest]["relative_path"],
                                 source_status=seen[digest]["status"], pages_artifact=seen[digest].get("pages_artifact"))
                else:
                    entry.update(_extract_pdf(path, run_directory / "books" / digest, digest, max_pages, show_progress))
                    seen[digest] = entry
        except Exception as error:
            # Keep the report readable without presenting parser text as facts.
            entry.update(status="file_read_error", error_type=type(error).__name__)
            if "source_file_sha256" in entry:
                temporary = run_directory / "books" / entry["source_file_sha256"] / "pages.jsonl.tmp"
                temporary.unlink(missing_ok=True)
        entries.append(entry)
    entries.sort(key=lambda item: item["relative_path"])
    statuses = Counter(item["status"] for item in entries)
    unresolved = any(item["status"] not in {"text_extracted", "duplicate_file"}
                     or (item["status"] == "duplicate_file" and item["source_status"] != "text_extracted")
                     for item in entries)
    manifest = {
        "schema_version": VERSION,
        "tool": "4b-mos-local-orthopedic-library",
        "tool_version": VERSION,
        "tool_artifact_sha256": file_digest(Path(__file__)),
        "extractor_version": importlib.metadata.version("pypdf"),
        "created_at": started.isoformat(),
        "source_directory": str(source),
        "scope": "local_source_preparation_only",
        "status": "no_books_found" if not entries and not traversal_errors else "requires_review" if unresolved or traversal_errors else "extraction_complete",
        "status_counts": dict(statuses),
        "traversal_errors": traversal_errors,
        "books": entries,
        "draft_proposition_count": 0,
        "approved_proposition_count": 0,
        "is_clinically_validated": False,
        "uploads_performed": False,
    }
    manifest["manifest_sha256"] = hashlib.sha256(_json(manifest).encode("utf-8")).hexdigest()
    _atomic_json(run_directory / "manifest.json", manifest)
    lines = ["4B-MOS | LOCAL ORTHOPEDIC BOOKS", "", f"Source: {source}",
             f"Status: {manifest['status']}", "No upload, medical approval or database write performed.",
             "PDF text is unreviewed source material. Edition, chapter and printed page need review.", ""]
    lines.extend(f"{item['status']}: {item['relative_path']}" for item in entries)
    (run_directory / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_directory, manifest


def verify_library_run(run_directory: Path) -> dict:
    """Verify a local snapshot, including full ordered page records, read-only.

    This verifies extraction artifacts, not medical validity or book identity
    against a current original PDF. No source PDF needs to be opened here.
    """
    run_directory = run_directory.resolve(strict=True)
    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    supplied = manifest.pop("manifest_sha256", None)
    expected = hashlib.sha256(_json(manifest).encode("utf-8")).hexdigest()
    if supplied != expected or manifest.get("schema_version") != VERSION:
        raise ValueError("Extraction manifest integrity check failed.")
    for book in manifest["books"]:
        if book.get("status") == "duplicate_file" or not book.get("pages_artifact"):
            continue
        path = (run_directory / book["pages_artifact"]).resolve(strict=True)
        if not path.is_relative_to(run_directory):
            raise ValueError("Page artifact must stay inside its extraction snapshot.")
        if file_digest(path) != book["pages_artifact_sha256"]:
            raise ValueError("Page artifact integrity check failed.")
        page_count = 0
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, start=1):
                page = json.loads(line)
                page_count += 1
                if (page["pdf_page_number"] != number
                        or page["source_file_sha256"] != book["source_file_sha256"]
                        or page["text_sha256"] != hashlib.sha256(page["text"].encode("utf-8")).hexdigest()
                        or page.get("is_approved_medical_knowledge") is not False):
                    raise ValueError("Page provenance integrity check failed.")
        if page_count != book["page_record_count"]:
            raise ValueError("Page record count mismatch.")
    return {**manifest, "manifest_sha256": supplied}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(DEFAULT_SOURCE))
    parser.add_argument("--output", type=Path, default=default_output())
    parser.add_argument("--max-file-mib", type=int, default=1024)
    parser.add_argument("--max-pages", type=int, default=10000)
    parser.add_argument("--verify", type=Path, help="Verify an existing local run without reading source PDFs")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            verify_library_run(args.verify)
            print("Local extraction snapshot integrity verified. This is not medical approval.")
            return 0
        destination, manifest = scan_library(args.source, args.output, max_file_mib=args.max_file_mib,
                                             max_pages=args.max_pages, show_progress=True)
    except importlib.metadata.PackageNotFoundError:
        print("Install the optional reader first: python -m pip install -r backend/requirements-books.txt", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"Local intake could not start: {error}", file=sys.stderr)
        return 2
    print(f"Status: {manifest['status']}")
    print(f"Local report: {destination / 'report.txt'}")
    print(f"Local manifest: {destination / 'manifest.json'}")
    print("Original books remain on this computer. No cloud connection was created.")
    return 0 if manifest["status"] == "extraction_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
