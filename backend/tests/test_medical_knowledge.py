from datetime import date

import pytest
from sqlalchemy import update

from backend.app.models.medical_knowledge import MedicalKnowledgeFact


pytestmark = pytest.mark.usefixtures("authenticated_admin")


def knowledge_payload(
    *,
    fact_key="ACS-OA-001",
    title="ACS evidence statement",
    statement=(
        "This is a source-linked clinical knowledge statement long enough "
        "to pass validation without asserting an unreviewed treatment claim."
    ),
    therapy_type="ACS",
    valid_from="2026-01-01",
    valid_to=None,
):
    return {
        "fact_key": fact_key,
        "title": title,
        "statement": statement,
        "clinical_domain": "knee osteoarthritis",
        "therapy_type": therapy_type,
        "population": "Adults assessed by a licensed clinician.",
        "indication": "Clinician-reviewed informational context.",
        "contraindications": ["Example contraindication for registry testing."],
        "evidence_grade": "ungraded",
        "valid_from": valid_from,
        "valid_to": valid_to,
        "sources": [
            {
                "source_type": "guideline",
                "title": "Synthetic guideline fixture",
                "citation": "Synthetic citation used only by automated tests.",
                "publisher": "4B-MOS Test Suite",
                "url": "https://example.test/guideline",
                "publication_date": "2025-06-01",
                "guideline_version": "1.0",
                "accessed_at": "2026-09-19",
            }
        ],
    }


