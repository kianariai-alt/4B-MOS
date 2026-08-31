from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


FlagSeverity = Literal[
    "info",
    "attention",
]


class PatientIdentitySummary(BaseModel):
    id: str
    patient_code: str
    first_name: str
    last_name: str
    date_of_birth: date | None
    is_active: bool


class LatestVisitSummary(BaseModel):
    id: str
    visit_date: datetime
    status: str
    body_region: str | None


class ActiveTreatmentSummary(BaseModel):
    id: str
    treatment_type: str
    status: str
    body_region: str | None
    protocol_name: str | None
    protocol_version: str | None
    created_at: datetime


class SessionSummary(BaseModel):
    id: str
    treatment_id: str
    treatment_type: str
    session_number: int
    status: str

    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None

    body_region: str | None


class OperationalFlag(BaseModel):
    code: str
    severity: FlagSeverity
    message: str
    count: int | None = None


class PatientClinicalSummaryResponse(
    BaseModel
):
    patient: PatientIdentitySummary

    total_visits: int
    open_visit_count: int

    total_treatments: int
    active_treatment_count: int
    completed_treatment_count: int

    total_sessions: int
    completed_session_count: int

    overdue_planned_session_count: int
    sessions_with_adverse_events: int

    treatment_status_counts: dict[str, int]
    treatment_type_counts: dict[str, int]

    latest_visit: (
        LatestVisitSummary | None
    )

    active_treatments: list[
        ActiveTreatmentSummary
    ]

    next_scheduled_session: (
        SessionSummary | None
    )

    last_completed_session: (
        SessionSummary | None
    )

    operational_flags: list[
        OperationalFlag
    ]