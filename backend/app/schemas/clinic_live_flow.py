from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from backend.app.schemas.session_worklist import (
    SessionWorklistAction,
)


ClinicPriorityLevel = Literal[
    "normal",
    "attention",
    "urgent",
]

ClinicAlertSeverity = Literal[
    "attention",
    "urgent",
]


class ClinicFlowAlert(BaseModel):
    code: str
    severity: ClinicAlertSeverity
    message: str


class ClinicLiveFlowItem(BaseModel):
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
    checked_in_at: datetime | None
    ready_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None

    scheduled_delay_minutes: int | None
    waiting_minutes: int | None
    ready_wait_minutes: int | None
    treatment_minutes: int | None
    discharge_wait_minutes: int | None

    priority_level: ClinicPriorityLevel
    priority_score: int
    is_attention_required: bool

    alerts: list[ClinicFlowAlert]

    allowed_actions: list[
        SessionWorklistAction
    ]


class ClinicLiveFlowResponse(BaseModel):
    generated_at: datetime
    clinic_timezone: str
    local_date: date

    scheduled_count: int
    checked_in_count: int
    ready_count: int
    in_treatment_count: int
    awaiting_discharge_count: int
    active_count: int

    attention_count: int
    urgent_count: int
    alert_count: int

    scheduled: list[ClinicLiveFlowItem]
    checked_in: list[ClinicLiveFlowItem]
    ready: list[ClinicLiveFlowItem]
    in_treatment: list[ClinicLiveFlowItem]
    awaiting_discharge: list[
        ClinicLiveFlowItem
    ]