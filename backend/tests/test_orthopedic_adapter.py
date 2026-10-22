"""Synthetic review previews: additive contract, role gates, no clinical writes."""
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.core.config import settings
from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.app.models.clinical_safety import ClinicalSafetyRule
from backend.app.schemas.orthopedic_adapter import OrthopedicDecisionKnowledge
from backend.app.schemas.orthopedic_book_questions import BookQuestionPreview
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext
from backend.app.services.orthopedic_adapter import build_decision_knowledge


BASE_URL = "/api/v1/knowledge/orthopedics/knee"


def test_adapter_inventory_has_traceable_drafts_without_rank_or_probability():
    context = OrthopedicQuestionContext(body_region="knee")
    result = build_decision_knowledge(context)
    assert result == build_decision_knowledge(context)
    assert result.approved_fact_count == 0
    assert result.evidence_references and result.source_references
    keys = {item.fact_key for item in result.evidence_references}
    source_keys = {item.source_key for item in result.source_references}
    for item in result.evidence_references:
        assert not item.usable_as_approved_knowledge
        assert item.approved_content_sha256 is None
        assert set(item.source_keys) <= source_keys
    for item in result.differential_knowledge_references:
        assert item.compatibility == "not_assessed"
        assert item.is_ranked is False
        assert set(item.definition.fact_keys) <= keys
    assert [item.definition.id for item in result.differential_knowledge_references] == sorted(
        item.definition.id for item in result.differential_knowledge_references
    )
    payload = result.model_dump(mode="json")
    assert result.result_sha256 == content_digest({k: v for k, v in payload.items() if k != "result_sha256"})
    def all_keys(value):
        if isinstance(value, dict):
            return set(value).union(*(all_keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(all_keys(v) for v in value))
        return set()
    assert not {"probability", "diagnostic_probability", "rank", "treatment_score"} & all_keys(payload)
    assert result.existing_safety_engine_required and result.safety_evaluation == "not_performed"
    assert not result.is_diagnosis and not result.authorizes_treatment and not result.is_clinical_clearance


@pytest.mark.parametrize("region", ["other", "unknown"])
def test_outside_knee_does_not_supply_knee_differentials(region):
    result = build_decision_knowledge(OrthopedicQuestionContext(body_region=region))
    assert result.differential_knowledge_references == ()
    assert result.evidence_references == ()
    assert result.assessment_requirements == ()
    assert result.review_reasons


def test_api_requires_explicit_enablement_and_authorization(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "ORTHOPEDIC_PREVIEW_ENABLED", False)
    assert client.get(BASE_URL, headers=admin_headers).status_code == 404
    book_request = {"context": {"body_region": "knee"}, "review_scopes": ["arthroplasty_review"]}
    assert client.post(BASE_URL + "/book-preview", headers=admin_headers, json=book_request).status_code == 404
    monkeypatch.setattr(settings, "ORTHOPEDIC_PREVIEW_ENABLED", True)
    assert client.get(BASE_URL).status_code == 401
    assert client.post(BASE_URL + "/book-preview", json=book_request).status_code == 401
    client.headers.update(admin_headers)
    from backend.tests.test_medical_knowledge import create_role_headers
    headers = create_role_headers(client, username="orthopedic_viewer", role="viewer")
    assert client.get(BASE_URL, headers=headers).status_code == 403
    assert client.post(BASE_URL + "/preview", headers=headers, json={"body_region": "knee"}).status_code == 403
    assert client.post(BASE_URL + "/book-preview", headers=headers, json=book_request).status_code == 403


def test_preview_keeps_stores_empty_and_patient_identifiers_rejected(client, admin_headers, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ORTHOPEDIC_PREVIEW_ENABLED", True)
    response = client.get(BASE_URL, headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "draft"
    preview = client.post(BASE_URL + "/preview", headers=admin_headers, json={"body_region": "knee"})
    assert preview.status_code == 200, preview.text
    assert preview.headers["cache-control"] == "no-store"
    assert OrthopedicDecisionKnowledge.model_validate(preview.json()).workflow_state == "preview_only"
    book = client.post(BASE_URL + "/book-preview", headers=admin_headers,
                       json={"context": {"body_region": "knee"}, "review_scopes": ["arthroplasty_review"]})
    assert book.status_code == 200, book.text
    assert book.headers["cache-control"] == "no-store"
    reviewed = BookQuestionPreview.model_validate(book.json())
    assert {item.candidate_key for item in reviewed.source_references} == {"BOOK.KNEE.001", "BOOK.KNEE.002"}
    assert reviewed.approved_fact_count == 0 and reviewed.safety_evaluation == "not_performed"
    assert client.post(BASE_URL + "/preview", headers=admin_headers,
                       json={"body_region": "knee"}).json() == preview.json()
    for model in (MedicalKnowledgeFact, PhysicianQuestionEvent, ClinicalSafetyRule):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
    rejected = client.post(BASE_URL + "/preview", headers=admin_headers,
                           json={"body_region": "knee", "patient_id": "not-allowed"})
    assert rejected.status_code == 422
    rejected_book = client.post(BASE_URL + "/book-preview", headers=admin_headers,
                               json={"context": {"body_region": "knee", "patient_id": "not-allowed"}})
    assert rejected_book.status_code == 422


@pytest.mark.parametrize("name,model", [
    ("orthopedic-decision-knowledge", OrthopedicDecisionKnowledge),
    ("orthopedic-knee-pack", KneeKnowledgePack),
    ("orthopedic-question-context", OrthopedicQuestionContext),
])
def test_checked_in_json_schema_matches_current_contract(name, model):
    path = Path(__file__).resolve().parents[2] / f"docs/contracts/{name}-1.0.0.schema.json"
    assert json.loads(path.read_text()) == model.model_json_schema()
