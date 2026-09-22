import pytest
from sqlalchemy import update

from backend.app.models.protocol_governance import ProtocolGovernanceCase
from backend.tests.test_protocols import protocol_payload
from backend.tests.test_treatment_options_roadmap import create_role_headers


pytestmark = pytest.mark.usefixtures("authenticated_admin")


@pytest.fixture
def author_headers(client):
    return create_role_headers(
        client,
        username="governance_author",
        role="physician",
    )


@pytest.fixture
def reviewer_headers(client):
    return create_role_headers(
        client,
        username="governance_reviewer",
        role="physician",
    )


def current_learning_hash(client, headers) -> str:
    response = client.get("/api/v1/learning/review", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["review_sha256"]


def test_governance_signals_are_non_prescriptive(client, author_headers):
    created = client.post(
        "/api/v1/protocols",
        headers=author_headers,
        json=protocol_payload(code="GOV-ACS", treatment_type="ACS"),
    )
    assert created.status_code == 201, created.text

    response = client.get(
        "/api/v1/learning/governance/signals",
        headers=author_headers,
    )
    assert response.status_code == 200, response.text
    signals = response.json()
    assert len(signals) == 1
    item = signals[0]
    assert item["protocol_code"] == "GOV-ACS"
    assert "insufficient_outcome_volume" in item["signals"]
    assert "early_followup_gap" in item["signals"]
    assert "intermediate_followup_gap" in item["signals"]
    assert "long_term_followup_gap" in item["signals"]
    assert item["system_recommends_protocol_change"] is False
    assert item["requires_human_review"] is True


def test_revision_case_requires_independent_clinical_and_admin_review(
    client,
    author_headers,
    reviewer_headers,
):
    source = client.post(
        "/api/v1/protocols",
        headers=author_headers,
        json=protocol_payload(
            code="GOV-REV",
            version="1.0",
            treatment_type="ACS",
        ),
    )
    assert source.status_code == 201, source.text

    learning_hash = current_learning_hash(client, author_headers)
    case_response = client.post(
        "/api/v1/protocol-governance/cases",
        headers=author_headers,
        json={
            "protocol_code": "GOV-REV",
            "protocol_version": "1.0",
            "source_learning_review_sha256": learning_hash,
            "case_type": "revision_candidate",
            "rationale": (
                "Synthetic governance rationale for independent review of a "
                "possible future protocol revision."
            ),
            "evidence_needed": [
                "More structured follow-up",
                "Independent clinical review",
            ],
            "proposed_protocol": protocol_payload(
                code="GOV-REV",
                version="2.0",
                treatment_type="ACS",
            ),
        },
    )
    assert case_response.status_code == 201, case_response.text
    case = case_response.json()
    assert case["status"] == "awaiting_clinical_review"
    assert case["automatically_changes_protocol"] is False
    assert case["requires_manual_protocol_action"] is True

    # Opening the case must not create the proposed protocol version.
    protocols = client.get("/api/v1/protocols", headers=author_headers).json()
    assert {(item["code"], item["version"]) for item in protocols} == {
        ("GOV-REV", "1.0")
    }

    self_review = client.post(
        f"/api/v1/protocol-governance/cases/{case['id']}/reviews",
        headers=author_headers,
        json={
            "expected_case_sha256": case["sha256"],
            "action": "clinical_approve",
            "rationale": "Synthetic self approval must not be allowed.",
        },
    )
    assert self_review.status_code == 403

    approved = client.post(
        f"/api/v1/protocol-governance/cases/{case['id']}/reviews",
        headers=reviewer_headers,
        json={
            "expected_case_sha256": case["sha256"],
            "action": "clinical_approve",
            "rationale": (
                "Independent synthetic physician review accepts this only as "
                "a candidate for manual protocol governance action."
            ),
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "awaiting_operational_review"

    admin_ack = client.post(
        f"/api/v1/protocol-governance/cases/{case['id']}/reviews",
        json={
            "expected_case_sha256": case["sha256"],
            "action": "operational_acknowledge",
            "rationale": (
                "Synthetic administrator acknowledgement of operational "
                "readiness for manual action."
            ),
        },
    )
    assert admin_ack.status_code == 200, admin_ack.text
    final_case = admin_ack.json()
    assert final_case["status"] == "approved_for_manual_action"
    assert len(final_case["reviews"]) == 2

    # Even fully reviewed governance does not mutate or create protocols.
    protocols = client.get("/api/v1/protocols").json()
    assert {(item["code"], item["version"]) for item in protocols} == {
        ("GOV-REV", "1.0")
    }


def test_case_rejects_stale_learning_review(
    client,
    author_headers,
):
    client.post(
        "/api/v1/protocols",
        headers=author_headers,
        json=protocol_payload(
            code="GOV-STALE",
            version="1.0",
            treatment_type="ACS",
        ),
    )
    stale_hash = current_learning_hash(client, author_headers)

    # Adding another protocol changes the learning-review payload/hash.
    client.post(
        "/api/v1/protocols",
        headers=author_headers,
        json=protocol_payload(
            code="GOV-OTHER",
            version="1.0",
            treatment_type="PL",
        ),
    )
    response = client.post(
        "/api/v1/protocol-governance/cases",
        headers=author_headers,
        json={
            "protocol_code": "GOV-STALE",
            "protocol_version": "1.0",
            "source_learning_review_sha256": stale_hash,
            "case_type": "collect_more_data",
            "rationale": (
                "Synthetic governance request using an intentionally stale "
                "learning review hash."
            ),
            "evidence_needed": ["More follow-up"],
        },
    )
    assert response.status_code == 409
    assert "learning review changed" in response.json()["detail"]


def test_case_is_append_only_and_nurse_cannot_read(
    client,
    author_headers,
    db_session,
):
    created = client.post(
        "/api/v1/protocols",
        headers=author_headers,
        json=protocol_payload(
            code="GOV-IMM",
            version="1.0",
            treatment_type="ACS",
        ),
    )
    assert created.status_code == 201
    case_response = client.post(
        "/api/v1/protocol-governance/cases",
        headers=author_headers,
        json={
            "protocol_code": "GOV-IMM",
            "protocol_version": "1.0",
            "source_learning_review_sha256": current_learning_hash(
                client,
                author_headers,
            ),
            "case_type": "collect_more_data",
            "rationale": (
                "Synthetic immutable governance case for append-only testing."
            ),
            "evidence_needed": ["More outcomes"],
        },
    )
    assert case_response.status_code == 201, case_response.text
    case = case_response.json()

    nurse = create_role_headers(
        client,
        username="governance_nurse",
        role="nurse",
    )
    assert client.get(
        f"/api/v1/protocol-governance/cases/{case['id']}",
        headers=nurse,
    ).status_code == 403

    record = db_session.get(ProtocolGovernanceCase, case["id"])
    record.rationale = "This rewrite must fail."
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()

    db_session.execute(
        update(ProtocolGovernanceCase)
        .where(ProtocolGovernanceCase.id == case["id"])
        .values(payload={})
    )
    db_session.commit()
    tampered = client.get(
        f"/api/v1/protocol-governance/cases/{case['id']}",
        headers=author_headers,
    )
    assert tampered.status_code == 409
    assert "integrity check" in tampered.json()["detail"]
