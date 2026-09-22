import pytest
from sqlalchemy import update

from backend.app.models.treatment import Treatment
from backend.tests.test_treatment_decisions import (
    build_reportable_roadmap,
    complete_linked_treatment,
    select_decision_payload,
)
from backend.tests.test_treatment_options_roadmap import (
    create_role_headers,
    record_outcome,
)


pytestmark = pytest.mark.usefixtures("authenticated_admin")


@pytest.fixture
def physician_headers(client):
    return create_role_headers(
        client,
        username="learning_physician",
        role="physician",
    )


@pytest.fixture
def nurse_headers(client):
    return create_role_headers(
        client,
        username="learning_nurse",
        role="nurse",
    )


def test_empty_learning_review_is_unranked_and_traceable(client):
    response = client.get("/api/v1/learning/review")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["data_quality"]["decision_event_count"] == 0
    assert body["data_quality"]["current_decision_count"] == 0
    assert body["data_quality"]["decision_linked_treatment_count"] == 0
    assert body["data_quality"]["legacy_or_unlinked_treatment_count"] == 0
    assert body["data_quality"]["outcome_record_count"] == 0
    assert body["protocols"] == []
    assert body["source_decision_count"] == 0
    assert body["source_outcome_count"] == 0
    assert len(body["source_manifest_sha256"]) == 64
    assert len(body["review_sha256"]) == 64
    assert body["protocol_ordering"] == "protocol_code_then_version"
    assert body["local_data_are_observational"] is True
    assert body["is_cross_protocol_effectiveness_comparison"] is False
    assert body["ranks_treatments"] is False
    assert body["produces_learning_score"] is False
    assert body["automatically_changes_protocols"] is False

    repeated = client.get("/api/v1/learning/review")
    assert repeated.status_code == 200
    assert repeated.json()["review_sha256"] == body["review_sha256"]
    assert (
        repeated.json()["source_manifest_sha256"]
        == body["source_manifest_sha256"]
    )


def test_learning_review_tracks_decision_treatment_outcome_coverage(
    client,
    physician_headers,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        physician_headers,
    )
    decision_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=select_decision_payload(roadmap),
    )
    assert decision_response.status_code == 201, decision_response.text
    decision = decision_response.json()

    treatment = complete_linked_treatment(
        client,
        physician_headers,
        visit_id=visit["id"],
        protocol_id=protocol["id"],
        decision_id=decision["id"],
    )
    outcome = record_outcome(
        client,
        physician_headers,
        visit_id=visit["id"],
        treatment_id=treatment["id"],
        patient_rating=5,
        physician_rating=4,
        follow_up_pain=2,
        outcome_status="improved",
    )

    response = client.get(
        "/api/v1/learning/review",
        headers=physician_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    quality = body["data_quality"]

    assert quality["decision_event_count"] == 1
    assert quality["current_decision_count"] == 1
    assert quality["current_actionable_decision_count"] == 1
    assert quality["decision_linked_treatment_count"] == 1
    assert quality["legacy_or_unlinked_treatment_count"] == 5
    assert quality["treatment_with_outcome_count"] == 6
    assert quality["outcome_record_count"] == 6
    assert quality["patient_rating_coverage"] == {
        "present_count": 6,
        "total_count": 6,
        "proportion": 1.0,
    }
    assert quality["physician_rating_coverage"]["proportion"] == 1.0
    assert quality["pain_score_coverage"]["proportion"] == 1.0
    assert quality["function_score_coverage"]["proportion"] == 1.0

    assert len(body["protocols"]) == 1
    review = body["protocols"][0]
    assert review["protocol_code"] == "DECISION-ACS"
    assert review["protocol_version"] == "1.0"
    assert review["is_active"] is True
    assert review["decision_event_reference_count"] == 1
    assert review["current_decision_reference_count"] == 1
    assert review["treatment_count"] == 6
    assert review["decision_linked_treatment_count"] == 1
    assert review["treatment_with_outcome_count"] == 6
    assert review["outcome_record_count"] == 6
    assert review["follow_up_counts"] == {
        "early_28_to_70_days": 0,
        "intermediate_71_to_180_days": 6,
        "long_term_181_to_365_days": 0,
        "outside_standard_windows": 0,
    }
    assert review["data_volume"] == "very_limited"
    assert review["patient_rating_coverage"]["proportion"] == 1.0
    assert review["physician_rating_coverage"]["proportion"] == 1.0
    assert review["pain_score_coverage"]["proportion"] == 1.0
    assert review["function_score_coverage"]["proportion"] == 1.0
    assert review["data_quality_flags"] == []
    assert review["is_performance_score"] is False
    assert review["is_treatment_ranking"] is False

    refreshed_decision = client.get(
        f"/api/v1/treatment-decisions/{decision['id']}",
        headers=physician_headers,
    )
    assert refreshed_decision.status_code == 200
    assert refreshed_decision.json()["linked_outcome_ids"] == [outcome["id"]]


def test_learning_review_detects_broken_decision_provenance(
    client,
    physician_headers,
    db_session,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        physician_headers,
    )
    decision_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=select_decision_payload(roadmap),
    )
    assert decision_response.status_code == 201, decision_response.text
    decision = decision_response.json()

    treatment = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician_headers,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": decision["id"],
            "body_region": "Knee",
        },
    )
    assert treatment.status_code == 201, treatment.text

    db_session.execute(
        update(Treatment)
        .where(Treatment.id == treatment.json()["id"])
        .values(source_treatment_decision_sha256="0" * 64)
    )
    db_session.commit()

    response = client.get(
        "/api/v1/learning/review",
        headers=physician_headers,
    )
    assert response.status_code == 409
    assert "decision hash" in response.json()["detail"]


def test_learning_review_is_admin_physician_only(
    client,
    physician_headers,
    nurse_headers,
):
    assert client.get(
        "/api/v1/learning/review",
        headers=physician_headers,
    ).status_code == 200
    assert client.get(
        "/api/v1/learning/review",
        headers=nurse_headers,
    ).status_code == 403
