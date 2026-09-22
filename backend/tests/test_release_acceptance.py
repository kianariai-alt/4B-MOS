"""Release-level acceptance scenarios across the public HTTP API."""

from copy import deepcopy

from backend.app.main import app
from backend.app.services.session_finalization import evidence_digest


def create_user_and_login(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> dict[str, str]:
    password = "StrongPass123"
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "password": password,
            "role": role,
        },
    )
    assert created.status_code == 201, created.text

    authenticated = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )
    assert authenticated.status_code == 200, authenticated.text

    return {
        "Authorization": (
            "Bearer " + authenticated.json()["access_token"]
        )
    }


def assert_status(response, expected: int) -> dict:
    assert response.status_code == expected, response.text
    return response.json()


def transition(client, headers, session_id: str, target: str) -> dict:
    return assert_status(
        client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=headers,
            json={"operational_status": target},
        ),
        200,
    )


def test_complete_clinical_journey_is_coherent_and_append_only(
    client,
    admin_headers,
):
    operator = create_user_and_login(
        client,
        admin_headers,
        username="acceptance_operator",
        role="operator",
    )
    physician = create_user_and_login(
        client,
        admin_headers,
        username="acceptance_physician",
        role="physician",
    )
    nurse = create_user_and_login(
        client,
        admin_headers,
        username="acceptance_nurse",
        role="nurse",
    )
    reviewer = create_user_and_login(
        client,
        admin_headers,
        username="acceptance_reviewer",
        role="physician",
    )
    viewer = create_user_and_login(
        client,
        admin_headers,
        username="acceptance_viewer",
        role="viewer",
    )

    material = assert_status(
        client.post(
            "/api/v1/orthobiologic-materials",
            headers=admin_headers,
            json={
                "code": "ACCEPT-ACS",
                "name": "Acceptance Autologous Conditioned Serum",
                "default_unit": "ml",
                "is_autologous": True,
                "requires_lot_tracking": True,
            },
        ),
        201,
    )
    protocol = assert_status(
        client.post(
            "/api/v1/protocols",
            headers=admin_headers,
            json={
                "code": "ACCEPT-ACS-KNEE",
                "name": "Acceptance ACS Knee Protocol",
                "treatment_type": "ACS",
                "version": "1.0",
                "description": "Synthetic release-acceptance protocol.",
                "preparation_parameters": {"method": "acceptance"},
                "administration_parameters": {
                    "route": "intra-articular"
                },
                "monitoring_parameters": {"follow_up": "configured"},
            },
        ),
        201,
    )

    patient = assert_status(
        client.post(
            "/api/v1/patients",
            headers=operator,
            json={
                "patient_code": "RELEASE-ACCEPT-001",
                "first_name": "Release",
                "last_name": "Acceptance",
                "date_of_birth": "1990-01-01",
            },
        ),
        201,
    )
    visit = assert_status(
        client.post(
            f"/api/v1/patients/{patient['id']}/visits",
            headers=operator,
            json={
                "chief_complaint": "Knee pain",
                "body_region": "Knee",
                "diagnosis": "Knee osteoarthritis",
                "notes": "Synthetic acceptance record; no patient data.",
            },
        ),
        201,
    )
    intake = assert_status(
        client.post(
            f"/api/v1/visits/{visit['id']}/clinical-intakes",
            headers=operator,
            json={
                "chief_complaint": "Synthetic right knee pain",
                "history_present_illness": (
                    "Synthetic acceptance history with gradual symptom onset."
                ),
                "body_region": "Knee",
                "laterality": "right",
                "pain_score": 6,
                "functional_limitations": ["Stairs"],
                "red_flags": [],
                "clinical_impression": "Synthetic acceptance impression.",
            },
        ),
        201,
    )
    assert_status(
        client.post(
            f"/api/v1/clinical-intakes/{intake['id']}/finalize",
            headers=physician,
        ),
        200,
    )
    report = assert_status(
        client.post(
            f"/api/v1/visits/{visit['id']}/paraclinical-reports",
            headers=nurse,
            json={
                "report_key": "acceptance-lab-001",
                "category": "laboratory",
                "title": "Synthetic acceptance laboratory report",
                "conclusion": "Synthetic acceptance result only.",
                "observations": [
                    {
                        "category": "laboratory",
                        "code_system": "LOCAL",
                        "code": "ACCEPT-RESULT",
                        "display_name": "Synthetic acceptance result",
                        "value_type": "boolean",
                        "boolean_value": True,
                    }
                ],
            },
        ),
        201,
    )
    assert_status(
        client.post(
            f"/api/v1/paraclinical-reports/{report['id']}/finalize",
            headers=physician,
        ),
        200,
    )
    context = assert_status(
        client.get(
            f"/api/v1/visits/{visit['id']}/clinical-context",
            headers=viewer,
        ),
        200,
    )
    assert context["intake"]["id"] == intake["id"]
    assert [item["id"] for item in context["reports"]] == [report["id"]]
    safety_evaluation = assert_status(
        client.post(
            f"/api/v1/visits/{visit['id']}/safety-evaluations",
            headers=physician,
        ),
        201,
    )
    assert safety_evaluation["outcome"] == "no_active_rules"
    assert safety_evaluation["evaluated_rule_count"] == 0
    assert safety_evaluation["findings"] == []
    assert safety_evaluation["is_clinical_clearance"] is False
    escalation_queue = assert_status(
        client.get(
            "/api/v1/safety/escalations?limit=50",
            headers=nurse,
        ),
        200,
    )
    assert escalation_queue["total"] == 0
    assert escalation_queue["items"] == []
    assert escalation_queue["is_clinical_priority_order"] is False
    assert escalation_queue["is_clinical_clearance"] is False
    treatment = assert_status(
        client.post(
            f"/api/v1/visits/{visit['id']}/treatments",
            headers=physician,
            json={
                "treatment_type": "ACS",
                "protocol_template_id": protocol["id"],
                "body_region": "Knee",
                "dose_or_volume": "3 ml",
            },
        ),
        201,
    )
    assert treatment["protocol_name"] == protocol["name"]
    assert treatment["protocol_snapshot"]["version"] == "1.0"

    plan = assert_status(
        client.post(
            f"/api/v1/treatments/{treatment['id']}/components",
            headers=physician,
            json={
                "material_id": material["id"],
                "planned_amount": "3",
                "notes": "Synthetic planned component.",
            },
        ),
        201,
    )
    session = assert_status(
        client.post(
            f"/api/v1/treatments/{treatment['id']}/sessions",
            headers=operator,
            json={
                "session_number": 1,
                "body_region": "Knee",
                "dose_or_volume": "3 ml",
            },
        ),
        201,
    )
    session_id = session["id"]

    assert transition(
        client, operator, session_id, "checked_in"
    )["operational_status"] == "checked_in"
    assert transition(
        client, nurse, session_id, "ready"
    )["operational_status"] == "ready"
    assert transition(
        client, physician, session_id, "in_treatment"
    )["operational_status"] == "in_treatment"

    administration = assert_status(
        client.post(
            f"/api/v1/treatment-sessions/{session_id}/components",
            headers=nurse,
            json={
                "treatment_component_id": plan["id"],
                "material_id": material["id"],
                "actual_amount": "3",
                "lot_number": "ACCEPT-LOT-001",
                "expiry_date": "2027-12-31",
                "preparation_parameters": {"cycles": 3},
                "notes": "Synthetic administration record.",
            },
        ),
        201,
    )
    assert administration["unit"] == "ml"
    assert administration["lot_number"] == "ACCEPT-LOT-001"

    variance = assert_status(
        client.get(
            f"/api/v1/treatment-sessions/{session_id}/variance",
            headers=viewer,
        ),
        200,
    )
    assert variance["matched_count"] == 1
    assert variance["unplanned_count"] == 0

    clinical_summary = assert_status(
        client.get(
            f"/api/v1/treatment-sessions/{session_id}/clinical-summary",
            headers=viewer,
        ),
        200,
    )
    assert clinical_summary["plan_alignment_status"] == "aligned"
    assert clinical_summary["has_deviations"] is False

    completion = assert_status(
        client.get(
            f"/api/v1/treatment-sessions/{session_id}/completion-check",
            headers=viewer,
        ),
        200,
    )
    assert completion["can_complete"] is True
    assert completion["readiness"] == "ready"

    completed = transition(client, nurse, session_id, "completed")
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None

    finalization_url = (
        f"/api/v1/treatment-sessions/{session_id}/finalization"
    )
    finalization = assert_status(
        client.get(finalization_url, headers=viewer),
        200,
    )
    assert evidence_digest(finalization["payload"]) == finalization["sha256"]
    assert finalization["payload"]["actor"]["actor_role"] == "nurse"
    assert finalization["payload"]["treatment"]["protocol_version"] == "1.0"
    assert finalization["payload"]["treatment"]["protocol_snapshot"][
        "source_template_id"
    ] == protocol["id"]
    assert finalization["payload"]["administrations"][0][
        "lot_number"
    ] == "ACCEPT-LOT-001"
    original_finalization = deepcopy(finalization)

    immutable_edit = client.patch(
        f"/api/v1/treatment-sessions/{session_id}",
        headers=physician,
        json={"notes": "This rewrite must be refused."},
    )
    assert immutable_edit.status_code == 409
    immutable_administration = client.post(
        f"/api/v1/treatment-sessions/{session_id}/components",
        headers=nurse,
        json={
            "material_id": material["id"],
            "actual_amount": "1",
            "lot_number": "TOO-LATE",
        },
    )
    assert immutable_administration.status_code == 409

    amendment = assert_status(
        client.post(
            f"/api/v1/treatment-sessions/{session_id}/amendments",
            headers=nurse,
            json={
                "amendment_type": "supplement",
                "reason_code": "late_result",
                "reason_detail": "A synthetic follow-up result became available.",
                "statement": "Synthetic follow-up remained clinically stable.",
            },
        ),
        201,
    )
    assert amendment["status"] == "pending"
    assert amendment["payload"]["author"]["actor_role"] == "nurse"
    assert amendment["payload"]["finalization_sha256"] == finalization["sha256"]

    reviewed = assert_status(
        client.post(
            f"/api/v1/treatment-sessions/{session_id}/amendments/"
            f"{amendment['id']}/review",
            headers=reviewer,
            json={
                "decision": "approved",
                "comment": "Synthetic acceptance review completed.",
            },
        ),
        201,
    )
    assert reviewed["status"] == "approved"
    assert reviewed["review"]["payload"]["reviewer"][
        "actor_role"
    ] == "physician"
    assert assert_status(
        client.get(
            f"/api/v1/treatment-sessions/{session_id}/amendments",
            headers=viewer,
        ),
        200,
    )[0]["status"] == "approved"

    discharged = transition(client, nurse, session_id, "discharged")
    assert discharged["operational_status"] == "discharged"
    assert assert_status(
        client.get(finalization_url, headers=viewer),
        200,
    ) == original_finalization

    patient_summary = assert_status(
        client.get(
            f"/api/v1/patients/{patient['id']}/clinical-summary",
            headers=viewer,
        ),
        200,
    )
    assert patient_summary["total_visits"] == 1
    assert patient_summary["total_treatments"] == 1
    assert patient_summary["completed_session_count"] == 1
    assert patient_summary["last_completed_session"]["id"] == session_id

    timeline = assert_status(
        client.get(
            f"/api/v1/patients/{patient['id']}/timeline",
            headers=physician,
        ),
        200,
    )
    assert timeline["patient_id"] == patient["id"]
    assert {item["entity_id"] for item in timeline["items"]}.issuperset(
        {visit["id"], treatment["id"], session_id}
    )

    session_audit = assert_status(
        client.get(
            f"/api/v1/treatment-sessions/{session_id}/audit-logs",
            headers=physician,
        ),
        200,
    )
    event_types = {event["event_type"] for event in session_audit}
    assert {
        "session_created",
        "operational_transition",
        "state_transition",
        "session_amendment_created",
        "session_amendment_approved",
    }.issubset(event_types)


def test_openapi_keeps_release_endpoints_and_unique_operation_ids():
    schema = app.openapi()
    required_operations = {
        ("/api/v1/auth/login", "post"),
        ("/api/v1/patients", "post"),
        ("/api/v1/patients/{patient_id}/visits", "post"),
        ("/api/v1/visits/{visit_id}/clinical-intakes", "post"),
        ("/api/v1/clinical-intakes/{intake_id}/finalize", "post"),
        ("/api/v1/visits/{visit_id}/paraclinical-reports", "post"),
        ("/api/v1/paraclinical-reports/{report_id}/finalize", "post"),
        ("/api/v1/visits/{visit_id}/clinical-context", "get"),
        ("/api/v1/safety/rules", "post"),
        ("/api/v1/safety/rules/active", "get"),
        ("/api/v1/visits/{visit_id}/safety-evaluations", "post"),
        ("/api/v1/safety/evaluations/{evaluation_id}", "get"),
        ("/api/v1/safety/escalations", "get"),
        (
            "/api/v1/visits/{visit_id}/safety-findings/{finding_id}/reviews",
            "post",
        ),
        (
            "/api/v1/visits/{visit_id}/safety-findings/{finding_id}/reviews",
            "get",
        ),
        ("/api/v1/safety/finding-reviews/{review_id}", "get"),
        (
            "/api/v1/visits/{visit_id}/evidence-briefs",
            "post",
        ),
        (
            "/api/v1/visits/{visit_id}/evidence-briefs",
            "get",
        ),
        ("/api/v1/evidence-briefs/{brief_id}", "get"),
        ("/api/v1/visits/{visit_id}/treatments", "post"),
        (
            "/api/v1/visits/{visit_id}/treatment-options-roadmap",
            "get",
        ),
        (
            "/api/v1/visits/{visit_id}/treatment-decisions",
            "post",
        ),
        (
            "/api/v1/visits/{visit_id}/treatment-decisions",
            "get",
        ),
        ("/api/v1/treatment-decisions/{decision_id}", "get"),
        ("/api/v1/learning/review", "get"),
        ("/api/v1/learning/governance/signals", "get"),
        ("/api/v1/protocol-governance/cases", "post"),
        ("/api/v1/protocol-governance/cases", "get"),
        ("/api/v1/protocol-governance/cases/{case_id}", "get"),
        (
            "/api/v1/protocol-governance/cases/{case_id}/reviews",
            "post",
        ),
        (
            "/api/v1/protocol-governance/cases/{case_id}/release",
            "post",
        ),
        ("/api/v1/protocol-governance/releases", "get"),
        ("/api/v1/treatments/{treatment_id}/outcomes", "post"),
        ("/api/v1/treatments/{treatment_id}/outcomes", "get"),
        ("/api/v1/treatment-outcomes/{outcome_id}", "get"),
        ("/api/v1/treatments/{treatment_id}/sessions", "post"),
        ("/api/v1/treatment-sessions/{session_id}/workflow", "patch"),
        ("/api/v1/treatment-sessions/{session_id}/completion-check", "get"),
        ("/api/v1/treatment-sessions/{session_id}/finalization", "get"),
        ("/api/v1/treatment-sessions/{session_id}/amendments", "post"),
        (
            "/api/v1/treatment-sessions/{session_id}/amendments/"
            "{amendment_id}/review",
            "post",
        ),
    }
    for path, method in required_operations:
        assert method in schema["paths"][path]

    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]
    assert len(operation_ids) == len(set(operation_ids))
