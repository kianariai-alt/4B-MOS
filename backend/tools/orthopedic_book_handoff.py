"""Prepare a private, text-free source index for orthopedic Draft authoring.

Run on the computer holding the original PDFs. Uses only Python's standard
library and the existing local extractor's snapshot verifier. No database,
network, medical summarization, approval, or automatic Registry import.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

try:
    from .local_orthopedic_library import default_output, file_digest, verify_library_run
except ImportError:  # Direct execution from a Windows launcher, outside repo cwd.
    from local_orthopedic_library import default_output, file_digest, verify_library_run


SCHEMA_ID = "4b-mos.book-source-handoff"
VERSION = "1.0.0"
PAGE_STATUSES = {"text_extracted", "empty_text_requires_ocr_or_manual_review", "page_extraction_error"}
DIGEST = re.compile(r"^[a-f0-9]{64}$")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite JSON value.")


def strict_json(text: str):
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def _digest(value: object) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError("Expected a SHA-256 content identifier.")
    return value


def _relative(root: Path, value: object) -> Path:
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(character) < 32 for character in value)
            or PureWindowsPath(value).drive or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError("Source and artifact locators must be portable relative paths.")
    path = root
    for part in value.split("/"):
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Linked source or artifact paths are not accepted.")
    if not path.resolve().is_relative_to(root):
        raise ValueError("A locator escaped its selected root.")
    return path


def latest_run(root: Path | None = None) -> Path:
    root = (default_output() if root is None else root).resolve(strict=True)
    runs = sorted((path for path in root.glob("run-*")
                   if path.is_dir() and not path.is_symlink()
                   and not (hasattr(path, "is_junction") and path.is_junction())
                   and (path / "manifest.json").is_file()),
                  key=lambda path: ((path / "manifest.json").stat().st_mtime_ns, path.name))
    if not runs:
        raise ValueError("No extraction run with a manifest was found.")
    # A manifest marks a finished extraction attempt, not clinical completeness.
    # Do not silently fall back if the latest finished snapshot is corrupted.
    return runs[-1]


def build_handoff(run_directory: Path, source: Path, *, selection=()) -> dict:
    """Check actual local bytes; return metadata, never page text or knowledge.

    Source is explicitly selected by the caller; manifest.source_directory is
    not used as a filesystem permission grant. A self-checksummed handoff remains
    an unsigned local assertion, requiring source and independent clinical review.
    """
    run_directory = run_directory.expanduser().resolve(strict=True)
    source = source.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError("The explicitly selected source must be a directory.")
    manifest = strict_json((run_directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("books"), list):
        raise ValueError("Invalid extraction manifest.")
    if any(not isinstance(book, dict) for book in manifest["books"]):
        raise ValueError("Every extraction manifest book entry must be an object.")
    if not isinstance(manifest.get("traversal_errors", []), list):
        raise ValueError("Extraction traversal errors must be a list.")
    chosen = set()
    for digest, number in selection:
        _digest(digest)
        if type(number) is not int or number < 1:
            raise ValueError("A PDF page number must be a positive integer.")
        if (digest, number) in chosen:
            raise ValueError("Duplicate selected page.")
        chosen.add((digest, number))

    # Strictly parse all artifacts before reusing the extractor's integrity
    # verifier, whose legacy JSON loader permits duplicate keys.
    books = []
    for book in manifest["books"]:
        if book.get("status") == "duplicate_file" or not book.get("pages_artifact"):
            continue
        digest = _digest(book.get("source_file_sha256"))
        _digest(book.get("pages_artifact_sha256"))
        original = _relative(source, book.get("relative_path"))
        if original.suffix.casefold() != ".pdf":
            raise ValueError("Only PDF source files are accepted.")
        artifact = _relative(run_directory, book["pages_artifact"])
        with artifact.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, start=1):
                page = strict_json(line)
                if (not isinstance(page, dict) or type(page.get("pdf_page_number")) is not int
                        or page["pdf_page_number"] != number
                        or page.get("status") not in PAGE_STATUSES
                        or not isinstance(page.get("text"), str)):
                    raise ValueError("Invalid ordered page record.")
                if page["status"] == "text_extracted" and (not page["text"].strip() or page.get("error_type") is not None):
                    raise ValueError("A successful page must contain nonempty, error-free text.")
        books.append((digest, book, original, artifact))
    if len({entry[0] for entry in books}) != len(books):
        raise ValueError("Duplicate canonical source identifier.")
    checked = verify_library_run(run_directory)
    if not books:
        raise ValueError("No extracted PDF pages are available for a handoff.")
    sources = []
    pages = []
    found = set()
    for digest, book, original, artifact in sorted(books, key=lambda item: item[0]):
        if chosen and not any(key[0] == digest for key in chosen):
            continue
        verification_error = None
        try:
            before = original.stat()
            actual = file_digest(original)
            after = original.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                verification_error = "source_pdf_changed_during_verification"
            elif actual != digest:
                verification_error = "source_pdf_hash_mismatch"
        except OSError:
            verification_error = "source_pdf_unavailable"
        sources.append({
            "source_file_sha256": digest,
            "filename": original.name,
            "source_pdf_verified": verification_error is None,
            "pages_artifact_sha256": book["pages_artifact_sha256"],
            "verification_error": verification_error,
        })
        with artifact.open(encoding="utf-8") as stream:
            for line in stream:
                page = strict_json(line)
                key = (digest, page["pdf_page_number"])
                if chosen and key not in chosen:
                    continue
                if chosen and page["status"] != "text_extracted":
                    raise ValueError("A selected page is empty or has an extraction error.")
                found.add(key)
                pages.append({"source_file_sha256": digest, "pdf_page_number": page["pdf_page_number"],
                              "text_sha256": page["text_sha256"], "status": page["status"]})
    if chosen - found:
        raise ValueError("One or more selected pages do not exist in this snapshot.")
    if len(pages) > 100000 or len(sources) > 1000:
        raise ValueError("Handoff size exceeds the authoring contract limits.")
    # Bind exactly the bytes read again; the original verifier completed earlier.
    # Recheck artifacts after building metadata to catch changes between passes.
    for _, book, _, artifact in books:
        if file_digest(artifact) != book["pages_artifact_sha256"]:
            raise ValueError("A page artifact changed during handoff preparation.")
    if strict_json((run_directory / "manifest.json").read_text(encoding="utf-8")) != checked:
        raise ValueError("The extraction manifest changed during preparation.")
    result = {
        "schema_id": SCHEMA_ID, "schema_version": VERSION,
        "scope": "selected_extracted_pages" if chosen else "available_extracted_pages",
        "omitted_entry_count": len(manifest["books"]) - len(sources),
        "unresolved_entry_count": sum(
            book.get("status") not in {"text_extracted", "duplicate_file"}
            or (book.get("status") == "duplicate_file" and book.get("source_status") != "text_extracted")
            for book in manifest["books"]
        ),
        "traversal_error_count": len(manifest.get("traversal_errors", [])),
        "extraction_manifest_sha256": checked["manifest_sha256"],
        "verifier_artifact_sha256": hashlib.sha256(canonical({
            "handoff_tool_sha256": file_digest(Path(__file__)),
            "snapshot_verifier_sha256": file_digest(Path(verify_library_run.__code__.co_filename)),
        }).encode("utf-8")).hexdigest(),
        "sources": sources, "pages": pages,
        "uploads_performed": False, "is_clinically_validated": False,
        "registry_write_performed": False,
    }
    result["handoff_sha256"] = hashlib.sha256(canonical(result).encode("utf-8")).hexdigest()
    return result


def _selection(value: str) -> tuple[str, int]:
    try:
        digest, number = value.rsplit(":", 1)
        _digest(digest)
        if not re.fullmatch(r"[1-9][0-9]*", number):
            raise ValueError
        return digest, int(number)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use PDF_SHA256:positive_page_number.") from error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--run", type=Path, help="An existing extraction run")
    location.add_argument("--latest", action="store_true", help="Latest finished attempt under the local library output")
    parser.add_argument("--source", required=True, type=Path, help="Explicit original PDF directory")
    parser.add_argument("--page", action="append", type=_selection, default=[], help="Optional PDF_SHA256:page; repeat to select")
    parser.add_argument("--output", type=Path, help="New private JSON file outside sources and extraction snapshot")
    args = parser.parse_args(argv)
    try:
        run = latest_run() if args.latest else args.run.expanduser().resolve(strict=True)
        source = args.source.expanduser().resolve(strict=True)
        destination = args.output.expanduser().resolve() if args.output else None
        if destination and (destination.is_relative_to(source) or destination.is_relative_to(run)):
            raise ValueError("Output must stay outside the books and extraction snapshot.")
        print("Checking extraction records and original PDFs; no book text is exported.", file=sys.stderr, flush=True)
        result = build_handoff(run, source, selection=args.page)
        content = canonical(result) + "\n"
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            print(f"Private handoff: {destination}", file=sys.stderr)
        else:
            sys.stdout.write(content)
        ineligible = sum(p["status"] != "text_extracted" for p in result["pages"])
        unverified = sum(not s["source_pdf_verified"] for s in result["sources"])
        print(f"Pages indexed: {len(result['pages'])}; ineligible pages: {ineligible}; unverified PDFs: {unverified}.", file=sys.stderr)
        print(f"Omitted entries: {result['omitted_entry_count']}; unresolved extraction entries: {result['unresolved_entry_count']}; traversal errors: {result['traversal_error_count']}.", file=sys.stderr)
        print("Source and independent clinical review remain required. No Registry import or approval performed.", file=sys.stderr)
        whole_snapshot_issues = not args.page and (result["unresolved_entry_count"] or result["traversal_error_count"])
        return 1 if ineligible or unverified or whole_snapshot_issues else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Handoff could not be prepared: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
