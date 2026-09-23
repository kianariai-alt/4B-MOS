from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PilotReadinessCheckRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pass", "fail", "blocked"]
    code: str


class PilotManualGateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["manual_required"]
    code: str


class ControlledPilotReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["automated_prerequisites_passed", "blocked"]
    generated_at: datetime
    application: str
    version: str
    database_dialect: str
    readiness_sha256: str
    automated_checks: list[PilotReadinessCheckRead]
    manual_gates: list[PilotManualGateRead]
    warnings: list[str]
    controlled_pilot_authorized: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    requires_human_release_decision: Literal[True] = True
