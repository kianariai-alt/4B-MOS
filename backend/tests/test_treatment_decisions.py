from copy import deepcopy

import pytest
from sqlalchemy import update

from backend.app.models.treatment_decision import TreatmentDecision
from backend.app.services.session_finalization import evidence_digest
from backend.tests.test_treatment_options_roadmap import (
    create_historical_case,
    create_protocol,
    create_role_headers,
    create_target_case,
    record_outcome,
    run_safety,
)


pytestmark = pytest.mark.usefixtures("authenticated_admin")


@pytest.fixture
def physician_headers(client):
    return create_role_headers(
        client,
        username="decision_physician",
        role="physician",
    )


@pytest.fixture
def nurse_headers(client):
    return create_role_headers(
        client,
        username="decision_nurse",
        role="nurse",
    )


def build_reportable_roadmap(client, physician_headers):
    protocol = create_protocol(
        client,
        physician_headers,
        code="DECISION-ACS",
    )
    target_patient, target_visit, _target_intake = create_target_case(
        client,
        physician_headers,
    )
    for index in range(5):
        create_historical_case(
            client,
            physician_headers,
            protocol["id"],
            index=200 + index,
        )
    run_safety(
        client,
        target_visit["id"],
        physician_headers,
    )
    roadmap = client.get(
        f"/api/v1/visits/{target_visit['id']}/treatment-options-roadmap",
        headers=physician_headers,
    )
    assert roadmap.status_code == 200, roadmap.text
    roadmap = roadmap.json()
    assert roadmap["roadmap_status"] == "options_available"
    return protocol, target_patient, target_visit, roadmap


def select_decision_payload(
    roadmap: dict,
    *,
    previous_sha256: str | None = None,
) -> dict:
    option = roadmap["options"][0]
    return {
        "expected_clinical_context_sha256": (
            roadmap["target_profile"]["clinical_context_sha256"]
        ),
        "expected_roadmap_sha256": roadmap["roadmap_sha256"],
        "expected_previous_decision_sha256": previous_sha256,
        "decision_type": "select_option",
        "selected_protocols": [
            {
                "protocol_code": option["protocol_code"],
                "protocol_version": option["protocol_version"],
                "treatment_type": option["treatment_type"],
                "source": "roadmap_option",
            }
        ],
        "rationale": (
            "Synthetic physician rationale after independent review of the "
            "patient context, local cohort and treatment alternatives."
        ),
        "patient_preference_summary": (
            "Synthetic patient preference was discussed and documented."
        ),
        "evidence_brief_ids": [],
    }


def complete_linked_treatment(
    client,
    headers,
    *,
    visit_id: str,
    protocol_id: str,
    decision_id: str,
) -> dict:
    response = client.post(
        f"/api/v1/visits/{visit_id}/treatments",
        headers=headers,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol_id,
            "source_treatment_decision_id": decision_id,
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert response.status_code == 201, response.text
    treatment = response.json()

    session = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=headers,
        json={
            "session_number": 1,
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]
    for state in ("checked_in", "ready", "in_treatment", "completed"):
        changed = client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=headers,
            json={"operational_status": state},
        )
        assert changed.status_code == 200, changed.text
    finalization = client.get(
        f"/api/v1/treatment-sessions/{session_id}/finalization",
        headers=headers,
    )
    assert finalization.status_code == 200, finalization.text
    return treatment


