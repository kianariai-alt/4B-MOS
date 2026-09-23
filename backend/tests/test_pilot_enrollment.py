from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services import pilot_authorization as pilot_authorization_module
from backend.app.services import pilot_launch as pilot_launch_module
from backend.app.services import pilot_release as pilot_release_module
from backend.tests.test_pilot_release_decision import (
    READINESS_SHA,
    authorization_payload,
    freeze_launch_package,
)
from backend.tests.test_treatment_decisions import (
    build_reportable_roadmap,
    select_decision_payload,
)
from backend.tests.test_treatment_options_roadmap import (
    context_hash,
    create_patient,
    create_role_headers,
    create_visit,
    final_intake,
    run_safety,
)


pytestmark = pytest.mark.usefixtures("authenticated_admin")


@pytest.fixture(autouse=True)
def passing_readiness(monkeypatch):
    snapshot = SimpleNamespace(
        status="automated_prerequisites_passed",
        readiness_sha256=READINESS_SHA,
    )
    for module in (
        pilot_release_module,
        pilot_launch_module,
        pilot_authorization_module,
    ):
        monkeypatch.setattr(
            module.ControlledPilotReadinessService,
            "build",
            lambda db, config: snapshot,
        )


@pytest.fixture
def pilot_physician_headers(client):
    return create_role_headers(
        client,
        username="pilot_enrollment_physician",
        role="physician",
    )


def authorize_release(
    client,
    *,
    package,
    protocol_code,
    max_visits=12,
    username="pilot_enrollment_release_admin",
):
    headers = create_role_headers(
        client,
        username=username,
        role="admin",
    )
    payload = authorization_payload(package, protocol_code)
    payload["max_enrolled_visits"] = max_visits
    response = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json(), headers


def enroll(
    client,
    headers,
    *,
    visit_id,
    decision,
    protocol_id,
    context_sha256,
    supersedes=None,
):
    payload = {
        "release_decision_id": decision["id"],
        "expected_release_decision_sha256": decision["sha256"],
        "expected_clinical_context_sha256": context_sha256,
        "protocol_template_id": protocol_id,
        "rationale": (
            "Synthetic physician-controlled pilot enrollment after reviewing "
            "the current context and bounded release scope."
        ),
        "supersedes_enrollment_id": (
            supersedes["id"] if supersedes else None
        ),
        "expected_supersedes_sha256": (
            supersedes["sha256"] if supersedes else None
        ),
    }
    return client.post(
        f"/api/v1/visits/{visit_id}/pilot-enrollments",
        headers=headers,
        json=payload,
    )


def test_pilot_enrollment_controls_treatment_and_session_start(
    client,
    pilot_physician_headers,
    db_session,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        pilot_physician_headers,
    )
    package = freeze_launch_package(client)
    release, _release_headers = authorize_release(
        client,
        package=package,
        protocol_code=protocol["code"],
    )

    enrolled = enroll(
        client,
        pilot_physician_headers,
        visit_id=visit["id"],
        decision=release,
        protocol_id=protocol["id"],
        context_sha256=roadmap["target_profile"]["clinical_context_sha256"],
    )
    assert enrolled.status_code == 201, enrolled.text
    enrollment = enrolled.json()
    assert enrollment["generation"] == 1
    assert enrollment["protocol_template_id"] == protocol["id"]
    assert enrollment["release_decision_id"] == release["id"]
    assert enrollment["pilot_enrollment"] is True
    assert enrollment["authorizes_individual_treatment"] is False
    assert enrollment["requires_clinician_treatment_decision"] is True
    assert enrollment["is_clinical_clearance"] is False

    no_decision = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=pilot_physician_headers,
        json={
            "treatment_type": protocol["treatment_type"],
            "protocol_template_id": protocol["id"],
            "body_region": "Knee",
        },
    )
    assert no_decision.status_code == 409
    assert "clinician treatment decision" in no_decision.json()["detail"]

    created_decision = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=pilot_physician_headers,
        json=select_decision_payload(roadmap),
    )
    assert created_decision.status_code == 201, created_decision.text
    clinician_decision = created_decision.json()

    treatment = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=pilot_physician_headers,
        json={
            "treatment_type": protocol["treatment_type"],
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": clinician_decision["id"],
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert treatment.status_code == 201, treatment.text
    treatment = treatment.json()

    session = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=pilot_physician_headers,
        json={
            "session_number": 1,
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    for state in ("checked_in", "ready", "in_treatment"):
        changed = client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=pilot_physician_headers,
            json={"operational_status": state},
        )
        assert changed.status_code == 200, changed.text

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="pilot_visit_enrollment",
        entity_id=enrollment["id"],
    )
    assert [item.event_type for item in logs] == ["pilot_visit_enrolled"]


