from datetime import datetime
from typing import Literal

from pydantic import BaseModel


DashboardFlagSeverity = Literal[
    "info",
    "attention",
]


class DashboardOperationalFlag(
    BaseModel
):
    code: str
    severity: DashboardFlagSeverity
    message: str
    count: int | None = None


class OperationsDashboardResponse(
    BaseModel
):
    generated_at: datetime
    clinic_timezone: str

    total_patients: int
    active_patient_count: int
    inactive_patient_count: int

    total_visits: int
    open_visit_count: int

    total_treatments: int
    active_treatment_count: int
    completed_treatment_count: int

    treatment_type_counts: dict[str, int]
    treatment_status_counts: dict[str, int]

    total_sessions: int
    session_status_counts: dict[str, int]

    sessions_scheduled_today: int
    upcoming_planned_sessions: int
    overdue_planned_sessions: int

    sessions_with_adverse_events: int

    audit_events_last_24h: int
    audit_event_type_counts: dict[str, int]

    operational_flags: list[
        DashboardOperationalFlag
    ]