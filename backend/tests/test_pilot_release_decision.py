from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services import pilot_authorization as pilot_authorization_module
from backend.app.services import pilot_launch as pilot_launch_module
from backend.app.services import pilot_release as pilot_release_module
from backend.tests.test_pilot_launch_package import (
    READINESS_SHA,
    RELEASE_REF,
    create_and_approve_all_gates,
)
from backend.tests.test_treatment_options_roadmap import create_role_headers


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


def freeze_launch_package(client):
    create_and_approve_all_gates(client)
    preview = client.get(
        "/api/v1/pilot-readiness/manual-gates/launch-package-preview"
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "packageable"

    frozen = client.post(
        "/api/v1/pilot-readiness/manual-gates/launch-packages",
        json={
            "expected_readiness_sha256": body["readiness_sha256"],
            "expected_release_ref": body["release_ref"],
            "expected_attestations": [
                {
                    "gate_name": item["gate_name"],
                    "attestation_sha256": item["attestation_sha256"],
                }
                for item in body["attestation_manifest"]
            ],
        },
    )
    assert frozen.status_code == 201, frozen.text
    return frozen.json()


def create_active_protocol(client, *, code="PILOT-RELEASE-ACS"):
    response = client.post(
        "/api/v1/protocols",
        json={
            "code": code,
            "name": "Synthetic Pilot Release Protocol",
            "treatment_type": "ACS",
            "version": "1.0",
            "description": "Synthetic protocol for release-decision testing.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorization_payload(package, protocol_code):
    now = datetime.now(timezone.utc)
    return {
        "expected_package_sha256": package["sha256"],
        "action": "authorize",
        "rationale": (
            "Independent human release decision for the synthetic controlled "
            "pilot acceptance scenario."
        ),
        "starts_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "max_enrolled_visits": 12,
        "allowed_protocol_codes": [protocol_code],
    }


def test_independent_admin_can_authorize_exact_launch_package(
    client,
    db_session,
):
    protocol = create_active_protocol(client)
    package = freeze_launch_package(client)

    same_admin = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        json=authorization_payload(package, protocol["code"]),
    )
    assert same_admin.status_code == 403
    assert "author" in same_admin.json()["detail"].lower()

    release_admin = create_role_headers(
        client,
        username="pilot_release_independent_admin",
        role="admin",
    )
    authorized = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=release_admin,
        json=authorization_payload(package, protocol["code"]),
    )
    assert authorized.status_code == 201, authorized.text
    decision = authorized.json()

    assert decision["package_id"] == package["id"]
    assert decision["package_sha256"] == package["sha256"]
    assert decision["action"] == "authorize"
    assert decision["max_enrolled_visits"] == 12
    assert decision["allowed_protocol_codes"] == [protocol["code"]]
    assert decision["append_only"] is True
    assert decision["controlled_pilot_release_authorized"] is True
    assert decision["authorizes_individual_treatment"] is False
    assert decision["is_clinical_clearance"] is False
    assert decision["individual_clinician_decision_required"] is True

    by_package = client.get(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decision",
        headers=release_admin,
    )
    assert by_package.status_code == 200
    assert by_package.json()["id"] == decision["id"]

    history = client.get(
        "/api/v1/pilot-readiness/manual-gates/release-decisions",
        headers=release_admin,
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [decision["id"]]

    duplicate = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=release_admin,
        json=authorization_payload(package, protocol["code"]),
    )
    assert duplicate.status_code == 409

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="pilot_release_decision",
        entity_id=decision["id"],
    )
    assert [item.event_type for item in logs] == [
        "pilot_release_decision_recorded"
    ]


def test_authorization_rejects_inactive_or_unknown_protocol_scope(client):
    package = freeze_launch_package(client)
    release_admin = create_role_headers(
        client,
        username="pilot_release_scope_admin",
        role="admin",
    )

    response = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=release_admin,
        json=authorization_payload(package, "NOT-ACTIVE"),
    )
    assert response.status_code == 409
    assert "not currently active" in response.json()["detail"]


def test_hold_decision_has_no_active_scope(client):
    package = freeze_launch_package(client)
    release_admin = create_role_headers(
        client,
        username="pilot_release_hold_admin",
        role="admin",
    )

    held = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=release_admin,
        json={
            "expected_package_sha256": package["sha256"],
            "action": "hold",
            "rationale": (
                "Synthetic human release hold while external readiness remains "
                "under review."
            ),
            "allowed_protocol_codes": [],
        },
    )
    assert held.status_code == 201, held.text
    decision = held.json()
    assert decision["action"] == "hold"
    assert decision["controlled_pilot_release_authorized"] is False
    assert decision["starts_at"] is None
    assert decision["expires_at"] is None
    assert decision["max_enrolled_visits"] is None
    assert decision["allowed_protocol_codes"] == []


def test_release_decision_tamper_is_detected(client, db_session):
    protocol = create_active_protocol(client, code="PILOT-TAMPER-ACS")
    package = freeze_launch_package(client)
    release_admin = create_role_headers(
        client,
        username="pilot_release_tamper_admin",
        role="admin",
    )
    authorized = client.post(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/"
        f"{package['id']}/release-decisions",
        headers=release_admin,
        json=authorization_payload(package, protocol["code"]),
    )
    assert authorized.status_code == 201, authorized.text
    decision = authorized.json()

    db_session.execute(
        text(
            "UPDATE pilot_release_decisions "
            "SET action = 'hold' WHERE id = :decision_id"
        ),
        {"decision_id": decision["id"]},
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/pilot-readiness/manual-gates/release-decisions/"
        f"{decision['id']}",
        headers=release_admin,
    )
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"].lower()
