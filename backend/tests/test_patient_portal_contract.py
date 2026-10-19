from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from backend.app.schemas.patient_portal import PatientRequestCreate


def request(**updates):
    return dict(request_key="request-123", entry_mode="clinic_arrival",
                first_name="Synthetic", last_name="Patient", complaint="Test only",
                processing_notice_version="v1", processing_consent=True, **updates)


def test_optional_marketing_and_unknown_clinical_information():
    item = PatientRequestCreate(**request())
    assert item.marketing_opt_in is False
    assert item.pain_score is None
    assert item.medications == []
    assert item.allergies == []


@pytest.mark.parametrize("field,value", [
    ("clinic_id", "other-clinic"), ("patient_id", "other-patient"),
    ("assigned_physician_id", "doctor"), ("state", "final"),
    ("verified", True), ("pain_score", True), ("pain_score", 11),
    ("conditions", [" "]), ("allergies", ["x" * 501]),
    ("date_of_birth", date.today() + timedelta(days=1)),
    ("symptom_onset_date", date.today() + timedelta(days=1)),
])
def test_rejects_patient_claims_of_authority_and_invalid_values(field, value):
    payload = request()
    payload[field] = value
    with pytest.raises(ValidationError):
        PatientRequestCreate(**payload)


def test_processing_consent_required_but_marketing_independent():
    payload = request()
    payload["processing_consent"] = False
    with pytest.raises(ValidationError):
        PatientRequestCreate(**payload)
    payload["processing_consent"] = True
    payload["marketing_opt_in"] = False
    assert PatientRequestCreate(**payload).processing_consent is True


def test_patient_reported_medications_remain_unverified_statements():
    item = PatientRequestCreate(**request(medications=[{"name": "Test medicine"}]))
    assert item.medications[0].use_status == "unknown"
    payload = request(medications=[{"name": "Test", "physician_approved": True}])
    with pytest.raises(ValidationError):
        PatientRequestCreate(**payload)
