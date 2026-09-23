from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services import pilot_launch as pilot_launch_module
from backend.app.services import pilot_release as pilot_release_module
from backend.tests.test_treatment_options_roadmap import create_role_headers


pytestmark = pytest.mark.usefixtures("authenticated_admin")

READINESS_SHA = "b" * 64
RELEASE_REF = "rc-stage-27"

CLINICAL_GATES = (
    "clinical_protocol_signoff",
    "clinical_safety_signoff",
)
OPERATIONAL_GATES = (
    "backup_restore",
    "security_perimeter",
    "monitoring_alerting",
    "human_ui_acceptance",
    "privacy_retention_legal",
)


@pytest.fixture(autouse=True)
def passing_readiness(monkeypatch):
    snapshot = SimpleNamespace(
        status="automated_prerequisites_passed",
        readiness_sha256=READINESS_SHA,
    )
    monkeypatch.setattr(
        pilot_release_module.ControlledPilotReadinessService,
        "build",
        lambda db, config: snapshot,
    )
    monkeypatch.setattr(
        pilot_launch_module.ControlledPilotReadinessService,
        "build",
        lambda db, config: snapshot,
    )


def gate_payload(gate_name, *, release_ref=RELEASE_REF):
    return {
        "gate_name": gate_name,
        "expected_readiness_sha256": READINESS_SHA,
        "release_ref": release_ref,
        "evidence_reference": f"SYNTHETIC-{gate_name}",
        "statement": (
            "Synthetic manual gate evidence created only for launch package "
            "integration testing."
        ),
        "supersedes_attestation_id": None,
        "expected_supersedes_sha256": None,
    }


def create_and_approve_all_gates(client, *, mismatched_gate=None):
    physician_author = create_role_headers(
        client,
        username="launch_physician_author",
        role="physician",
    )
    physician_reviewer = create_role_headers(
        client,
        username="launch_physician_reviewer",
        role="physician",
    )
    admin_reviewer = create_role_headers(
        client,
        username="launch_admin_reviewer",
        role="admin",
    )

    created = {}
    for gate_name in CLINICAL_GATES + OPERATIONAL_GATES:
        release_ref = (
            "different-release"
            if gate_name == mismatched_gate
            else RELEASE_REF
        )
        author_headers = (
            physician_author
            if gate_name in CLINICAL_GATES
            else None
        )
        response = client.post(
            "/api/v1/pilot-readiness/manual-gates/attestations",
            headers=author_headers,
            json=gate_payload(gate_name, release_ref=release_ref),
        )
        assert response.status_code == 201, response.text
        attestation = response.json()
        created[gate_name] = attestation

        reviewer_headers = (
            physician_reviewer
            if gate_name in CLINICAL_GATES
            else admin_reviewer
        )
        review = client.post(
            f"/api/v1/pilot-readiness/manual-gates/attestations/"
            f"{attestation['id']}/review",
            headers=reviewer_headers,
            json={
                "expected_attestation_sha256": attestation["sha256"],
                "action": "approve",
                "rationale": (
                    "Independent synthetic review for launch package testing."
                ),
            },
        )
        assert review.status_code == 200, review.text
        assert review.json()["status"] == "approved"

    return created, physician_author


