"""Validate an offline metadata handoff and prepare a source-bound Draft preview.

There is no database access, import, approval, upload, filesystem write, or
automatic source extraction here. Self-declared hashes detect inconsistency;
they are not a signature or proof that a book supports a proposed medical claim.
The verifier artifact digest identifies both executable sources: SHA-256 of
canonical compact JSON {handoff_tool_sha256: <wrapper source SHA-256>,
snapshot_verifier_sha256: <currently imported local_orthopedic_library.py source
SHA-256>}. Export scope, omission/unresolved counts, and traversal-error counts
are integrity-bound by the handoff digest, which is also bound into each Draft's
provenance. These metadata do not establish clinical validation or completeness.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence

from backend.app.schemas.medical_knowledge import KnowledgeFactContent, KnowledgeFactCreate
from backend.app.schemas.orthopedic_book_handoff import (
    BookDraftPageProvenance,
    BookDraftPreview,
    BookDraftProvenance,
    BookPageReference,
    BookSourceHandoff,
    ProposalOrigin,
)
from backend.app.services.medical_knowledge import knowledge_content_digest

PROVENANCE_MARKER = "\n\nBook Draft provenance v1:\n"
EMPTY_TEXT_SHA256 = hashlib.sha256(b"").hexdigest()


class BookHandoffIntegrityError(ValueError):
    """Metadata or its references do not match the claimed handoff digest."""


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def book_handoff_digest(handoff: BookSourceHandoff | Mapping) -> str:
    """Hash normalized schema fields, including optional verification_error:null.

    Input dictionaries may omit handoff_sha256 while computing their hash. Schema
    validation still rejects unknown fields and invalid references. A placeholder
    is used only internally and is excluded from the digest payload.
    """
    if isinstance(handoff, BookSourceHandoff):
        payload = handoff.model_dump(mode="json")
    else:
        payload = dict(handoff)
        payload.setdefault("handoff_sha256", "0" * 64)
    normalized = BookSourceHandoff.model_validate(payload)
    content = normalized.model_dump(mode="json", exclude={"handoff_sha256"})
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def validate_book_handoff(handoff: BookSourceHandoff | Mapping) -> BookSourceHandoff:
    """Fail closed on invalid metadata, dangling pages, or content tampering."""
    payload = handoff.model_dump(mode="json") if isinstance(handoff, BookSourceHandoff) else dict(handoff)
    normalized = BookSourceHandoff.model_validate(payload)
    if not hmac.compare_digest(book_handoff_digest(normalized), normalized.handoff_sha256):
        raise BookHandoffIntegrityError("Book handoff digest does not match its metadata.")
    return normalized


def prepare_book_draft(
    proposal: KnowledgeFactCreate,
    handoff: BookSourceHandoff | Mapping,
    page_refs: Sequence[BookPageReference | Mapping],
    chapter: str,
    *,
    proposal_origin: ProposalOrigin,
    reported_printed_pages: str | None = None,
) -> BookDraftPreview:
    """Bind one manually authored book citation to technical page provenance.

    The returned existing KnowledgeFactCreate remains an unsaved Draft proposal.
    Its statement includes canonical provenance before Registry hashing. This
    binds the hash to the selected pages but does not establish source entailment
    or verify the author's bibliographic citation against the original PDF.
    """
    validated = validate_book_handoff(handoff)
    if not isinstance(proposal, KnowledgeFactCreate):
        raise TypeError("A validated existing KnowledgeFactCreate proposal is required.")
    # Revalidation also checks mutable nested Registry models before hashing.
    raw = proposal.model_dump(mode="json")
    checked = KnowledgeFactCreate.model_validate(raw)
    if checked.evidence_grade != "ungraded":
        raise ValueError("A book Draft preview must retain ungraded evidence.")
    if not checked.population or not checked.indication:
        raise ValueError("A book Draft requires an explicit population and application indication.")
    if len(checked.sources) != 1 or checked.sources[0].source_type != "textbook":
        raise ValueError("Exactly one manually identified textbook citation is required.")
    if "accessed_at" not in proposal.sources[0].model_fields_set:
        raise ValueError("The source access date must be explicitly supplied, not automatically inferred.")
    if PROVENANCE_MARKER in checked.statement:
        raise ValueError("A proposal already contains book Draft provenance; review it rather than nesting previews.")
    references = tuple(
        BookPageReference.model_validate(item.model_dump(mode="json") if isinstance(item, BookPageReference) else dict(item))
        for item in page_refs
    )
    if not references:
        raise ValueError("At least one source page is required.")
    keys = [(item.source_file_sha256, item.pdf_page_number) for item in references]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate selected source/page reference.")
    source_hashes = {item.source_file_sha256 for item in references}
    if len(source_hashes) != 1:
        raise ValueError("One book citation must reference pages from exactly one book.")
    selected_hash = next(iter(source_hashes))
    sources = {item.source_file_sha256: item for item in validated.sources}
    selected_source = sources.get(selected_hash)
    if selected_source is None:
        raise ValueError("Selected book source does not exist in the handoff.")
    if not selected_source.source_pdf_verified or selected_source.verification_error is not None:
        raise ValueError("A Draft preview requires successful technical verification of the original source PDF.")
    pages = {(item.source_file_sha256, item.pdf_page_number): item for item in validated.pages}
    selected_pages = []
    for key in sorted(keys):
        page = pages.get(key)
        if page is None:
            raise ValueError("A selected page does not exist in the handoff.")
        if page.status != "text_extracted" or page.text_sha256 == EMPTY_TEXT_SHA256:
            raise ValueError("A selected page lacks nonempty extracted text and requires source review.")
        selected_pages.append(BookDraftPageProvenance(
            source_file_sha256=page.source_file_sha256,
            pdf_page_number=page.pdf_page_number,
            text_sha256=page.text_sha256,
        ))
    provenance = BookDraftProvenance(
        extraction_manifest_sha256=validated.extraction_manifest_sha256,
        verifier_artifact_sha256=validated.verifier_artifact_sha256,
        handoff_sha256=validated.handoff_sha256,
        source_file_sha256=selected_source.source_file_sha256,
        filename=selected_source.filename,
        pages_artifact_sha256=selected_source.pages_artifact_sha256,
        pages=tuple(selected_pages),
        chapter=chapter,
        reported_printed_pages=reported_printed_pages,
        proposal_origin=proposal_origin,
    )
    raw["statement"] = checked.statement + PROVENANCE_MARKER + _canonical_json(provenance.model_dump(mode="json"))
    bound = KnowledgeFactCreate.model_validate(raw)
    content = KnowledgeFactContent.model_validate(bound.model_dump(exclude={"fact_key"}))
    digest = knowledge_content_digest(fact_key=bound.fact_key, version=1, content=content)
    return BookDraftPreview(
        proposal=bound,
        provenance=provenance,
        content_sha256=digest,
        proposal_origin=provenance.proposal_origin,
    )