def create_fact(client, **overrides):
    payload = knowledge_payload(**overrides)
    response = client.post("/api/v1/knowledge/facts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def approve_fact(client, fact_id, reviewer_headers=None):
    submitted = client.post(f"/api/v1/knowledge/facts/{fact_id}/submit")
    assert submitted.status_code == 200, submitted.text
    if reviewer_headers is None:
        reviewer_headers = create_role_headers(
            client,
            username=f"reviewer_{fact_id[:8]}",
            role="physician",
        )
    approved = client.post(
        f"/api/v1/knowledge/facts/{fact_id}/review",
        json={"decision": "approved", "comment": "Clinical fixture review."},
        headers=reviewer_headers,
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def create_role_headers(client, *, username, role):
    created = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "display_name": username.title(),
            "password": "StrongPass123",
            "role": role,
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "StrongPass123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_create_fact_is_draft_source_linked_and_hashed(client):
    data = create_fact(client, fact_key="acs.oa-001")

    assert data["fact_key"] == "ACS.OA-001"
    assert data["version"] == 1
    assert data["status"] == "draft"
    assert data["row_version"] == 1
    assert len(data["content_sha256"]) == 64
    assert data["sources"][0]["sort_order"] == 1
    assert data["sources"][0]["source_type"] == "guideline"


def test_duplicate_key_requires_superseding_version(client):
    create_fact(client)
    duplicate = client.post(
        "/api/v1/knowledge/facts",
        json=knowledge_payload(),
    )
    assert duplicate.status_code == 409
    assert "superseding version" in duplicate.json()["detail"]


def test_knowledge_payload_requires_source_and_valid_dates(client):
    missing_source = knowledge_payload()
    missing_source["sources"] = []
    assert client.post(
        "/api/v1/knowledge/facts",
        json=missing_source,
    ).status_code == 422

    invalid_dates = knowledge_payload(
        valid_from="2026-02-01",
        valid_to="2026-01-01",
    )
    assert client.post(
        "/api/v1/knowledge/facts",
        json=invalid_dates,
    ).status_code == 422


def test_only_approved_current_facts_are_exposed_to_consumers(client):
    fact = create_fact(client)
    assert client.get("/api/v1/knowledge/facts/approved").json() == []

    approved = approve_fact(client, fact["id"])
    assert approved["status"] == "approved"
    assert approved["reviewed_by_user_id"] is not None

    visible = client.get(
        "/api/v1/knowledge/facts/approved",
        params={"therapy_type": "ACS", "search": "source-linked"},
    )
    assert visible.status_code == 200
    assert [item["id"] for item in visible.json()] == [fact["id"]]

    expired_view = client.get(
        "/api/v1/knowledge/facts/approved",
        params={"as_of": "2025-12-31"},
    )
    assert expired_view.status_code == 200
    assert expired_view.json() == []


def test_approved_content_is_immutable(client):
    fact = create_fact(client)
    approve_fact(client, fact["id"])
    response = client.patch(
        f"/api/v1/knowledge/facts/{fact['id']}",
        json={"statement": "A changed statement that should be rejected."},
    )
    assert response.status_code == 409
    assert "draft or rejected" in response.json()["detail"]


def test_draft_update_replaces_sources_and_rejects_required_null(client):
    fact = create_fact(client)
    updated = client.patch(
        f"/api/v1/knowledge/facts/{fact['id']}",
        json={
            "sources": [
                {
                    "source_type": "systematic_review",
                    "title": "Replacement synthetic review",
                    "citation": "Replacement citation for automated testing.",
                    "publisher": "4B-MOS Test Suite",
                    "accessed_at": "2026-09-19",
                }
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["sources"][0]["source_type"] == "systematic_review"
    assert updated.json()["content_sha256"] != fact["content_sha256"]

    invalid = client.patch(
        f"/api/v1/knowledge/facts/{fact['id']}",
        json={"statement": None},
    )
    assert invalid.status_code == 422


def test_rejected_fact_can_be_revised_and_resubmitted(client):
    fact = create_fact(client)
    client.post(f"/api/v1/knowledge/facts/{fact['id']}/submit")
    reviewer_headers = create_role_headers(
        client,
        username="rejection_reviewer",
        role="physician",
    )

    missing_comment = client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/review",
        json={"decision": "rejected"},
        headers=reviewer_headers,
    )
    assert missing_comment.status_code == 422

    rejected = client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/review",
        json={"decision": "rejected", "comment": "Source is insufficient."},
        headers=reviewer_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    revised = client.patch(
        f"/api/v1/knowledge/facts/{fact['id']}",
        json={
            "statement": (
                "This revised source-linked statement remains a synthetic "
                "test fixture and now has enough review detail."
            )
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["status"] == "draft"
    assert revised.json()["reviewed_at"] is None
    assert client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/submit"
    ).status_code == 200


def test_author_cannot_review_own_knowledge_fact(client):
    fact = create_fact(client)
    assert client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/submit"
    ).status_code == 200

    response = client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/review",
        json={"decision": "approved", "comment": "Self review attempt."},
    )
    assert response.status_code == 409
    assert "independent reviewer" in response.json()["detail"]


def test_superseding_approval_retires_previous_version(client):
    original = create_fact(client)
    approve_fact(client, original["id"])

    replacement_payload = knowledge_payload(
        title="Updated ACS evidence statement",
        statement=(
            "This is the second reviewed version of the synthetic clinical "
            "knowledge statement used by the automated test suite."
        ),
    )
    replacement_payload.pop("fact_key")
    replacement = client.post(
        f"/api/v1/knowledge/facts/{original['id']}/supersede",
        json=replacement_payload,
    )
    assert replacement.status_code == 201, replacement.text
    replacement_data = replacement.json()
    assert replacement_data["version"] == 2
    assert replacement_data["supersedes_fact_id"] == original["id"]
    assert replacement_data["status"] == "draft"

    before_approval = client.get("/api/v1/knowledge/facts/approved").json()
    assert [item["id"] for item in before_approval] == [original["id"]]

    approve_fact(client, replacement_data["id"])
    old = client.get(f"/api/v1/knowledge/facts/{original['id']}").json()
    assert old["status"] == "retired"
    current = client.get("/api/v1/knowledge/facts/approved").json()
    assert [item["id"] for item in current] == [replacement_data["id"]]


def test_integrity_check_detects_database_content_tampering(
    client,
    db_session,
):
    fact = create_fact(client)
    db_session.execute(
        update(MedicalKnowledgeFact)
        .where(MedicalKnowledgeFact.id == fact["id"])
        .values(statement="Tampered outside the controlled service.")
    )
    db_session.commit()

    response = client.get(f"/api/v1/knowledge/facts/{fact['id']}")
    assert response.status_code == 409
    assert "integrity check" in response.json()["detail"]


def test_audit_history_covers_lifecycle(client):
    fact = create_fact(client)
    approve_fact(client, fact["id"])
    retired = client.post(f"/api/v1/knowledge/facts/{fact['id']}/retire")
    assert retired.status_code == 200
    assert retired.json()["status"] == "retired"

    response = client.get(
        f"/api/v1/knowledge/facts/{fact['id']}/audit-logs"
    )
    assert response.status_code == 200
    assert [item["event_type"] for item in response.json()] == [
        "knowledge_fact_created",
        "knowledge_fact_submitted",
        "knowledge_fact_approved",
        "knowledge_fact_retired",
    ]


def test_read_roles_cannot_author_knowledge(client):
    nurse_headers = create_role_headers(
        client,
        username="knowledge_nurse",
        role="nurse",
    )
    denied = client.post(
        "/api/v1/knowledge/facts",
        json=knowledge_payload(),
        headers=nurse_headers,
    )
    assert denied.status_code == 403

    listed = client.get(
        "/api/v1/knowledge/facts",
        headers=nurse_headers,
    )
    assert listed.status_code == 200


def test_list_filters_status_domain_key_and_paginates(client):
    first = create_fact(client, fact_key="ACS-OA-001")
    second = create_fact(
        client,
        fact_key="PL-HAIR-001",
        therapy_type="PL",
        title="Platelet lysate registry fixture",
    )
    assert first["id"] != second["id"]

    response = client.get(
        "/api/v1/knowledge/facts",
        params={"status": "draft", "fact_key": "pl-hair-001"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [second["id"]]

    page = client.get(
        "/api/v1/knowledge/facts",
        params={"skip": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert len(page.json()) == 1


def test_validity_date_is_a_real_date_in_response(client):
    fact = create_fact(client)
    assert date.fromisoformat(fact["valid_from"]) == date(2026, 1, 1)
