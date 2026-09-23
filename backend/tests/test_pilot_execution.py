"""Synthetic end-to-end controlled-pilot execution acceptance tests."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.services.pilot_readiness import ControlledPilotReadinessService
from backend.tests.test_pilot_release_decision import (
    authorization_payload,
    freeze_launch_package,
)
from backend.tests.test_treatment_decisions import (
    build_reportable_roadmap,
    select_decision_payload,
)
from backend.tests.test_treatment_options_roadmap import create_role_headers


pytestmark = pytest.mark.usefixtures("authenticated_admin")
READINESS_HASH = "b" * 64


@pytest.fixture(autouse=True)
def safe_synthetic_readiness(monkeypatch):
    monkeypatch.setattr(
        ControlledPilotReadinessService,
        "build",
        lambda db, config: SimpleNamespace(
            status="automated_prerequisites_passed",
            readiness_sha256=READINESS_HASH,
        ),
    )


def test_pilot_scope_enrollment_stop_and_acceptance(
    client, monkeypatch, db_session,
):
    physician = create_role_headers(
        client, username="pilot_execution_physician", role="physician",
    )
    protocol, _patient, visit, roadmap = build_reportable_roadmap(
        client, physician,
    )
    decision_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatment-decisions",
        headers=physician,
        json=select_decision_payload(roadmap),
    )
    assert decision_response.status_code == 201, decision_response.text
    decision = decision_response.json()

    package = freeze_launch_package(client)
    independent_admin = create_role_headers(
        client, username="pilot_execution_release_admin", role="admin",
    )
    release_payload = authorization_payload(package, protocol["code"])
    release_payload["max_enrolled_visits"] = 1
    released = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=independent_admin,
        json=release_payload,
    )
    assert released.status_code == 201, released.text
    release = released.json()
    root = f"/api/v1/pilot-execution/releases/{release['id']}"

    initial = client.get(f"{root}/acceptance", headers=physician)
    assert initial.status_code == 200, initial.text
    assert initial.json()["status"] == "no_pilot_data"
    assert initial.json()["authorizes_expansion"] is False

    # Production enforcement rejects the legacy un-enrolled treatment route.
    monkeypatch.setattr(settings, "PILOT_ENFORCEMENT_ENABLED", True)
    blocked = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": decision["id"],
        },
    )
    assert blocked.status_code == 409
    assert "enrolled" in blocked.json()["detail"]

    enrollment_data = {
        "expected_release_decision_sha256": release["sha256"],
        "protocol_template_id": protocol["id"],
        "clinician_decision_id": decision["id"],
        "expected_clinician_decision_sha256": decision["sha256"],
        "consent_evidence_reference": "SYNTHETIC-CONSENT-REF-001",
        "consent_confirmed_at": datetime.now(timezone.utc).isoformat(),
        "clinician_statement": (
            "Synthetic physician confirms that pilot eligibility and "
            "consent-document reference were checked independently."
        ),
    }
    enrollment = client.post(
        f"{root}/visits/{visit['id']}/enroll",
        headers=physician,
        json=enrollment_data,
    )
    assert enrollment.status_code == 201, enrollment.text
    enrolled = enrollment.json()
    assert enrolled["clinician_decision_sha256"] == decision["sha256"]
    assert enrolled["authorizes_individual_treatment"] is False
    assert enrolled["confirms_patient_consent_document_authenticity"] is False

    duplicate = client.post(
        f"{root}/visits/{visit['id']}/enroll",
        headers=physician,
        json=enrollment_data,
    )
    assert duplicate.status_code == 409

    operations = client.get(f"{root}/operations", headers=physician)
    assert operations.status_code == 200, operations.text
    assert operations.json()["enrolled_visits"] == 1
    assert operations.json()["remaining_enrollment_slots"] == 0

    treatment_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol["id"],
            "source_treatment_decision_id": decision["id"],
        },
    )
    assert treatment_response.status_code == 201, treatment_response.text
    treatment = treatment_response.json()

    report = client.get(f"{root}/acceptance", headers=physician)
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "follow_up_incomplete"
    assert report.json()["enrolled_visits"] == 1
    assert report.json()["visits_with_treatment"] == 1
    assert report.json()["visits_with_outcome"] == 0
    assert report.json()["is_effectiveness_conclusion"] is False

    nurse = create_role_headers(
        client, username="pilot_execution_nurse", role="nurse",
    )
    forbidden = client.post(
        f"{root}/stop", headers=nurse,
        json={
            "expected_release_decision_sha256": release["sha256"],
            "reason_category": "clinical_safety",
            "reason": "Synthetic nurse cannot stop a pilot through the privileged endpoint.",
        },
    )
    assert forbidden.status_code == 403

    stopped = client.post(
        f"{root}/stop", headers=physician,
        json={
            "expected_release_decision_sha256": release["sha256"],
            "reason_category": "clinical_safety",
            "reason": (
                "Synthetic safety hold for acceptance testing; no further "
                "pilot treatment should be started."
            ),
        },
    )
    assert stopped.status_code == 201, stopped.text
    assert stopped.json()["restart_requires_new_pilot_release"] is True

    no_new_session = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=physician,
        json={"session_number": 1},
    )
    assert no_new_session.status_code == 409
    assert "stopped" in no_new_session.json()["detail"]

    after_stop = client.get(f"{root}/operations", headers=physician)
    assert after_stop.status_code == 200, after_stop.text
    assert after_stop.json()["status"] == "stopped"
    assert after_stop.json()["new_pilot_activity_allowed"] is False

    report_after_stop = client.get(f"{root}/acceptance", headers=physician)
    assert report_after_stop.status_code == 200, report_after_stop.text
    assert report_after_stop.json()["stop_sha256"] == stopped.json()["sha256"]

    # Direct SQL tampering is detected; ORM update/delete are prohibited.
    db_session.execute(
        text(
            "UPDATE pilot_visit_enrollments SET clinician_statement = "
            "'FORGED' WHERE id = :enrollment_id"
        ),
        {"enrollment_id": enrolled["id"]},
    )
    db_session.commit()
    tampered = client.get(
        f"/api/v1/pilot-execution/visits/{visit['id']}/enrollment",
        headers=physician,
    )
    assert tampered.status_code == 409
    assert "integrity" in tampered.json()["detail"].lower()


def test_pilot_enrollment_rejects_missing_visit_and_holds(client):
    missing = client.get(
        "/api/v1/pilot-execution/releases/missing/operations"
    )
    assert missing.status_code == 404

    from backend.app.schemas.pilot_execution import (
        PilotEnrollmentCreate, PilotStopCreate,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PilotEnrollmentCreate.model_validate({
            "expected_release_decision_sha256": "0" * 64,
            "protocol_template_id": "protocol",
            "clinician_decision_id": "decision",
            "expected_clinician_decision_sha256": "1" * 64,
            "consent_evidence_reference": "SYNTHETIC-REF",
            "consent_confirmed_at": "2026-09-24T10:00:00",
            "clinician_statement": "Synthetic consent requires an offset-aware timestamp.",
        })
    with pytest.raises(ValidationError):
        PilotStopCreate.model_validate({
            "expected_release_decision_sha256": "0" * 64,
            "reason_category": "unsupported",
            "reason": "Synthetic unsupported stop reason category.",
        })
