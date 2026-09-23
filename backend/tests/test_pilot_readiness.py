import json

import pytest

from backend.app.core.config import Settings
from backend.app.models.protocol import ProtocolTemplate
from backend.app.models.user import User
from backend.app.services.pilot_readiness import ControlledPilotReadinessService
from backend.app.services import pilot_readiness as readiness_module
from backend.tests.test_treatment_options_roadmap import create_role_headers
from backend.tools.pilot_readiness import render_text


pytestmark = pytest.mark.usefixtures("authenticated_admin")


def production_settings():
    return Settings(
        _env_file=None,
        ENVIRONMENT="production",
        DEBUG=False,
        BOOTSTRAP_ENABLED=False,
        SECRET_KEY="TEST-ONLY-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )


def seed_required_roles(db_session):
    for username, role in (
        ("pilot-admin-1", "admin"),
        ("pilot-admin-2", "admin"),
        ("pilot-physician-1", "physician"),
        ("pilot-physician-2", "physician"),
        ("pilot-nurse", "nurse"),
        ("pilot-operator", "operator"),
    ):
        db_session.add(
            User(
                username=username,
                display_name=username,
                password_hash="synthetic-hash",
                role=role,
                is_active=True,
            )
        )
    db_session.commit()


def seed_protocol(db_session):
    db_session.add(
        ProtocolTemplate(
            code="PILOT-ACS",
            name="Synthetic Pilot ACS",
            treatment_type="ACS",
            version="1.0",
            is_active=True,
        )
    )
    db_session.commit()


def stub_integrity_checks(monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        "database_readiness_issues",
        lambda db: (),
    )
    monkeypatch.setattr(
        readiness_module.ClinicalSafetyEvaluationService,
        "_active_rules",
        lambda db, as_of: [object()],
    )
    monkeypatch.setattr(
        readiness_module.ClinicalLearningReviewService,
        "get_review",
        lambda db: object(),
    )
    monkeypatch.setattr(
        readiness_module.ProtocolGovernanceService,
        "get_lineage",
        lambda db, protocol_id: object(),
    )
    monkeypatch.setattr(
        readiness_module.ProtocolGovernanceService,
        "list_cases",
        lambda db: [],
    )
    monkeypatch.setattr(
        readiness_module.ProtocolGovernanceService,
        "list_releases",
        lambda db: [],
    )
    monkeypatch.setattr(
        readiness_module.ProtocolGovernanceService,
        "list_recoveries",
        lambda db: [],
    )


def test_controlled_pilot_gate_passes_automated_prerequisites(
    db_session,
    monkeypatch,
):
    seed_required_roles(db_session)
    seed_protocol(db_session)
    stub_integrity_checks(monkeypatch)
    monkeypatch.setattr(
        db_session.get_bind().dialect,
        "name",
        "postgresql",
    )

    report = ControlledPilotReadinessService.build(
        db_session,
        production_settings(),
    )

    assert report.status == "automated_prerequisites_passed"
    assert all(item.status == "pass" for item in report.automated_checks)
    assert len(report.manual_gates) == 7
    assert {item.status for item in report.manual_gates} == {"manual_required"}
    assert len(report.readiness_sha256) == 64
    repeat = ControlledPilotReadinessService.build(
        db_session,
        production_settings(),
    )
    assert repeat.readiness_sha256 == report.readiness_sha256
    assert report.controlled_pilot_authorized is False
    assert report.is_clinical_clearance is False
    assert report.requires_human_release_decision is True

    rendered = render_text(report)
    assert "AUTOMATED_PREREQUISITES_PASSED" in rendered
    assert "controlled_pilot_authorized=false" in rendered
    assert "pilot-admin-1" not in rendered
    assert "PILOT-ACS" not in rendered
    assert "synthetic-hash" not in rendered

    serialized = json.dumps(report.model_dump(mode="json"))
    assert "pilot-admin-1" not in serialized
    assert "PILOT-ACS" not in serialized


def test_controlled_pilot_gate_requires_role_separation(
    db_session,
    monkeypatch,
):
    db_session.add(
        User(
            username="only-admin",
            display_name="Only Admin",
            password_hash="synthetic-hash",
            role="admin",
            is_active=True,
        )
    )
    db_session.commit()
    seed_protocol(db_session)
    stub_integrity_checks(monkeypatch)
    monkeypatch.setattr(
        db_session.get_bind().dialect,
        "name",
        "postgresql",
    )

    report = ControlledPilotReadinessService.build(
        db_session,
        production_settings(),
    )

    checks = {item.name: item for item in report.automated_checks}
    assert report.status == "blocked"
    assert checks["role_separation"].status == "fail"
    assert checks["role_separation"].code == "required_staff_roles_missing"


def test_controlled_pilot_gate_blocks_sqlite_even_when_other_checks_pass(
    db_session,
    monkeypatch,
):
    seed_required_roles(db_session)
    seed_protocol(db_session)
    stub_integrity_checks(monkeypatch)

    report = ControlledPilotReadinessService.build(
        db_session,
        production_settings(),
    )

    checks = {item.name: item for item in report.automated_checks}
    assert report.status == "blocked"
    assert checks["database_engine"].status == "fail"
    assert (
        checks["database_engine"].code
        == "postgresql_required_for_controlled_pilot"
    )


def test_pilot_readiness_endpoint_is_release_role_only(client):
    response = client.get("/api/v1/pilot-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["controlled_pilot_authorized"] is False
    assert body["requires_human_release_decision"] is True
    assert len(body["readiness_sha256"]) == 64

    physician_headers = create_role_headers(
        client,
        username="pilot_readiness_physician",
        role="physician",
    )
    physician_read = client.get(
        "/api/v1/pilot-readiness",
        headers=physician_headers,
    )
    assert physician_read.status_code == 200

    nurse_headers = create_role_headers(
        client,
        username="pilot_readiness_nurse",
        role="nurse",
    )
    forbidden = client.get(
        "/api/v1/pilot-readiness",
        headers=nurse_headers,
    )
    assert forbidden.status_code == 403