def test_launch_preview_blocks_until_all_manual_gates_are_approved(client):
    preview = client.get("/api/v1/pilot-readiness/manual-gates/launch-package-preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "blocked"
    assert body["approved_gate_count"] == 0
    assert body["required_gate_count"] == 7
    assert "manual_gate_manifest_incomplete" in body["issues"]
    assert body["controlled_pilot_authorized"] is False
    assert body["is_clinical_clearance"] is False


def test_launch_package_requires_one_release_ref_and_freezes_exact_manifest(
    client,
    db_session,
):
    created, physician_headers = create_and_approve_all_gates(client)

    preview_response = client.get(
        "/api/v1/pilot-readiness/manual-gates/launch-package-preview"
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["status"] == "packageable"
    assert preview["release_ref"] == RELEASE_REF
    assert preview["readiness_sha256"] == READINESS_SHA
    assert preview["approved_gate_count"] == 7
    assert len(preview["attestation_manifest"]) == 7
    assert preview["issues"] == []

    physician_attempt = client.post(
        "/api/v1/pilot-readiness/manual-gates/launch-packages",
        headers=physician_headers,
        json={
            "expected_readiness_sha256": READINESS_SHA,
            "expected_release_ref": RELEASE_REF,
            "expected_attestations": [
                {
                    "gate_name": item["gate_name"],
                    "attestation_sha256": item["attestation_sha256"],
                }
                for item in preview["attestation_manifest"]
            ],
        },
    )
    assert physician_attempt.status_code == 403

    stale = client.post(
        "/api/v1/pilot-readiness/manual-gates/launch-packages",
        json={
            "expected_readiness_sha256": "0" * 64,
            "expected_release_ref": RELEASE_REF,
            "expected_attestations": [
                {
                    "gate_name": item["gate_name"],
                    "attestation_sha256": item["attestation_sha256"],
                }
                for item in preview["attestation_manifest"]
            ],
        },
    )
    assert stale.status_code == 409

    frozen = client.post(
        "/api/v1/pilot-readiness/manual-gates/launch-packages",
        json={
            "expected_readiness_sha256": preview["readiness_sha256"],
            "expected_release_ref": preview["release_ref"],
            "expected_attestations": [
                {
                    "gate_name": item["gate_name"],
                    "attestation_sha256": item["attestation_sha256"],
                }
                for item in preview["attestation_manifest"]
            ],
        },
    )
    assert frozen.status_code == 201, frozen.text
    package = frozen.json()
    assert package["release_ref"] == RELEASE_REF
    assert package["readiness_sha256"] == READINESS_SHA
    assert len(package["attestation_manifest"]) == 7
    assert package["append_only"] is True
    assert package["controlled_pilot_authorized"] is False
    assert package["is_clinical_clearance"] is False
    assert package["requires_human_release_decision"] is True

    expected_hashes = {
        gate: record["sha256"] for gate, record in created.items()
    }
    assert {
        item["gate_name"]: item["attestation_sha256"]
        for item in package["attestation_manifest"]
    } == expected_hashes

    duplicate = client.post(
        "/api/v1/pilot-readiness/manual-gates/launch-packages",
        json={
            "expected_readiness_sha256": preview["readiness_sha256"],
            "expected_release_ref": preview["release_ref"],
            "expected_attestations": [
                {
                    "gate_name": item["gate_name"],
                    "attestation_sha256": item["attestation_sha256"],
                }
                for item in preview["attestation_manifest"]
            ],
        },
    )
    assert duplicate.status_code == 409

    history = client.get(
        "/api/v1/pilot-readiness/manual-gates/launch-packages"
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [package["id"]]

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="pilot_launch_package",
        entity_id=package["id"],
    )
    assert [item.event_type for item in logs] == [
        "pilot_launch_package_frozen",
    ]


def test_launch_preview_blocks_mixed_release_references(client):
    create_and_approve_all_gates(
        client,
        mismatched_gate="privacy_retention_legal",
    )

    preview = client.get(
        "/api/v1/pilot-readiness/manual-gates/launch-package-preview"
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["status"] == "blocked"
    assert body["release_ref"] is None
    assert "manual_gate_release_ref_mismatch" in body["issues"]


def test_launch_package_tamper_is_detected(client, db_session):
    create_and_approve_all_gates(client)
    preview = client.get(
        "/api/v1/pilot-readiness/manual-gates/launch-package-preview"
    ).json()
    frozen = client.post(
        "/api/v1/pilot-readiness/manual-gates/launch-packages",
        json={
            "expected_readiness_sha256": preview["readiness_sha256"],
            "expected_release_ref": preview["release_ref"],
            "expected_attestations": [
                {
                    "gate_name": item["gate_name"],
                    "attestation_sha256": item["attestation_sha256"],
                }
                for item in preview["attestation_manifest"]
            ],
        },
    )
    assert frozen.status_code == 201, frozen.text
    package = frozen.json()

    db_session.execute(
        text(
            "UPDATE pilot_launch_packages "
            "SET release_ref = 'tampered-release' "
            "WHERE id = :package_id"
        ),
        {"package_id": package["id"]},
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/pilot-readiness/manual-gates/launch-packages/{package['id']}"
    )
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"].lower()
