"""Read/validate an additive Draft book supplement without database access.

This is explicit authoring preparation, not Registry import, runtime knowledge,
medical approval, source authentication, or a claim of independent review.
"""
from __future__ import annotations

from collections.abc import Mapping
import hmac
from pathlib import Path

from backend.app.schemas.medical_knowledge import KnowledgeFactCreate
from backend.app.schemas.orthopedic_book_handoff import BookSourceHandoff
from backend.app.schemas.orthopedic_book_review import BookReviewEntry, KneeBookReviewPack
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack, content_digest
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError
from backend.app.services.orthopedic_book_handoff import prepare_book_draft, validate_book_handoff
from backend.app.services.orthopedic_knowledge import load_knee_pack, validate_knee_pack


BOOK_REVIEW_PACK_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "knee_book_review_v1.json"


def _proposal(entry: BookReviewEntry) -> KnowledgeFactCreate:
    return KnowledgeFactCreate(
        fact_key=entry.registry_fact_key, title=entry.title,
        statement=entry.authoring_statement(), clinical_domain="orthopedics_knee",
        therapy_type=entry.therapy_type, population=entry.population,
        indication=entry.indication, evidence_grade="ungraded",
        sources=[entry.source.model_copy(deep=True)],
    )


def bind_book_review_entry(raw_entry: Mapping, source_handoff: BookSourceHandoff | Mapping) -> BookReviewEntry:
    """Prepare one manually authored entry; never create a Registry record.

    A supporting-reference entry is checked with the same provenance machinery
    but never exposes its temporary authoring calculation as a creation payload.
    """
    raw = dict(raw_entry)
    raw["draft_preview"] = None
    entry = BookReviewEntry.model_validate(raw)
    provenance = entry.provenance
    preview = prepare_book_draft(
        _proposal(entry), source_handoff,
        [{"source_file_sha256": page.source_file_sha256, "pdf_page_number": page.pdf_page_number}
         for page in provenance.pages], provenance.chapter,
        proposal_origin="ai_assisted_draft",
        reported_printed_pages=provenance.reported_printed_pages,
    )
    if preview.provenance != provenance:
        raise MedicalKnowledgeIntegrityError("Book review provenance does not match the source handoff.")
    if entry.action == "new_fact":
        raw["draft_preview"] = preview.model_dump(mode="json")
    return BookReviewEntry.model_validate(raw)


def book_review_pack_digest(pack: KneeBookReviewPack | Mapping) -> str:
    """Canonical normalized metadata checksum; not a medical/source signature."""
    raw = pack.model_dump(mode="json") if isinstance(pack, KneeBookReviewPack) else dict(pack)
    raw.setdefault("manifest_sha256", "0" * 64)
    checked = KneeBookReviewPack.model_validate(raw)
    return content_digest(checked.model_dump(mode="json", exclude={"manifest_sha256"}))


def validate_knee_book_review_pack(
    pack: KneeBookReviewPack | Mapping, base_pack: KneeKnowledgePack | None = None,
) -> KneeBookReviewPack:
    """Revalidate nested mutable Registry models, provenance and content hashes."""
    raw = pack.model_dump(mode="json") if isinstance(pack, KneeBookReviewPack) else dict(pack)
    checked = KneeBookReviewPack.model_validate(raw)
    base = load_knee_pack() if base_pack is None else validate_knee_pack(base_pack)
    if checked.base_pack_manifest_sha256 != base.manifest_sha256:
        raise MedicalKnowledgeIntegrityError("Book review base pack manifest does not match the reviewed knee pack.")
    handoff = validate_book_handoff(checked.source_handoff)
    base_facts = {entry.fact.fact_key: entry for entry in base.facts}
    reviewed_pages = {(page.source_file_sha256, page.pdf_page_number): page for page in checked.reviewed_pages}
    handoff_pages = {(page.source_file_sha256, page.pdf_page_number): page for page in handoff.pages}
    # Every originally selected page stays visible among the reviewed-page hashes.
    for key, page in handoff_pages.items():
        reviewed = reviewed_pages.get(key)
        if reviewed is None or reviewed.text_sha256 != page.text_sha256:
            raise MedicalKnowledgeIntegrityError("Reviewed pages do not match the selected source handoff.")
    for entry in checked.entries:
        for reference in entry.related_facts:
            target = base_facts.get(reference.fact_key)
            if target is None:
                raise MedicalKnowledgeIntegrityError("Book review references an unknown base fact.")
            if target.version != reference.version or target.content_sha256 != reference.content_sha256:
                raise MedicalKnowledgeIntegrityError("Book review base fact content/version has changed.")
        if entry.action == "new_fact" and entry.registry_fact_key in base_facts:
            raise MedicalKnowledgeIntegrityError("A new book fact collides with an existing base fact key.")
        if entry.action == "support_existing" and entry.registry_fact_key not in base_facts:
            raise MedicalKnowledgeIntegrityError("Supporting evidence targets an unknown base fact.")
        for page in entry.provenance.pages:
            key = (page.source_file_sha256, page.pdf_page_number)
            reviewed = reviewed_pages.get(key)
            if reviewed is None or reviewed != page:
                raise MedicalKnowledgeIntegrityError("A book claim references an unreviewed or mismatched page.")
        rebound = bind_book_review_entry(entry.model_dump(mode="json"), handoff)
        if entry != rebound:
            raise MedicalKnowledgeIntegrityError("Book review Draft content hash or bound authoring metadata differs.")
    if not hmac.compare_digest(book_review_pack_digest(checked), checked.manifest_sha256):
        raise MedicalKnowledgeIntegrityError("Book review pack manifest hash mismatch.")
    return checked


def load_knee_book_review_pack(path: Path = BOOK_REVIEW_PACK_PATH) -> KneeBookReviewPack:
    return validate_knee_book_review_pack(KneeBookReviewPack.model_validate_json(Path(path).read_text(encoding="utf-8")))


def new_book_registry_proposals(pack: KneeBookReviewPack | Mapping | None = None) -> tuple[KnowledgeFactCreate, ...]:
    """Return detached existing-Registry Draft payloads; supporting entries omitted.

    No database session or writer is accepted. Calling this function imports or
    approves nothing and cannot alter the 27-fact base pack.
    """
    checked = load_knee_book_review_pack() if pack is None else validate_knee_book_review_pack(pack)
    return tuple(entry.draft_preview.proposal.model_copy(deep=True)
                 for entry in checked.entries if entry.action == "new_fact")
