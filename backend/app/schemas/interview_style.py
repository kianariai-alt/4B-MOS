"""Approved physician workflow context; no trained diagnostic model."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.physician_copilot import PhysicianCopilotSnapshotRead
from backend.app.schemas.physician_questions import BankContent


class ApprovedInterviewStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visit_id: str
    physician_id: str
    has_approved_bank: bool
    bank_id: str | None
    bank_sha256: str | None
    bank_version: int | None
    bank: BankContent | None
    learning_source_packet_id: str | None = None
    style_sha256: str
    source_policy: Literal["explicitly_approved_physician_bank_only"] = "explicitly_approved_physician_bank_only"
    model_weights_trained: Literal[False] = False
    authorizes_diagnosis: Literal[False] = False
    medical_knowledge_changed: Literal[False] = False


class PhysicianCopilotWithInterviewStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clinical_snapshot: PhysicianCopilotSnapshotRead
    interview_style: ApprovedInterviewStyle
    result_sha256: str
    is_diagnosis: Literal[False] = False
    model_weights_trained: Literal[False] = False
