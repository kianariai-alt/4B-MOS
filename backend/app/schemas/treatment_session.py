from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


TreatmentSessionStatus = Literal[
    "planned",
    "in_progress",
    "completed",
    "cancelled",
]


class TreatmentSessionCreate(BaseModel):
    session_number: int = Field(
        ge=1,
    )

    status: TreatmentSessionStatus = (
        "planned"
    )

    scheduled_at: datetime | None = None

    body_region: str | None = Field(
        default=None,
        max_length=100,
    )

    dose_or_volume: str | None = Field(
        default=None,
        max_length=100,
    )

    execution_parameters: (
        dict | None
    ) = None

    outcome_summary: str | None = None
    adverse_events: str | None = None
    notes: str | None = None


class TreatmentSessionUpdate(BaseModel):
    session_number: int | None = Field(
        default=None,
        ge=1,
    )

    status: (
        TreatmentSessionStatus | None
    ) = None

    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    body_region: str | None = Field(
        default=None,
        max_length=100,
    )

    dose_or_volume: str | None = Field(
        default=None,
        max_length=100,
    )

    execution_parameters: (
        dict | None
    ) = None

    outcome_summary: str | None = None
    adverse_events: str | None = None
    notes: str | None = None


class TreatmentSessionRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    treatment_id: str

    session_number: int

    status: str
    operational_status: str

    scheduled_at: datetime | None
    checked_in_at: datetime | None
    ready_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    discharged_at: datetime | None

    body_region: str | None
    dose_or_volume: str | None

    execution_parameters: dict | None

    outcome_summary: str | None
    adverse_events: str | None
    notes: str | None

    created_at: datetime
    updated_at: datetime