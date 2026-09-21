from datetime import date, timedelta

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from backend.app.models.clinical_context import (
    ClinicalIntake,
    ParaclinicalObservation,
    ParaclinicalReport,
)
from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.clinical_context import ClinicalContextRead
from backend.app.services.clinical_safety import clinical_context_digest


pytestmark = pytest.mark.usefixtures("authenticated_admin")


def create_role_headers(client, *, username: str, role: str) -> dict:
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


@pytest.fixture
def visit(client):
    patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "CTX-001",
            "first_name": "Context",
            "last_name": "Fixture",
            "date_of_birth": "1985-01-02",
        },
    )
    assert patient.status_code == 201, patient.text
    response = client.post(
        f"/api/v1/patients/{patient.json()['id']}/visits",
        json={"chief_complaint": "Knee pain", "body_region": "knee"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def intake_payload(**overrides) -> dict:
    payload = {
        "chief_complaint": "Progressive right knee pain",
        "history_present_illness": (
            "Pain increased during stairs over the previous six months."
        ),
        "body_region": "knee",
        "laterality": "right",
        "symptom_onset_date": "2026-03-01",
        "pain_score": 6,
        "functional_limitations": ["Stairs", "stairs", "Long walks"],
        "relevant_history": ["Prior physiotherapy"],
        "current_medications": ["Synthetic test medication"],
        "allergies": ["No known drug allergies"],
        "exam_findings": "Synthetic examination finding for tests.",
        "red_flags": [],
        "clinical_impression": "Synthetic clinician-entered impression.",
        "care_goal": "Improve walking tolerance.",
    }
    payload.update(overrides)
    return payload


def quantity_observation(**overrides) -> dict:
    payload = {
        "category": "laboratory",
        "code_system": "LOINC",
        "code_system_version": "2.80",
        "code": "718-7",
        "display_name": "Hemoglobin [Mass/volume] in Blood",
        "value_type": "quantity",
        "quantity_value": "13.200000",
        "unit_code": "g/dL",
        "unit_display": "grams per deciliter",
        "reference_low": "12.0",
        "reference_high": "16.0",
        "interpretation": "normal",
        "specimen": "Blood",
        "observed_at": "2026-09-18T08:15:00+03:30",
    }
    payload.update(overrides)
    return payload


def report_payload(**overrides) -> dict:
    payload = {
        "report_key": "lab-cbc-20260918",
        "category": "laboratory",
        "title": "Complete blood count",
        "external_identifier": "LAB-TEST-001",
        "performed_at": "2026-09-18T08:00:00Z",
        "issued_at": "2026-09-18T09:00:00Z",
        "performer": "Synthetic Laboratory",
        "conclusion": "Synthetic report conclusion for automated tests.",
        "source_reference": "urn:test:lab-report:001",
        "observations": [quantity_observation()],
    }
    payload.update(overrides)
    return payload


def create_intake(client, visit_id: str, **overrides) -> dict:
    response = client.post(
        f"/api/v1/visits/{visit_id}/clinical-intakes",
        json=intake_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_report(client, visit_id: str, **overrides) -> dict:
    response = client.post(
        f"/api/v1/visits/{visit_id}/paraclinical-reports",
        json=report_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_current_context_exposes_canonical_guard_digest(client, visit):
    empty_response = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    )
    assert empty_response.status_code == 200, empty_response.text
    empty_payload = empty_response.json()
    empty_context = ClinicalContextRead.model_validate(empty_payload)
    assert empty_payload["clinical_context_sha256"] == clinical_context_digest(
        empty_context
    )

    intake = create_intake(client, visit["id"])
    assert client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/finalize"
    ).status_code == 200

    final_payload = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    final_context = ClinicalContextRead.model_validate(final_payload)
    assert final_payload["clinical_context_sha256"] == clinical_context_digest(
        final_context
    )
    assert final_payload["clinical_context_sha256"] != empty_payload[
        "clinical_context_sha256"
    ]


def test_intake_is_structured_deduplicated_and_hashed(client, visit):
    intake = create_intake(client, visit["id"])

    assert intake["status"] == "draft"
    assert intake["version"] == 1
    assert intake["functional_limitations"] == ["Stairs", "Long walks"]
    assert len(intake["content_sha256"]) == 64
    assert intake["row_version"] == 1

    duplicate = client.post(
        f"/api/v1/visits/{visit['id']}/clinical-intakes",
        json=intake_payload(),
    )
    assert duplicate.status_code == 409
    assert "lineage" in duplicate.json()["detail"]


def test_intake_validation_rejects_future_onset_and_bad_pain(client, visit):
    future = (date.today() + timedelta(days=1)).isoformat()
    assert client.post(
        f"/api/v1/visits/{visit['id']}/clinical-intakes",
        json=intake_payload(symptom_onset_date=future),
    ).status_code == 422
    assert client.post(
        f"/api/v1/visits/{visit['id']}/clinical-intakes",
        json=intake_payload(pain_score=11),
    ).status_code == 422


def test_final_intake_is_immutable_and_correction_is_atomic(client, visit):
    original = create_intake(client, visit["id"])
    finalized = client.post(
        f"/api/v1/clinical-intakes/{original['id']}/finalize"
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "final"

    blocked = client.put(
        f"/api/v1/clinical-intakes/{original['id']}",
        json=intake_payload(pain_score=3),
    )
    assert blocked.status_code == 409

    correction_payload = intake_payload(pain_score=4)
    correction_payload["revision_reason"] = (
        "Correct pain score after reviewing the signed source document."
    )
    correction = client.post(
        f"/api/v1/clinical-intakes/{original['id']}/supersede",
        json=correction_payload,
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["version"] == 2
    assert correction.json()["status"] == "draft"

    current_before = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert current_before["intake"]["id"] == original["id"]

    replacement_id = correction.json()["id"]
    finalized_replacement = client.post(
        f"/api/v1/clinical-intakes/{replacement_id}/finalize"
    )
    assert finalized_replacement.status_code == 200, finalized_replacement.text
    assert finalized_replacement.json()["status"] == "final"
    assert client.get(
        f"/api/v1/clinical-intakes/{original['id']}"
    ).json()["status"] == "superseded"
    assert client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()["intake"]["id"] == replacement_id


def test_final_intake_can_be_entered_in_error_with_reason(client, visit):
    intake = create_intake(client, visit["id"])
    client.post(f"/api/v1/clinical-intakes/{intake['id']}/finalize")

    too_short = client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/entered-in-error",
        json={"reason": "mistake"},
    )
    assert too_short.status_code == 422
    response = client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/entered-in-error",
        json={"reason": "Document was assigned to the wrong patient visit."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "entered_in_error"
    assert client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()["intake"] is None

    replacement_payload = intake_payload(pain_score=5)
    replacement_payload["revision_reason"] = (
        "Re-entered the intake against the correct source documentation."
    )
    replacement = client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/supersede",
        json=replacement_payload,
    )
    assert replacement.status_code == 201, replacement.text
    replacement_id = replacement.json()["id"]
    finalized = client.post(
        f"/api/v1/clinical-intakes/{replacement_id}/finalize"
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "final"
    assert client.get(
        f"/api/v1/clinical-intakes/{intake['id']}"
    ).json()["status"] == "entered_in_error"
    assert client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()["intake"]["id"] == replacement_id


@pytest.mark.parametrize(
    ("observation", "expected_fragment"),
    [
        (
            quantity_observation(unit_code=None),
            "unit_code",
        ),
        (
            quantity_observation(
                value_type="string",
                quantity_value=None,
                string_value="negative",
                unit_code="g/dL",
            ),
            "only valid for quantities",
        ),
        (
            quantity_observation(reference_low="20", reference_high="10"),
            "reference_high",
        ),
        (
            quantity_observation(
                value_type="coded",
                quantity_value=None,
                unit_code=None,
                unit_display=None,
                reference_low=None,
                reference_high=None,
                coded_value="POS",
                coded_system=None,
            ),
            "coded_system",
        ),
        (
            quantity_observation(code_system="OTHER"),
            "code_system_uri",
        ),
    ],
)
def test_observation_type_validation(
    client,
    visit,
    observation,
    expected_fragment,
):
    response = client.post(
        f"/api/v1/visits/{visit['id']}/paraclinical-reports",
        json=report_payload(observations=[observation]),
    )
    assert response.status_code == 422
    assert expected_fragment in response.text


def test_paraclinical_report_round_trips_quantity_and_timezone(client, visit):
    report = create_report(client, visit["id"])

    assert report["report_key"] == "LAB-CBC-20260918"
    assert report["status"] == "draft"
    assert report["observations"][0]["quantity_value"] == "13.200000"
    assert report["observations"][0]["unit_code"] == "g/dL"
    assert len(report["content_sha256"]) == 64

    fetched = client.get(
        f"/api/v1/paraclinical-reports/{report['id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["content_sha256"] == report["content_sha256"]


def test_other_observation_code_system_requires_and_preserves_uri(client, visit):
    observation = quantity_observation(
        code_system="OTHER",
        code_system_uri="https://example.test/codes/laboratory",
        code_system_version="2026-09",
        code="SYNTH-HGB",
    )
    report = create_report(
        client,
        visit["id"],
        observations=[observation],
    )

    stored = report["observations"][0]
    assert stored["code_system"] == "OTHER"
    assert stored["code_system_uri"] == "https://example.test/codes/laboratory"
    assert stored["code_system_version"] == "2026-09"


def test_report_draft_replacement_and_final_immutability(client, visit):
    report = create_report(client, visit["id"])
    replacement = report_payload(
        conclusion="Updated synthetic conclusion.",
        observations=[
            quantity_observation(quantity_value="14.1", interpretation="normal")
        ],
    )
    replacement.pop("report_key")
    updated = client.put(
        f"/api/v1/paraclinical-reports/{report['id']}",
        json=replacement,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["observations"][0]["quantity_value"] == "14.100000"
    assert updated.json()["content_sha256"] != report["content_sha256"]

    finalized = client.post(
        f"/api/v1/paraclinical-reports/{report['id']}/finalize"
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "final"
    assert client.put(
        f"/api/v1/paraclinical-reports/{report['id']}",
        json=replacement,
    ).status_code == 409


def test_report_correction_replaces_current_context_only_when_final(client, visit):
    original = create_report(client, visit["id"])
    client.post(f"/api/v1/paraclinical-reports/{original['id']}/finalize")

    replacement = report_payload(
        conclusion="Corrected synthetic report conclusion.",
        observations=[quantity_observation(quantity_value="12.9")],
    )
    replacement.pop("report_key")
    replacement["revision_reason"] = (
        "Corrected transcription after source report verification."
    )
    response = client.post(
        f"/api/v1/paraclinical-reports/{original['id']}/supersede",
        json=replacement,
    )
    assert response.status_code == 201, response.text
    correction = response.json()
    assert correction["version"] == 2

    before = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert [item["id"] for item in before["reports"]] == [original["id"]]

    assert client.post(
        f"/api/v1/paraclinical-reports/{correction['id']}/finalize"
    ).status_code == 200
    assert client.get(
        f"/api/v1/paraclinical-reports/{original['id']}"
    ).json()["status"] == "superseded"
    after = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert [item["id"] for item in after["reports"]] == [correction["id"]]


def test_entered_in_error_report_is_excluded_from_current_context(client, visit):
    report = create_report(client, visit["id"])
    client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize")
    response = client.post(
        f"/api/v1/paraclinical-reports/{report['id']}/entered-in-error",
        json={"reason": "The source laboratory recalled this report as invalid."},
    )
    assert response.status_code == 200, response.text
    context = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert context["reports"] == []

    replacement_payload = report_payload(
        conclusion="Replacement for the recalled synthetic source report.",
        observations=[quantity_observation(quantity_value="13.4")],
    )
    replacement_payload.pop("report_key")
    replacement_payload["revision_reason"] = (
        "Replaced the report after the source laboratory issued a valid result."
    )
    replacement = client.post(
        f"/api/v1/paraclinical-reports/{report['id']}/supersede",
        json=replacement_payload,
    )
    assert replacement.status_code == 201, replacement.text
    replacement_id = replacement.json()["id"]
    finalized = client.post(
        f"/api/v1/paraclinical-reports/{replacement_id}/finalize"
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "final"
    assert client.get(
        f"/api/v1/paraclinical-reports/{report['id']}"
    ).json()["status"] == "entered_in_error"
    current = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert [item["id"] for item in current["reports"]] == [replacement_id]


def test_current_context_exposes_only_final_records(client, visit):
    intake = create_intake(client, visit["id"])
    report = create_report(client, visit["id"])
    empty = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert empty["intake"] is None
    assert empty["reports"] == []

    client.post(f"/api/v1/clinical-intakes/{intake['id']}/finalize")
    client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize")
    context = client.get(
        f"/api/v1/visits/{visit['id']}/clinical-context"
    ).json()
    assert context["intake"]["id"] == intake["id"]
    assert context["reports"][0]["id"] == report["id"]


def test_patient_context_never_promotes_itself_to_general_knowledge(
    client,
    visit,
    db_session,
):
    intake = create_intake(client, visit["id"])
    report = create_report(client, visit["id"])
    client.post(f"/api/v1/clinical-intakes/{intake['id']}/finalize")
    client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize")

    assert db_session.query(MedicalKnowledgeFact).count() == 0


def test_integrity_checks_detect_intake_report_and_observation_tampering(
    client,
    visit,
    db_session,
):
    intake = create_intake(client, visit["id"])
    report = create_report(client, visit["id"])

    db_session.execute(
        update(ClinicalIntake)
        .where(ClinicalIntake.id == intake["id"])
        .values(pain_score=1)
    )
    db_session.execute(
        update(ParaclinicalObservation)
        .where(ParaclinicalObservation.report_id == report["id"])
        .values(quantity_value=99)
    )
    db_session.commit()

    intake_response = client.get(
        f"/api/v1/clinical-intakes/{intake['id']}"
    )
    assert intake_response.status_code == 409
    assert "integrity check" in intake_response.json()["detail"]
    report_response = client.get(
        f"/api/v1/paraclinical-reports/{report['id']}"
    )
    assert report_response.status_code == 409
    assert "integrity check" in report_response.json()["detail"]


def test_clinical_write_and_audit_are_atomic(
    client,
    visit,
    db_session,
    monkeypatch,
):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(AuditLogRepository, "create", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        client.post(
            f"/api/v1/visits/{visit['id']}/clinical-intakes",
            json=intake_payload(),
        )
    assert db_session.query(ClinicalIntake).count() == 0


def test_role_boundaries_allow_authoring_but_reserve_finalization(
    client,
    visit,
):
    nurse = create_role_headers(
        client,
        username="context_nurse",
        role="nurse",
    )
    viewer = create_role_headers(
        client,
        username="context_viewer",
        role="viewer",
    )
    response = client.post(
        f"/api/v1/visits/{visit['id']}/clinical-intakes",
        json=intake_payload(),
        headers=nurse,
    )
    assert response.status_code == 201, response.text
    intake = response.json()
    assert client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/finalize",
        headers=nurse,
    ).status_code == 403
    assert client.get(
        f"/api/v1/clinical-intakes/{intake['id']}",
        headers=viewer,
    ).status_code == 200
    assert client.put(
        f"/api/v1/clinical-intakes/{intake['id']}",
        json=intake_payload(),
        headers=viewer,
    ).status_code == 403


def test_audit_metadata_avoids_clinical_content(client, visit):
    intake = create_intake(client, visit["id"])
    report = create_report(client, visit["id"])

    intake_events = client.get(
        f"/api/v1/clinical-intakes/{intake['id']}/audit-logs"
    )
    report_events = client.get(
        f"/api/v1/paraclinical-reports/{report['id']}/audit-logs"
    )
    assert intake_events.status_code == 200
    assert report_events.status_code == 200
    serialized = intake_events.text + report_events.text
    assert "Progressive right knee pain" not in serialized
    assert "Hemoglobin" not in serialized
    assert "content_sha256" in serialized


def test_completed_visit_rejects_first_intake_but_accepts_late_report(
    client,
    visit,
):
    assert client.patch(
        f"/api/v1/visits/{visit['id']}",
        json={"status": "completed"},
    ).status_code == 200
    intake = client.post(
        f"/api/v1/visits/{visit['id']}/clinical-intakes",
        json=intake_payload(),
    )
    assert intake.status_code == 409
    assert create_report(client, visit["id"])["status"] == "draft"


def test_report_list_filters_normalized_key(client, visit):
    first = create_report(client, visit["id"])
    second = create_report(
        client,
        visit["id"],
        report_key="imaging-mri-20260918",
        category="imaging",
        title="Knee MRI",
        conclusion="Synthetic MRI conclusion.",
        observations=[],
    )
    response = client.get(
        f"/api/v1/visits/{visit['id']}/paraclinical-reports",
        params={"report_key": "lab-cbc-20260918"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [first["id"]]
    assert first["id"] != second["id"]


def test_database_rejects_mismatched_observation_value(db_session, client, visit):
    report = create_report(client, visit["id"])
    observation_id = report["observations"][0]["id"]
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    with pytest.raises(IntegrityError):
        db_session.execute(
            update(ParaclinicalObservation)
            .where(ParaclinicalObservation.id == observation_id)
            .values(value_type="string", string_value="bad")
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            update(ParaclinicalObservation)
            .where(ParaclinicalObservation.id == observation_id)
            .values(code_system="OTHER", code_system_uri="")
        )
        db_session.commit()
    db_session.rollback()


def test_unknown_records_and_visits_are_404(client):
    assert client.get(
        "/api/v1/clinical-intakes/missing"
    ).status_code == 404
    assert client.get(
        "/api/v1/paraclinical-reports/missing"
    ).status_code == 404
    assert client.get(
        "/api/v1/visits/missing/clinical-context"
    ).status_code == 404
