from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


SessionActionCode = Literal[
    "check_in",
    "mark_ready",
    "start_treatment",
    "complete",
    "discharge",
    "cancel",
]


class SessionWorklistAction(BaseModel):
    code: SessionActionCode
    target_status: str
    label: str
    is_primary: bool


class SessionWorklistItem(BaseModel):
    session_id: str
    treatment_id: str
    visit_id: str

    patient_id: str
    patient_code: str
    patient_name: str

    treatment_type: str
    session_number: int

    status: str
    operational_status: str

    scheduled_at: datetime | None

    body_region: str | None
    dose_or_volume: str | None

    is_overdue: bool
    has_documented_adverse_event: bool

    allowed_actions: list[
        SessionWorklistAction
    ]


class SessionWorklistResponse(BaseModel):
    generated_at: datetime
    clinic_timezone: str
    local_date: date
    horizon_days: int

    today_count: int
    today_overdue_count: int
    overdue_count: int
    upcoming_count: int
    unscheduled_count: int

    today: list[SessionWorklistItem]
    overdue: list[SessionWorklistItem]
    upcoming: list[SessionWorklistItem]
    unscheduled: list[SessionWorklistItem]