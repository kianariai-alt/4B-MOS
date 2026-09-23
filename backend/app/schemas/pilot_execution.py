"""Bounded, read-only pilot operations and acceptance contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256 = r"^[0-9a-f]{64}$"


class PilotEnrollmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_release_decision_sha256: str = Field(pattern=SHA256)
    protocol_template_id: str = Field(min_length=1, max_length=36)
    clinician_decision_id: str = Field(min_length=1, max_length=36)
    expected_clinician_decision_sha256: str = Field(pattern=SHA256)
    consent_evidence_reference: str = Field(min_length=8, max_length=500)
    consent_confirmed_at: datetime
    clinician_statement: str = Field(min_length=20, max_length=5000)

    @field_validator("consent_confirmed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An offset-aware consent timestamp is required.")
        return value


class PilotEnrollmentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    release_decision_id: str
    release_decision_sha256: str
    visit_id: str
    protocol_template_id: str
    protocol_snapshot_sha256: str
    clinician_decision_id: str
    clinician_decision_sha256: str
    consent_evidence_reference: str
    consent_confirmed_at: datetime
    clinician_statement: str
    enrolled_by_user_id: str
    sha256: str
    created_at: datetime
    append_only: Literal[True] = True
    confirms_patient_consent_document_authenticity: Literal[False] = False
    authorizes_individual_treatment: Literal[False] = False
    individual_clinician_decision_required: Literal[True] = True


class PilotStopCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_release_decision_sha256: str = Field(pattern=SHA256)
    reason_category: Literal["clinical_safety", "operational", "privacy", "other"]
    reason: str = Field(min_length=20, max_length=5000)


class PilotStopRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    release_decision_id: str
    release_decision_sha256: str
    reason_category: str
    reason: str
    stopped_by_user_id: str
    sha256: str
    created_at: datetime
    append_only: Literal[True] = True
    restart_requires_new_pilot_release: Literal[True] = True


class PilotOperationsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_decision_id: str
    release_decision_sha256: str
    status: Literal["held", "scheduled", "active", "expired", "stopped"]
    enrolled_visits: int
    max_enrolled_visits: int | None
    remaining_enrollment_slots: int
    stopped: bool
    stop_sha256: str | None
    new_pilot_activity_allowed: bool
    individual_treatment_authorized: Literal[False] = False


class PilotAcceptanceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_decision_id: str
    release_decision_sha256: str
    generated_at: datetime
    operations_status: str
    enrolled_visits: int
    visits_with_treatment: int
    visits_with_outcome: int
    total_outcome_observations: int
    total_reported_adverse_event_entries: int
    enrollment_sha256s: list[str]
    outcome_sha256s: list[str]
    stop_sha256: str | None
    evidence_manifest_sha256: str
    status: Literal["no_pilot_data", "follow_up_incomplete", "ready_for_human_review"]
    external_clinical_review_required: Literal[True] = True
    is_effectiveness_conclusion: Literal[False] = False
    authorizes_expansion: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
