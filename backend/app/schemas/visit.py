from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VisitStatus = Literal[
    "open",
    "completed",
    "cancelled",
]


class VisitCreate(BaseModel):
    chief_complaint: str | None = Field(
        default=None,
        max_length=2000,
    )

    body_region: str | None = Field(
        default=None,
        max_length=100,
    )

    diagnosis: str | None = Field(
        default=None,
        max_length=2000,
    )

    notes: str | None = Field(
        default=None,
        max_length=5000,
    )


class VisitUpdate(BaseModel):
    status: VisitStatus | None = None

    chief_complaint: str | None = Field(
        default=None,
        max_length=2000,
    )

    body_region: str | None = Field(
        default=None,
        max_length=100,
    )

    diagnosis: str | None = Field(
        default=None,
        max_length=2000,
    )

    notes: str | None = Field(
        default=None,
        max_length=5000,
    )


class VisitRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    patient_id: str
    visit_date: datetime
    status: str
    chief_complaint: str | None
    body_region: str | None
    diagnosis: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime