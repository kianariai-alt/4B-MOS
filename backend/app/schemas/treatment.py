from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TreatmentType = Literal[
    "PRP",
    "PRGF",
    "ACS",
    "PL",
    "SVF",
    "EXOSOME",
]

TreatmentStatus = Literal[
    "planned",
    "in_progress",
    "completed",
    "cancelled",
]


class TreatmentCreate(BaseModel):
    treatment_type: TreatmentType

    session_number: int = Field(
        default=1,
        ge=1,
    )

    body_region: str | None = Field(
        default=None,
        max_length=100,
    )

    protocol_name: str | None = Field(
        default=None,
        max_length=200,
    )

    dose_or_volume: str | None = Field(
        default=None,
        max_length=100,
    )

    notes: str | None = Field(
        default=None,
        max_length=5000,
    )


class TreatmentUpdate(BaseModel):
    status: TreatmentStatus | None = None

    session_number: int | None = Field(
        default=None,
        ge=1,
    )

    body_region: str | None = Field(
        default=None,
        max_length=100,
    )

    protocol_name: str | None = Field(
        default=None,
        max_length=200,
    )

    dose_or_volume: str | None = Field(
        default=None,
        max_length=100,
    )

    notes: str | None = Field(
        default=None,
        max_length=5000,
    )

    performed_at: datetime | None = None


class TreatmentRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    visit_id: str
    treatment_type: str
    status: str
    session_number: int
    body_region: str | None
    protocol_name: str | None
    dose_or_volume: str | None
    notes: str | None
    performed_at: datetime | None
    created_at: datetime
    updated_at: datetime