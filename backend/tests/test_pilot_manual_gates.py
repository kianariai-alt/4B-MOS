from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services import pilot_release as pilot_release_module
from backend.tests.test_treatment_options_roadmap import create_role_headers


pytestmark = pytest.mark.usefixtures("authenticated_admin")

READINESS_SHA = "a" * 64


@pytest.fixture(autouse=True)
def passing_readiness(monkeypatch):
    monkeypatch.setattr(
        pilot_release_module.ControlledPilotReadinessService,
        "build",
        lambda db, config: SimpleNamespace(
            status="automated_prerequisites_passed",
            readiness_sha256=READINESS_SHA,
        ),
    )


def attestation_payload(
    gate_name,
    *,
    release_ref="rc-stage-26",
    supersedes_attestation_id=None,
    expected_supersedes_sha256=None,
):
    return {
        "gate_name": gate_name,
        "expected_readiness_sha256": READINESS_SHA,
        "release_ref": release_ref,
        "evidence_reference": "SYNTHETIC-EVIDENCE-001",
        "statement": (
            "Synthetic controlled-pilot acceptance statement used only by "
            "the automated test suite."
        ),
        "supersedes_attestation_id": supersedes_attestation_id,
        "expected_supersedes_sha256": expected_supersedes_sha256,
    }


def test_clinical_gate_requires_independent_physician_review(
    client,
    db_session,
):
    author = create_role_headers(
        client,
        username="pilot_gate_physician_author",
        role="physician",
    )
    reviewer = create_role_headers(
        client,
        username="pilot_gate_physician_reviewer",
        role="physician",
    )

    created = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        headers=author,
        json=attestation_payload("clinical_protocol_signoff"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["generation"] == 1
    assert body["status"] == "pending_review"
    assert body["review"] is None
    assert body["append_only"] is True
    assert body["independent_review_required"] is True
    assert body["is_clinical_clearance"] is False
    assert body["controlled_pilot_authorized"] is False

    self_review = client.post(
        f"/api/v1/pilot-readiness/manual-gates/attestations/"
        f"{body['id']}/review",
        headers=author,
        json={
            "expected_attestation_sha256": body["sha256"],
            "action": "approve",
            "rationale": (
                "Synthetic self-review attempt must be rejected by the API."
            ),
        },
    )
    assert self_review.status_code == 403

    reviewed = client.post(
        f"/api/v1/pilot-readiness/manual-gates/attestations/"
        f"{body['id']}/review",
        headers=reviewer,
        json={
            "expected_attestation_sha256": body["sha256"],
            "action": "approve",
            "rationale": (
                "Independent synthetic physician review completed for testing."
            ),
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    approved = reviewed.json()
    assert approved["status"] == "approved"
    assert approved["review"]["action"] == "approve"
    assert approved["review"]["reviewed_by_user_id"] != body["attested_by_user_id"]

    duplicate = client.post(
        f"/api/v1/pilot-readiness/manual-gates/attestations/"
        f"{body['id']}/review",
        headers=reviewer,
        json={
            "expected_attestation_sha256": body["sha256"],
            "action": "reject",
            "rationale": (
                "A second immutable review must not be accepted by the system."
            ),
        },
    )
    assert duplicate.status_code == 409

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="pilot_manual_gate_attestation",
        entity_id=body["id"],
    )
    assert [item.event_type for item in logs] == [
        "pilot_manual_gate_attested",
        "pilot_manual_gate_reviewed",
    ]


def test_gate_roles_stale_readiness_and_supersession_are_enforced(
    client,
):
    physician = create_role_headers(
        client,
        username="pilot_gate_role_physician",
        role="physician",
    )
    second_admin = create_role_headers(
        client,
        username="pilot_gate_second_admin",
        role="admin",
    )

    admin_on_clinical = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=attestation_payload("clinical_safety_signoff"),
    )
    assert admin_on_clinical.status_code == 403

    physician_on_operational = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        headers=physician,
        json=attestation_payload("backup_restore"),
    )
    assert physician_on_operational.status_code == 403

    stale = attestation_payload("backup_restore")
    stale["expected_readiness_sha256"] = "0" * 64
    stale_response = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=stale,
    )
    assert stale_response.status_code == 409

    first = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=attestation_payload("backup_restore"),
    )
    assert first.status_code == 201, first.text
    first_body = first.json()

    pending_duplicate = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=attestation_payload(
            "backup_restore",
            supersedes_attestation_id=first_body["id"],
            expected_supersedes_sha256=first_body["sha256"],
        ),
    )
    assert pending_duplicate.status_code == 409

    reviewed = client.post(
        f"/api/v1/pilot-readiness/manual-gates/attestations/"
        f"{first_body['id']}/review",
        headers=second_admin,
        json={
            "expected_attestation_sha256": first_body["sha256"],
            "action": "approve",
            "rationale": (
                "Independent synthetic administrator review completed."
            ),
        },
    )
    assert reviewed.status_code == 200, reviewed.text

    wrong_supersession = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=attestation_payload(
            "backup_restore",
            supersedes_attestation_id=first_body["id"],
            expected_supersedes_sha256="1" * 64,
        ),
    )
    assert wrong_supersession.status_code == 409

    second = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=attestation_payload(
            "backup_restore",
            release_ref="rc-stage-26-v2",
            supersedes_attestation_id=first_body["id"],
            expected_supersedes_sha256=first_body["sha256"],
        ),
    )
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["generation"] == 2
    assert second_body["supersedes_attestation_id"] == first_body["id"]

    statuses = client.get("/api/v1/pilot-readiness/manual-gates")
    assert statuses.status_code == 200, statuses.text
    backup = next(
        item for item in statuses.json()
        if item["gate_name"] == "backup_restore"
    )
    assert backup["status"] == "pending_review"
    assert backup["latest_attestation"]["id"] == second_body["id"]


def test_attestation_tamper_is_detected_on_read(
    client,
    db_session,
):
    second_admin = create_role_headers(
        client,
        username="pilot_gate_tamper_admin",
        role="admin",
    )
    created = client.post(
        "/api/v1/pilot-readiness/manual-gates/attestations",
        json=attestation_payload("monitoring_alerting"),
    )
    assert created.status_code == 201, created.text
    body = created.json()

    db_session.execute(
        text(
            "UPDATE pilot_manual_gate_attestations "
            "SET statement = 'tampered outside governed service' "
            "WHERE id = :attestation_id"
        ),
        {"attestation_id": body["id"]},
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/pilot-readiness/manual-gates/attestations/{body['id']}",
        headers=second_admin,
    )
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"].lower()