def test_pilot_enrollment_cap_cannot_be_exceeded(
    client,
    pilot_physician_headers,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        pilot_physician_headers,
    )
    package = freeze_launch_package(client)
    release, _headers = authorize_release(
        client,
        package=package,
        protocol_code=protocol["code"],
        max_visits=1,
        username="pilot_cap_release_admin",
    )
    first = enroll(
        client,
        pilot_physician_headers,
        visit_id=visit["id"],
        decision=release,
        protocol_id=protocol["id"],
        context_sha256=roadmap["target_profile"]["clinical_context_sha256"],
    )
    assert first.status_code == 201, first.text

    patient2 = create_patient(client, code="PILOT-CAP-SECOND")
    visit2 = create_visit(
        client,
        patient2["id"],
        complaint="Synthetic second pilot-cap visit",
    )
    final_intake(
        client,
        visit2["id"],
        pilot_physician_headers,
        pain_score=6,
    )
    safety2 = run_safety(
        client,
        visit2["id"],
        pilot_physician_headers,
    )
    second = enroll(
        client,
        pilot_physician_headers,
        visit_id=visit2["id"],
        decision=release,
        protocol_id=protocol["id"],
        context_sha256=safety2["clinical_context_sha256"],
    )
    assert second.status_code == 409
    assert "cap has been reached" in second.json()["detail"]


def test_session_start_rechecks_exact_enrolled_protocol(
    client,
    pilot_physician_headers,
    db_session,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        pilot_physician_headers,
    )
    package = freeze_launch_package(client)
    release, _headers = authorize_release(
        client,
        package=package,
        protocol_code=protocol["code"],
        username="pilot_runtime_release_admin",
    )
    enrolled = enroll(
        client,
        pilot_physician_headers,
        visit_id=visit["id"],
        decision=release,
        protocol_id=protocol["id"],
        context_sha256=roadmap["target_profile"]["clinical_context_sha256"],
    )
    assert enrolled.status_code == 201, enrolled.text

    decision = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=pilot_physician_headers,
        json=select_decision_payload(roadmap),
    )
    assert decision.status_code == 201, decision.text
    treatment = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=pilot_physician_headers,
        json={
            "treatment_type": protocol["treatment_type"],
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": decision.json()["id"],
        },
    )
    assert treatment.status_code == 201, treatment.text
    session = client.post(
        f"/api/v1/treatments/{treatment.json()['id']}/sessions",
        headers=pilot_physician_headers,
        json={"session_number": 1},
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    for state in ("checked_in", "ready"):
        assert client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=pilot_physician_headers,
            json={"operational_status": state},
        ).status_code == 200

    db_session.execute(
        text(
            "UPDATE protocol_templates SET is_active = 0 "
            "WHERE id = :protocol_id"
        ),
        {"protocol_id": protocol["id"]},
    )
    db_session.commit()

    start = client.patch(
        f"/api/v1/treatment-sessions/{session_id}/workflow",
        headers=pilot_physician_headers,
        json={"operational_status": "in_treatment"},
    )
    assert start.status_code == 409
    assert "no longer valid" in start.json()["detail"]


def test_pilot_enrollment_tamper_is_detected(
    client,
    pilot_physician_headers,
    db_session,
):
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client,
        pilot_physician_headers,
    )
    package = freeze_launch_package(client)
    release, _headers = authorize_release(
        client,
        package=package,
        protocol_code=protocol["code"],
        username="pilot_tamper_release_admin",
    )
    enrolled = enroll(
        client,
        pilot_physician_headers,
        visit_id=visit["id"],
        decision=release,
        protocol_id=protocol["id"],
        context_sha256=roadmap["target_profile"]["clinical_context_sha256"],
    )
    assert enrolled.status_code == 201, enrolled.text
    enrollment = enrolled.json()

    db_session.execute(
        text(
            "UPDATE pilot_visit_enrollments "
            "SET protocol_version = 'tampered' WHERE id = :id"
        ),
        {"id": enrollment["id"]},
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/visits/{visit['id']}/pilot-enrollment",
        headers=pilot_physician_headers,
    )
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"].lower()
