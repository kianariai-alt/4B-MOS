import pytest


pytestmark = pytest.mark.usefixtures("authenticated_admin")


def create_role_headers(client, *, username: str, role: str) -> dict[str, str]:
    created = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "display_name": username.replace("_", " ").title(),
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


@pytest.fixture
def physician_headers(client):
    return create_role_headers(
        client,
        username="roadmap_physician",
        role="physician",
    )


@pytest.fixture
def nurse_headers(client):
    return create_role_headers(
        client,
        username="roadmap_nurse",
        role="nurse",
    )


def create_patient(
    client,
    *,
    code: str,
    date_of_birth: str = "1980-01-01",
) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": code,
            "first_name": "Synthetic",
            "last_name": code,
            "date_of_birth": date_of_birth,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_visit(client, patient_id: str, *, complaint: str) -> dict:
    response = client.post(
        f"/api/v1/patients/{patient_id}/visits",
        json={
            "chief_complaint": complaint,
            "body_region": "Knee",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def final_intake(
    client,
    visit_id: str,
    headers: dict,
    *,
    pain_score: int = 7,
    laterality: str = "right",
) -> dict:
    created = client.post(
        f"/api/v1/visits/{visit_id}/clinical-intakes",
        headers=headers,
        json={
            "chief_complaint": "Synthetic chronic knee pain",
            "history_present_illness": (
                "Synthetic chronic symptoms for transparent cohort testing."
            ),
            "body_region": "Knee",
            "laterality": laterality,
            "symptom_onset_date": "2025-01-01",
            "pain_score": pain_score,
            "functional_limitations": ["Stairs"],
            "relevant_history": [],
            "current_medications": [],
            "allergies": [],
            "exam_findings": "Synthetic examination.",
            "red_flags": [],
            "clinical_impression": "Synthetic test impression.",
            "care_goal": "Synthetic mobility goal.",
        },
    )
    assert created.status_code == 201, created.text
    finalized = client.post(
        f"/api/v1/clinical-intakes/{created.json()['id']}/finalize",
        headers=headers,
    )
    assert finalized.status_code == 200, finalized.text
    return finalized.json()


def context_hash(client, visit_id: str, headers: dict) -> str:
    response = client.get(
        f"/api/v1/visits/{visit_id}/clinical-context",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["clinical_context_sha256"]


def create_protocol(client, headers: dict, *, code: str = "ROADMAP-ACS") -> dict:
    response = client.post(
        "/api/v1/protocols",
        headers=headers,
        json={
            "code": code,
            "name": "Synthetic Roadmap ACS Protocol",
            "treatment_type": "ACS",
            "version": "1.0",
            "description": (
                "Synthetic active protocol for treatment-roadmap tests."
            ),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def complete_treatment(
    client,
    headers: dict,
    *,
    visit_id: str,
    protocol_id: str,
) -> dict:
    treatment = client.post(
        f"/api/v1/visits/{visit_id}/treatments",
        headers=headers,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol_id,
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert treatment.status_code == 201, treatment.text
    treatment = treatment.json()

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
        response = client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=headers,
            json={"operational_status": state},
        )
        assert response.status_code == 200, response.text

    finalization = client.get(
        f"/api/v1/treatment-sessions/{session_id}/finalization",
        headers=headers,
    )
    assert finalization.status_code == 200, finalization.text
    return treatment


def record_outcome(
    client,
    headers: dict,
    *,
    visit_id: str,
    treatment_id: str,
    patient_rating: int = 4,
    physician_rating: int = 4,
    follow_up_pain: int = 3,
    outcome_status: str = "improved",
    adverse_events: list[str] | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/treatments/{treatment_id}/outcomes",
        headers=headers,
        json={
            "expected_clinical_context_sha256": context_hash(
                client,
                visit_id,
                headers,
            ),
            "follow_up_day": 90,
            "outcome_status": outcome_status,
            "patient_rating": patient_rating,
            "physician_rating": physician_rating,
            "pain_score": follow_up_pain,
            "function_score": 80,
            "outcome_measures": [],
            "adverse_events": adverse_events or [],
            "notes": "Synthetic roadmap follow-up.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_historical_case(
    client,
    headers: dict,
    protocol_id: str,
    *,
    index: int,
    patient_id: str | None = None,
    pain_score: int = 7,
    follow_up_pain: int = 3,
    outcome_status: str = "improved",
) -> tuple[dict, dict, dict]:
    patient = (
        {"id": patient_id}
        if patient_id is not None
        else create_patient(
            client,
            code=f"ROADMAP-HIST-{index:03d}",
            date_of_birth=f"198{index % 5}-01-01",
        )
    )
    visit = create_visit(
        client,
        patient["id"],
        complaint=f"Synthetic historical knee pain {index}",
    )
    intake = final_intake(
        client,
        visit["id"],
        headers,
        pain_score=pain_score,
        laterality="left" if index % 2 else "right",
    )
    treatment = complete_treatment(
        client,
        headers,
        visit_id=visit["id"],
        protocol_id=protocol_id,
    )
    outcome = record_outcome(
        client,
        headers,
        visit_id=visit["id"],
        treatment_id=treatment["id"],
        patient_rating=4,
        physician_rating=4,
        follow_up_pain=follow_up_pain,
        outcome_status=outcome_status,
    )
    return visit, intake, outcome


def create_target_case(client, headers: dict) -> tuple[dict, dict, dict]:
    patient = create_patient(
        client,
        code="ROADMAP-TARGET",
        date_of_birth="1982-06-15",
    )
    visit = create_visit(
        client,
        patient["id"],
        complaint="Synthetic target knee pain",
    )
    intake = final_intake(
        client,
        visit["id"],
        headers,
        pain_score=7,
        laterality="right",
    )
    return patient, visit, intake


def run_safety(client, visit_id: str, headers: dict) -> dict:
    response = client.post(
        f"/api/v1/visits/{visit_id}/safety-evaluations",
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_roadmap_blocks_until_current_safety_evaluation(
    client,
    physician_headers,
):
    _patient, visit, _intake = create_target_case(
        client,
        physician_headers,
    )
    response = client.get(
        f"/api/v1/visits/{visit['id']}/treatment-options-roadmap",
        headers=physician_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["roadmap_status"] == "blocked_pending_safety_evaluation"
    assert body["safety_evaluation_status"] == "missing"
    assert body["options"] == []
    assert body["ranks_treatments"] is False
    assert body["is_final_treatment_recommendation"] is False
    assert body["is_clinical_clearance"] is False

    first_hash = body["roadmap_sha256"]
    repeated = client.get(
        f"/api/v1/visits/{visit['id']}/treatment-options-roadmap",
        headers=physician_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["roadmap_sha256"] == first_hash


def test_roadmap_builds_unranked_option_from_five_similar_patients(
    client,
    physician_headers,
):
    protocol = create_protocol(client, physician_headers)
    target_patient, target_visit, _target_intake = create_target_case(
        client,
        physician_headers,
    )

    historical_codes = []
    for index in range(5):
        _visit, _intake, outcome = create_historical_case(
            client,
            physician_headers,
            protocol["id"],
            index=index,
        )
        historical_codes.append(outcome["sha256"])

    # A prior treatment belonging to the target patient must never enter the
    # "similar previous patients" cohort.
    create_historical_case(
        client,
        physician_headers,
        protocol["id"],
        index=90,
        patient_id=target_patient["id"],
    )

    # A sixth external outcome becomes unreproducible after its intake is
    # superseded, and therefore must be excluded rather than silently rematched.
    stale_visit, stale_intake, _stale_outcome = create_historical_case(
        client,
        physician_headers,
        protocol["id"],
        index=91,
    )
    superseded = client.post(
        f"/api/v1/clinical-intakes/{stale_intake['id']}/supersede",
        headers=physician_headers,
        json={
            "revision_reason": "Synthetic context change for roadmap testing.",
            "chief_complaint": "Synthetic chronic knee pain",
            "history_present_illness": (
                "Synthetic revised history that changes the context hash."
            ),
            "body_region": "Knee",
            "laterality": "right",
            "symptom_onset_date": "2025-01-01",
            "pain_score": 8,
            "functional_limitations": ["Stairs"],
            "relevant_history": [],
            "current_medications": [],
            "allergies": [],
            "exam_findings": "Synthetic revised examination.",
            "red_flags": [],
            "clinical_impression": "Synthetic revised impression.",
            "care_goal": "Synthetic mobility goal.",
        },
    )
    assert superseded.status_code == 201, superseded.text
    assert client.post(
        f"/api/v1/clinical-intakes/{superseded.json()['id']}/finalize",
        headers=physician_headers,
    ).status_code == 200

    safety = run_safety(
        client,
        target_visit["id"],
        physician_headers,
    )
    assert safety["is_clinical_clearance"] is False

    response = client.get(
        f"/api/v1/visits/{target_visit['id']}/treatment-options-roadmap",
        headers=physician_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["roadmap_status"] == "options_available"
    assert body["safety_evaluation_status"] == "current"
    assert body["matched_unique_patient_count"] == 5
    assert body["exclusions"]["excluded_current_patient"] == 1
    assert body["exclusions"]["excluded_unreproducible_context"] == 1
    assert body["option_ordering"] == "protocol_code_then_version"
    assert body["ranks_treatments"] is False
    assert body["is_final_treatment_recommendation"] is False
    assert body["local_outcomes_establish_causality"] is False
    assert len(body["options"]) == 1

    option = body["options"][0]
    assert option["protocol_code"] == "ROADMAP-ACS"
    assert option["protocol_version"] == "1.0"
    assert option["is_ranked"] is False
    assert option["is_selected"] is False
    assert option["is_prescription"] is False
    assert option["reportable_window_count"] == 1

    windows = {item["window"]: item for item in option["windows"]}
    intermediate = windows["intermediate_71_to_180_days"]
    assert intermediate["unique_patient_count"] == 5
    assert intermediate["local_data_volume"] == "very_limited"
    assert intermediate["observed_improvement_proportion"]["value"] == 1.0
    assert intermediate["observed_improvement_proportion"]["denominator"] == 5
    assert intermediate["observed_improvement_wilson_95_low"] is not None
    assert intermediate["observed_improvement_wilson_95_high"] == 1.0
    assert intermediate["median_patient_rating"]["value"] == 4.0
    assert intermediate["median_physician_rating"]["value"] == 4.0
    assert intermediate["median_pain_change"]["value"] == 4.0
    assert intermediate["documented_adverse_event_proportion"]["value"] == 0.0
    assert sorted(intermediate["source_outcome_sha256s"]) == sorted(
        historical_codes
    )
    assert windows["early_28_to_70_days"]["local_data_volume"] == "insufficient"
    assert windows["long_term_181_to_365_days"]["local_data_volume"] == "insufficient"

    serialized = response.text
    for index in range(5):
        assert f"ROADMAP-HIST-{index:03d}" not in serialized
    assert "ROADMAP-TARGET" not in serialized


def test_roadmap_becomes_stale_after_target_context_changes(
    client,
    physician_headers,
):
    _patient, visit, intake = create_target_case(
        client,
        physician_headers,
    )
    run_safety(client, visit["id"], physician_headers)

    replacement = client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/supersede",
        headers=physician_headers,
        json={
            "revision_reason": "Synthetic target context changed after safety.",
            "chief_complaint": "Synthetic chronic knee pain",
            "history_present_illness": "Synthetic changed target history.",
            "body_region": "Knee",
            "laterality": "right",
            "symptom_onset_date": "2025-01-01",
            "pain_score": 8,
            "functional_limitations": ["Stairs"],
            "relevant_history": [],
            "current_medications": [],
            "allergies": [],
            "exam_findings": "Synthetic changed target examination.",
            "red_flags": [],
            "clinical_impression": "Synthetic changed target impression.",
            "care_goal": "Synthetic mobility goal.",
        },
    )
    assert replacement.status_code == 201, replacement.text
    assert client.post(
        f"/api/v1/clinical-intakes/{replacement.json()['id']}/finalize",
        headers=physician_headers,
    ).status_code == 200

    response = client.get(
        f"/api/v1/visits/{visit['id']}/treatment-options-roadmap",
        headers=physician_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["roadmap_status"] == "blocked_stale_safety_evaluation"
    assert body["safety_evaluation_status"] == "stale"
    assert body["options"] == []


def test_roadmap_is_physician_admin_only(
    client,
    physician_headers,
    nurse_headers,
):
    _patient, visit, _intake = create_target_case(
        client,
        physician_headers,
    )
    assert client.get(
        f"/api/v1/visits/{visit['id']}/treatment-options-roadmap",
        headers=nurse_headers,
    ).status_code == 403
    assert client.get(
        f"/api/v1/visits/{visit['id']}/treatment-options-roadmap",
        headers=physician_headers,
    ).status_code == 200
