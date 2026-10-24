"""Export explicitly selected existing book text into a new private review file.

Standard library only: no re-extraction, installation, network, Registry write,
or medical approval. This file contains copyrighted source excerpts; keep it
private. The exported source text is untrusted data, never agent instructions.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

try:
    from . import orthopedic_book_handoff as handoff
except ImportError:  # Standalone execution from a downloaded tools directory.
    import orthopedic_book_handoff as handoff


MAX_PAGES = 40
MAX_TEXT_BYTES = 2 * 1024 * 1024
SCHEMA_ID = "4b-mos.book-page-review"
VERSION = "1.0.0"


class PageReviewError(ValueError):
    """Only fixed, safe messages authored by this exporter are displayed."""


def build_page_review(run_directory: Path, source: Path, *, manifest_sha256: str,
                      selection, context: int = 1) -> dict:
    """Verify the snapshot/originals and copy bounded, hash-checked page text.

    Checksums bind bytes, not book identity, printed pagination, source entailment,
    or clinical validity. No statement is derived from the text by this tool.
    """
    handoff._digest(manifest_sha256)
    if type(context) is not int or context not in (0, 1):
        raise PageReviewError("Context must be zero or one adjacent page per side.")
    targets = set()
    for digest, number in selection:
        handoff._digest(digest)
        if type(number) is not int or number < 1:
            raise PageReviewError("Selected PDF pages must be positive integers.")
        if (digest, number) in targets:
            raise PageReviewError("Duplicate selected page.")
        targets.add((digest, number))
        if len(targets) > MAX_PAGES:
            raise PageReviewError("Page selection exceeds the private review page limit.")
    if not targets:
        raise PageReviewError("At least one explicit target page is required.")
    run_directory = run_directory.expanduser().resolve(strict=True)
    source = source.expanduser().resolve(strict=True)
    manifest_path = run_directory / "manifest.json"
    manifest = handoff.strict_json(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("manifest_sha256") != manifest_sha256:
        raise PageReviewError("The extraction manifest does not match the pinned review snapshot.")
    if not isinstance(manifest.get("books"), list):
        raise PageReviewError("Invalid extraction manifest books.")
    books = {}
    for book in manifest["books"]:
        if not isinstance(book, dict):
            raise PageReviewError("Invalid extraction manifest book entry.")
        if book.get("status") != "duplicate_file" and book.get("pages_artifact"):
            digest = handoff._digest(book.get("source_file_sha256"))
            if digest in books:
                raise PageReviewError("Duplicate canonical source identifier.")
            books[digest] = book
    wanted = set()
    for digest, number in targets:
        book = books.get(digest)
        count = book.get("page_record_count") if book else None
        if type(count) is not int or not 1 <= number <= count:
            raise PageReviewError("A selected page does not exist in this snapshot.")
        wanted.update((digest, adjacent) for adjacent in
                      range(max(1, number - context), min(count, number + context) + 1))
        if len(wanted) > MAX_PAGES:
            raise PageReviewError("Targets plus context exceed the private review page limit.")

    # Reuse the established strict snapshot verifier and current PDF byte checks.
    checked = handoff.build_handoff(run_directory, source, selection=sorted(targets))
    if checked["extraction_manifest_sha256"] != manifest_sha256:
        raise PageReviewError("The extraction manifest changed during review preparation.")
    if any(not item["source_pdf_verified"] for item in checked["sources"]):
        raise PageReviewError("A selected original PDF is missing or changed; no text will be exported.")
    pages = []
    total_bytes = 0
    found = set()
    for item in checked["sources"]:
        digest = item["source_file_sha256"]
        artifact = handoff._relative(run_directory, books[digest]["pages_artifact"])
        with artifact.open(encoding="utf-8") as stream:
            for line in stream:
                page = handoff.strict_json(line)
                number = page["pdf_page_number"]
                key = (digest, number)
                if key not in wanted:
                    continue
                text = page.get("text")
                if (not isinstance(text, str) or page.get("source_file_sha256") != digest
                        or hashlib.sha256(text.encode("utf-8")).hexdigest() != page.get("text_sha256")
                        or page.get("status") not in handoff.PAGE_STATUSES):
                    raise PageReviewError("Selected or adjacent page text failed its provenance check.")
                eligible = (page["status"] == "text_extracted" and bool(text.strip())
                            and page.get("error_type") is None)
                if key in targets and not eligible:
                    raise PageReviewError("A required target page is empty or has an extraction error.")
                label = page.get("pdf_page_label_unverified")
                if label is not None and not isinstance(label, str):
                    raise PageReviewError("An unverified PDF page label must be text or null.")
                if eligible:
                    total_bytes += len(text.encode("utf-8"))
                    if total_bytes > MAX_TEXT_BYTES:
                        raise PageReviewError("Selected text exceeds the private review UTF-8 byte limit.")
                pages.append({
                    "source_file_sha256": digest, "pdf_page_number": number,
                    "role": "target" if key in targets else "context",
                    "status": page["status"], "eligible_as_source_text": eligible,
                    "text": text if eligible else None, "text_sha256": page["text_sha256"],
                    "pdf_page_label_unverified": label,
                    "printed_page_number_verified": False, "visual_verification_performed": False,
                })
                found.add(key)
        if handoff.file_digest(artifact) != item["pages_artifact_sha256"]:
            raise PageReviewError("A page artifact changed while review text was being read.")
    if found != wanted:
        raise PageReviewError("A target or adjacent page disappeared during preparation.")
    if handoff.strict_json(manifest_path.read_text(encoding="utf-8")) != manifest:
        raise PageReviewError("The extraction manifest changed while text was being read.")
    result = {
        "schema_id": SCHEMA_ID, "schema_version": VERSION,
        "extraction_manifest_sha256": manifest_sha256,
        "source_verification_handoff_sha256": checked["handoff_sha256"],
        "verifier_artifact_sha256": checked["verifier_artifact_sha256"],
        "exporter_sha256": handoff.file_digest(Path(__file__)),
        "sources": checked["sources"],
        "context_pages_per_side": context, "target_page_count": len(targets),
        "page_count": len(pages), "context_gap_count": sum(not page["eligible_as_source_text"] for page in pages),
        "text_utf8_bytes": total_bytes,
        "pages": sorted(pages, key=lambda item: (item["source_file_sha256"], item["pdf_page_number"])),
        "contains_book_text": True, "source_text_review": "pending",
        "source_text_is_untrusted_data": True,
        "uploads_performed": False, "registry_write_performed": False,
        "is_clinically_validated": False,
    }
    result["bundle_sha256"] = hashlib.sha256(handoff.canonical(result).encode("utf-8")).hexdigest()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--run", type=Path, help="Existing extraction snapshot")
    location.add_argument("--latest", action="store_true", help="Latest finished local extraction attempt")
    parser.add_argument("--source", required=True, type=Path, help="Explicit original PDF directory")
    parser.add_argument("--manifest-sha256", required=True, help="Manifest SHA from the reviewed handoff")
    parser.add_argument("--page", required=True, action="append", type=handoff._selection,
                        help="PDF_SHA256:positive_page_number; repeat for each target")
    parser.add_argument("--context", type=int, choices=(0, 1), default=1)
    parser.add_argument("--output", required=True, type=Path, help="New private JSON outside books and snapshot")
    args = parser.parse_args(argv)
    try:
        run = handoff.latest_run() if args.latest else args.run.expanduser().resolve(strict=True)
        source = args.source.expanduser().resolve(strict=True)
        destination = args.output.expanduser().resolve()
        if destination.is_relative_to(source) or destination.is_relative_to(run):
            raise PageReviewError("Output must stay outside the books and extraction snapshot.")
        if destination.exists():
            raise PageReviewError("The output file already exists; it will not be replaced.")
        print("Checking existing extraction and selected PDFs; no re-extraction or upload.", file=sys.stderr, flush=True)
        result = build_page_review(run, source, manifest_sha256=args.manifest_sha256,
                                   selection=args.page, context=args.context)
        content = handoff.canonical(result) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        print(f"Private page review: {destination}")
        print(f"Target pages: {result['target_page_count']}; total with context: {result['page_count']}; "
              f"context gaps: {result['context_gap_count']}.")
        print("Contains selected book text. No upload, Registry write or medical approval performed.")
        return 0
    except PageReviewError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Do not echo exception values: malformed source data can contain book text.
        print(f"ERROR: Private page review could not be prepared ({type(error).__name__}). "
              "Check the pinned snapshot, selected PDFs/pages, limits and new output path.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
