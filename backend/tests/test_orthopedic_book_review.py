"""Draft authoring reconciliation only; no textbook excerpts or patient data."""
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.schemas.medical_knowledge import KnowledgeFactContent
from backend.app.schemas.orthopedic_book_review import KneeBookReviewPack
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.services.medical_knowledge import (
    MedicalKnowledgeIntegrityError,
    MedicalKnowledgeService,
    knowledge_content_digest,
)
from backend.app.services.orthopedic_book_review import (
    bind_book_review_entry,
    load_knee_book_review_pack,
    new_book_registry_proposals,
    validate_knee_book_review_pack,
)
from backend.app.services.orthopedic_knowledge import PACK_PATH, load_knee_pack


INVALID = (ValueError, MedicalKnowledgeIntegrityError)


@pytest.fixture
def pack():
    return load_knee_book_review_pack()


@pytest.fixture
def payload(pack):
    return pack.model_dump(mode="json")


def rehash(payload):
    payload["manifest_sha256"] = content_digest(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    return payload


def validate(payload):
    return validate_knee_book_review_pack(KneeBookReviewPack.model_validate(payload))


def first_new(payload):
    return next(entry for entry in payload["entries"] if entry["action"] == "new_fact")


def test_reconciliation_preserves_base_and_produces_only_eight_new_scoped_drafts(pack):
    base = load_knee_pack()
    assert len(base.facts) == 27
    assert pack.base_pack_manifest_sha256 == base.manifest_sha256
    assert len(pack.entries) == 9
    assert {entry.candidate_key for entry in pack.entries} == {
        f"BOOK.KNEE.{number:03d}" for number in range(1, 10)
    }
    new_entries = [entry for entry in pack.entries if entry.action == "new_fact"]
    supporting = [entry for entry in pack.entries if entry.action == "support_existing"]
    assert len(new_entries) == 8 and len(supporting) == 1
    assert supporting[0].candidate_key == "BOOK.KNEE.004"
    assert supporting[0].registry_fact_key == "KNEE.CARTILAGE.CLASSIFICATION"
    assert supporting[0].support_scope == "location_component_only"
    assert supporting[0].draft_preview is None
    assert not {entry.registry_fact_key for entry in new_entries} & {
        entry.fact.fact_key for entry in base.facts
    }
    proposals = new_book_registry_proposals(pack)
    assert len(proposals) == 8
    assert {proposal.fact_key for proposal in proposals} == {
        entry.registry_fact_key for entry in new_entries
    }
    assert all(proposal.evidence_grade == "ungraded" for proposal in proposals)
    assert pack.status == "draft" and pack.runtime_use == "authoring_only"
    assert pack.requires_independent_review and not pack.is_clinically_validated
    assert not pack.registry_write_performed and not pack.contains_book_text


def test_primary_citations_are_source_bound_and_remain_unverified_clinically(pack):
    pages = {(page.source_file_sha256, page.pdf_page_number): page
             for page in pack.source_handoff.pages}
    reviewed = {(page.source_file_sha256, page.pdf_page_number): page
                for page in pack.reviewed_pages}
    assert len(pack.reviewed_pages) == 37
    assert len(pack.source_handoff.sources) == 3
    assert len(pack.source_handoff.pages) == 17
    for entry in pack.entries:
        provenance = entry.provenance
        assert entry.source.source_type == "textbook"
        assert provenance.proposal_origin == "ai_assisted_draft"
        assert provenance.source_entailment_review == "pending"
        assert provenance.clinical_source_review == "pending"
        assert provenance.bibliographic_identity_review == "pending"
        assert provenance.printed_page_verification == "unverified"
        for page in provenance.pages:
            key = (page.source_file_sha256, page.pdf_page_number)
            assert page.text_sha256 == pages[key].text_sha256 == reviewed[key].text_sha256
        if entry.draft_preview is not None:
            preview = entry.draft_preview
            assert preview.status == "draft" and not preview.registry_write_performed
            assert preview.requires_independent_review and not preview.is_clinically_validated
            assert preview.provenance == provenance
            content = KnowledgeFactContent.model_validate(
                preview.proposal.model_dump(exclude={"fact_key"})
            )
            assert preview.content_sha256 == knowledge_content_digest(
                fact_key=entry.registry_fact_key, version=1, content=content
            )


def test_hypothesis_and_historical_review_scopes_are_preserved_in_registry_hash(pack):
    by_id = {entry.candidate_key: entry for entry in pack.entries}
    assert by_id["BOOK.KNEE.007"].evidence_scope == "historical_evidence_summary"
    assert by_id["BOOK.KNEE.008"].evidence_scope == "proposed_mechanism"
    for key in ("BOOK.KNEE.007", "BOOK.KNEE.008"):
        entry = by_id[key]
        statement = entry.draft_preview.proposal.statement
        assert entry.evidence_scope in statement
        assert entry.page_review_bundle_sha256 in statement
        for limitation in entry.limitations:
            assert limitation in statement
        for condition in entry.application_conditions:
            assert condition in statement
        assert '"source_entailment_review":"pending"' in statement


def test_loading_and_previewing_leave_base_bytes_and_database_unchanged(db_session, monkeypatch):
    before = PACK_PATH.read_bytes()

    def forbidden_creation(*args, **kwargs):
        raise AssertionError("Authoring review must never create a Registry record.")

    monkeypatch.setattr(MedicalKnowledgeService, "create", forbidden_creation)
    existing = list(db_session.scalars(select(MedicalKnowledgeFact)))
    pack = load_knee_book_review_pack()
    assert len(new_book_registry_proposals(pack)) == 8
    assert list(db_session.scalars(select(MedicalKnowledgeFact))) == existing
    assert PACK_PATH.read_bytes() == before
    assert load_knee_pack().manifest_sha256 == pack.base_pack_manifest_sha256


def test_returned_proposals_are_copies_not_mutable_views_of_pack(pack):
    entry = next(entry for entry in pack.entries if entry.draft_preview is not None)
    original = entry.draft_preview.proposal.title
    proposals = new_book_registry_proposals(pack)
    next(proposal for proposal in proposals if proposal.fact_key == entry.registry_fact_key).title = (
        "Synthetic caller mutation"
    )
    assert entry.draft_preview.proposal.title == original
    validate_knee_book_review_pack(pack)


def test_pack_manifest_rejects_unbound_metadata_change(payload):
    first_new(payload)["title"] = "Synthetic altered authoring title"
    with pytest.raises(INVALID):
        validate(payload)


def test_base_manifest_pin_is_checked_even_with_recomputed_supplement_manifest(payload):
    payload["base_pack_manifest_sha256"] = "f" * 64
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_related_base_fact_hash_is_checked_after_rebinding_entry_and_manifest(payload):
    entry = first_new(payload)
    entry["related_facts"][0]["content_sha256"] = "f" * 64
    rebound = bind_book_review_entry(entry, payload["source_handoff"])
    payload["entries"][payload["entries"].index(entry)] = rebound.model_dump(mode="json")
    with pytest.raises(INVALID):
        validate(rehash(payload))


@pytest.mark.parametrize("field", ["limitations", "application_conditions", "evidence_scope", "page_review_bundle_sha256"])
def test_recomputed_pack_checksum_cannot_hide_unbound_clinical_metadata(payload, field):
    entry = first_new(payload)
    if field in {"limitations", "application_conditions"}:
        entry[field] = ["Synthetic altered clinical scope requiring new Registry content review."]
    elif field == "evidence_scope":
        entry[field] = "proposed_mechanism" if entry[field] != "proposed_mechanism" else "clinical_assessment"
    else:
        entry[field] = "f" * 64
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_mutable_nested_registry_payload_is_revalidated_even_with_new_manifest(pack):
    preview = next(entry.draft_preview for entry in pack.entries if entry.draft_preview is not None)
    preview.proposal.title = "Synthetic changed mutable Registry title"
    payload = pack.model_dump(mode="json")
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_new_fact_cannot_collide_with_an_existing_base_key(payload):
    entry = first_new(payload)
    entry["registry_fact_key"] = "KNEE.OA.KL_CONTEXT"
    rebound = bind_book_review_entry(entry, payload["source_handoff"])
    payload["entries"][payload["entries"].index(entry)] = rebound.model_dump(mode="json")
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_supporting_reference_cannot_produce_a_replacement_or_creation_payload(payload):
    support = next(entry for entry in payload["entries"] if entry["action"] == "support_existing")
    support["draft_preview"] = first_new(payload)["draft_preview"]
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_support_target_must_exist_in_the_pinned_base(payload):
    support = next(entry for entry in payload["entries"] if entry["action"] == "support_existing")
    support["registry_fact_key"] = "KNEE.SYNTHETIC.MISSING"
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_location_support_cannot_be_redirected_to_another_known_base_fact(payload):
    support = next(entry for entry in payload["entries"] if entry["action"] == "support_existing")
    other = load_knee_pack().get_fact("KNEE.OA.KL_CONTEXT")
    support["registry_fact_key"] = other.fact.fact_key
    support["related_facts"] = [{"fact_key": other.fact.fact_key, "version": other.version,
                                  "content_sha256": other.content_sha256}]
    with pytest.raises(INVALID):
        validate(rehash(payload))


@pytest.mark.parametrize("field", ["candidate_key", "registry_fact_key"])
def test_duplicate_candidate_or_registry_target_is_rejected(payload, field):
    payload["entries"][1][field] = payload["entries"][0][field]
    with pytest.raises(INVALID):
        validate(rehash(payload))


@pytest.mark.parametrize("change", ["wrong_page_hash", "missing_page", "wrong_source", "wrong_artifact"])
def test_primary_provenance_cannot_be_detached_from_verified_handoff(payload, change):
    entry = first_new(payload)
    if change == "wrong_page_hash":
        entry["provenance"]["pages"][0]["text_sha256"] = "f" * 64
    elif change == "missing_page":
        entry["provenance"]["pages"][0]["pdf_page_number"] = 99999
    elif change == "wrong_source":
        entry["provenance"]["source_file_sha256"] = "f" * 64
    else:
        entry["provenance"]["pages_artifact_sha256"] = "f" * 64
    with pytest.raises(INVALID):
        validate(rehash(payload))


@pytest.mark.parametrize("flag", ["contains_book_text", "registry_write_performed", "is_clinically_validated"])
@pytest.mark.parametrize("value", [True, 0, "false"])
def test_false_governance_flags_are_strict_json_booleans(payload, flag, value):
    payload[flag] = value
    with pytest.raises(ValidationError):
        KneeBookReviewPack.model_validate(payload)


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_independent_review_requirement_cannot_be_removed_or_coerced(payload, value):
    payload["requires_independent_review"] = value
    with pytest.raises(ValidationError):
        KneeBookReviewPack.model_validate(payload)


def test_review_catalog_exports_no_page_text_or_absolute_local_paths(pack):
    data = pack.model_dump(mode="json")

    def walk(value):
        if isinstance(value, dict):
            assert "text" not in value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            assert "C:\\Users\\" not in value
            assert "D:\\orthopedic book" not in value

    walk(data)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
@pytest.mark.parametrize("location", ["pack", "base_reference"])
def test_versions_cannot_coerce_booleans_floats_or_strings(payload, value, location):
    if location == "pack":
        payload["pack_version"] = value
    else:
        first_new(payload)["related_facts"][0]["version"] = value
    with pytest.raises(ValidationError):
        KneeBookReviewPack.model_validate(payload)


def test_book_access_date_cannot_be_silently_filled_by_registry_source_default(payload):
    del first_new(payload)["source"]["accessed_at"]
    with pytest.raises(ValidationError, match="explicitly supplied"):
        KneeBookReviewPack.model_validate(payload)


def test_draft_preview_cannot_upgrade_book_evidence_with_a_new_catalog_checksum(payload):
    first_new(payload)["draft_preview"]["proposal"]["evidence_grade"] = "high"
    with pytest.raises(INVALID):
        validate(rehash(payload))


def test_nested_preview_provenance_cannot_coerce_independent_review_flag(payload):
    first_new(payload)["draft_preview"]["provenance"]["requires_independent_review"] = 1
    with pytest.raises(ValidationError):
        KneeBookReviewPack.model_validate(payload)


def test_nested_preview_version_cannot_coerce_boolean(payload):
    first_new(payload)["draft_preview"]["version"] = True
    with pytest.raises(ValidationError):
        KneeBookReviewPack.model_validate(payload)
