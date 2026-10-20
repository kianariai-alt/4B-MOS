"""Synthetic-only governance and provenance tests; no clinical validation claim."""
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.models.user import User
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack, content_digest
from backend.app.services.medical_knowledge import (
    MedicalKnowledgeAuthorizationError,
    MedicalKnowledgeConflictError,
    MedicalKnowledgeIntegrityError,
)
from backend.app.services.orthopedic_knowledge import (
    import_knee_drafts,
    load_knee_pack,
    validate_knee_pack,
)


def test_pack_is_draft_sourced_and_separates_guideline_disagreement():
    pack = load_knee_pack()
    assert len(pack.facts) == 27
    assert len(pack.sources) == 16
    assert all(item.status == "draft" for item in pack.facts)
    assert pack.requires_independent_review and not pack.is_clinically_validated
    assert {item.topic for item in pack.facts} >= {"meniscus", "osteoarthritis", "cartilage_osteochondral"}
    prp = next(item for item in pack.treatments if item.treatment_type == "PRP")
    assert set(prp.fact_keys) == {"KNEE.OA.PRP_AAOS", "KNEE.OA.PRP_ACR"}
    assert len(prp.guideline_positions) == 2
    assert all(item.diagnostic_accuracy is None for item in pack.examinations)
    assert {item.treatment_type for item in pack.treatments} >= {"ACS", "PRGF", "PL", "PRP", "HA", "EXOSOME", "SVF", "MSC"}


def test_source_access_and_jurisdiction_limits_are_explicit():
    pack = load_knee_pack()
    acs = pack.get_fact("KNEE.ACS.RESEARCH")
    assert any("abstract" in text.casefold() for text in acs.limitations)
    fda = pack.get_fact("KNEE.REGULATORY.CELL_EXOSOME")
    assert any("United States" in text and "Iran" in text for text in fda.limitations)
    assert pack.get_fact("KNEE.OA.KL_CONTEXT").topic == "osteoarthritis"
    assert all(source.source.url.startswith("https://") for source in pack.sources)
    assert all(source.source.doi or source.source.guideline_version for source in pack.sources)


def test_pack_load_is_deterministic_and_registry_statement_binds_limitations():
    first = load_knee_pack()
    assert first == load_knee_pack()
    fact = first.facts[0]
    suffix = fact.fact.statement.split("\n\nOrthopedic metadata v1:\n")[1]
    assert json.loads(suffix)["limitations"] == list(fact.limitations)
    assert first.manifest_sha256 == content_digest(first.model_dump(mode="json", exclude={"manifest_sha256"}))


def test_fact_content_hash_rejects_tampering_even_with_new_manifest():
    payload = load_knee_pack().model_dump(mode="json")
    payload["facts"][0]["fact"]["title"] = "Tampered clinical title"
    payload["manifest_sha256"] = content_digest({k: v for k, v in payload.items() if k != "manifest_sha256"})
    with pytest.raises(MedicalKnowledgeIntegrityError, match="fact content"):
        validate_knee_pack(KneeKnowledgePack.model_validate(payload))


def test_pack_manifest_rejects_structured_content_tampering():
    payload = load_knee_pack().model_dump(mode="json")
    payload["differentials"][0]["label"] = "Altered differential"
    with pytest.raises(MedicalKnowledgeIntegrityError, match="manifest"):
        validate_knee_pack(KneeKnowledgePack.model_validate(payload))


@pytest.mark.parametrize("mutation", ["draft", "unknown_source", "duplicate_fact", "unknown_fact", "unknown_concept", "unknown_exam", "metadata"])
def test_schema_rejects_invalid_governance_and_references(mutation):
    payload = load_knee_pack().model_dump(mode="json")
    if mutation == "draft":
        payload["facts"][0]["status"] = "approved"
    elif mutation == "unknown_source":
        payload["facts"][0]["source_keys"] = ["missing"]
    elif mutation == "duplicate_fact":
        payload["facts"].append(payload["facts"][0])
    elif mutation == "unknown_fact":
        payload["relations"][0]["fact_keys"] = ["KNEE.MISSING"]
    elif mutation == "unknown_concept":
        payload["relations"][0]["target"]["id"] = "missing_differential"
    elif mutation == "unknown_exam":
        payload["differentials"][0]["examination_ids"] = ["missing_exam"]
    else:
        payload["facts"][0]["limitations"] = ["Altered without rebinding Registry statement"]
    with pytest.raises(ValidationError):
        KneeKnowledgePack.model_validate(payload)


def synthetic_author(db):
    actor = User(username="pack-test-author", display_name="Synthetic Author", password_hash="not-an-authentication-fixture", role="physician", is_active=True)
    db.add(actor)
    db.commit()
    return actor


def test_import_reuses_registry_is_draft_and_rerunnable(db_session):
    actor = synthetic_author(db_session)
    first = import_knee_drafts(db_session, actor=actor)
    second = import_knee_drafts(db_session, actor=actor)
    assert [item.id for item in first] == [item.id for item in second]
    assert all(item.status == "draft" and item.reviewed_by_user_id is None for item in first)
    assert len(list(db_session.scalars(select(MedicalKnowledgeFact)))) == 27
    assert first[0].content_sha256 == load_knee_pack().facts[0].content_sha256


def test_import_checks_authorization_before_any_write(db_session):
    with pytest.raises(MedicalKnowledgeAuthorizationError):
        import_knee_drafts(db_session, actor=None)
    assert list(db_session.scalars(select(MedicalKnowledgeFact))) == []


def test_import_conflict_is_detected_before_new_facts(db_session):
    actor = synthetic_author(db_session)
    rows = import_knee_drafts(db_session, actor=actor)
    changed = db_session.get(MedicalKnowledgeFact, rows[0].id)
    changed.status = "in_review"
    db_session.commit()
    with pytest.raises(MedicalKnowledgeConflictError, match="exact Draft"):
        import_knee_drafts(db_session, actor=actor)
    assert len(list(db_session.scalars(select(MedicalKnowledgeFact)))) == 27