def test_decision_closes_loop_from_roadmap_to_outcome(
    client,
    physician_headers,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        physician_headers,
    )

    created = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=select_decision_payload(roadmap),
    )
    assert created.status_code == 201, created.text
    decision = created.json()

    assert decision["decision_type"] == "select_option"
    assert decision["is_current_decision"] is True
    assert decision["is_system_selected"] is False
    assert decision["is_prescription_generated_by_system"] is False
    assert decision["linked_treatment_ids"] == []
    assert decision["linked_outcome_ids"] == []
    assert evidence_digest(decision["payload"]) == decision["sha256"]
    assert decision["payload"]["roadmap_sha256"] == roadmap["roadmap_sha256"]
    assert decision["payload"]["decision_is_physician_authored"] is True

    treatment = complete_linked_treatment(
        client,
        physician_headers,
        visit_id=visit["id"],
        protocol_id=protocol["id"],
        decision_id=decision["id"],
    )
    assert treatment["source_treatment_decision_id"] == decision["id"]
    assert treatment["source_treatment_decision_sha256"] == decision["sha256"]

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

    refreshed = client.get(
        f"/api/v1/treatment-decisions/{decision['id']}",
        headers=physician_headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    refreshed = refreshed.json()
    assert refreshed["linked_treatment_ids"] == [treatment["id"]]
    assert refreshed["linked_outcome_ids"] == [outcome["id"]]

    treatment_read = client.get(
        f"/api/v1/treatments/{treatment['id']}",
        headers=physician_headers,
    )
    assert treatment_read.status_code == 200
    assert (
        treatment_read.json()["source_treatment_decision_sha256"]
        == decision["sha256"]
    )


def test_superseding_decision_is_append_only_and_blocks_old_execution(
    client,
    physician_headers,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        physician_headers,
    )
    first = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=select_decision_payload(roadmap),
    )
    assert first.status_code == 201, first.text
    first = first.json()

    deferred_payload = {
        "expected_clinical_context_sha256": (
            roadmap["target_profile"]["clinical_context_sha256"]
        ),
        "expected_roadmap_sha256": roadmap["roadmap_sha256"],
        "expected_previous_decision_sha256": first["sha256"],
        "decision_type": "defer",
        "selected_protocols": [],
        "rationale": (
            "Synthetic physician decision to defer treatment after reviewing "
            "the current clinical context and discussing uncertainty."
        ),
        "patient_preference_summary": (
            "Synthetic patient preference favored additional observation."
        ),
        "evidence_brief_ids": [],
    }
    second = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=deferred_payload,
    )
    assert second.status_code == 201, second.text
    second = second.json()
    assert second["supersedes_decision_id"] == first["id"]
    assert second["payload"]["supersedes_decision_sha256"] == first["sha256"]
    assert second["is_current_decision"] is True

    history = client.get(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
    )
    assert history.status_code == 200
    history = history.json()
    assert [item["id"] for item in history] == [first["id"], second["id"]]
    assert history[0]["is_current_decision"] is False
    assert history[1]["is_current_decision"] is True

    old_link = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician_headers,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": first["id"],
        },
    )
    assert old_link.status_code == 409
    assert "superseded" in old_link.json()["detail"]

    deferred_link = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician_headers,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": second["id"],
        },
    )
    assert deferred_link.status_code == 409
    assert "does not authorize" in deferred_link.json()["detail"]


def test_decision_rejects_stale_roadmap_and_non_option_protocol(
    client,
    physician_headers,
):
    _protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        physician_headers,
    )
    stale = select_decision_payload(roadmap)
    stale["expected_roadmap_sha256"] = "0" * 64
    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=stale,
    )
    assert response.status_code == 409
    assert "roadmap changed" in response.json()["detail"]

    bad = select_decision_payload(roadmap)
    bad["selected_protocols"][0]["protocol_code"] = "NOT-IN-ROADMAP"
    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=bad,
    )
    assert response.status_code == 409
    assert "no longer present" in response.json()["detail"]


def test_decision_role_boundaries_and_orm_immutability(
    client,
    physician_headers,
    nurse_headers,
    db_session,
):
    _protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        physician_headers,
    )
    payload = select_decision_payload(roadmap)

    assert client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=nurse_headers,
        json=payload,
    ).status_code == 403

    created = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician_headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    decision = created.json()

    assert client.get(
        f"/api/v1/treatment-decisions/{decision['id']}",
        headers=nurse_headers,
    ).status_code == 200

    record = db_session.get(TreatmentDecision, decision["id"])
    record.rationale = "This rewrite must fail."
    with pytest.raises(ValueError, match="cannot be updated"):
        db_session.commit()
    db_session.rollback()

    tampered = deepcopy(record.payload)
    tampered["decision_type"] = "no_treatment"
    db_session.execute(
        update(TreatmentDecision)
        .where(TreatmentDecision.id == decision["id"])
        .values(payload=tampered)
    )
    db_session.commit()
    response = client.get(
        f"/api/v1/treatment-decisions/{decision['id']}",
        headers=physician_headers,
    )
    assert response.status_code == 409
    assert "integrity check" in response.json()["detail"]
