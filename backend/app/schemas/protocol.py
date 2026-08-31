from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProtocolTreatmentType = Literal[
    "PRP",
    "PRGF",
    "ACS",
    "PL",
    "SVF",
    "EXOSOME",
]


class ProtocolCreate(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=100,
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    treatment_type: ProtocolTreatmentType

    version: str = Field(
        default="1.0",
        min_length=1,
        max_length=30,
    )

    description: str | None = None

    preparation_parameters: dict | None = None
    administration_parameters: dict | None = None
    monitoring_parameters: dict | None = None


class ProtocolRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    code: str
    name: str
    treatment_type: str
    version: str
    description: str | None
    preparation_parameters: dict | None
    administration_parameters: dict | None
    monitoring_parameters: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime