from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.clinical_context import ClinicalContextSnapshotRead
from backend.app.schemas.clinical_evidence import ClinicalEvidenceBriefRead
from backend.app.schemas.clinical_safety_review import (
    SafetyInboxFindingRead,
    SafetyInboxRead,
)


class PhysicianCopilotManifestRead(BaseModel):
    clinical_context_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    safety_evaluation_result_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    open_escalation_review_sha256s: list[str]
    evidence_brief_sha256s: list[str]


class PhysicianCopilotSnapshotRead(BaseModel):
    visit_id: str
    generated_at: datetime
    clinical_context: ClinicalContextSnapshotRead
    safety_inbox: SafetyInboxRead
    open_escalations: list[SafetyInboxFindingRead]
    evidence_briefs: list[ClinicalEvidenceBriefRead]
    current_context_evidence_briefs: list[ClinicalEvidenceBriefRead]
    manifest: PhysicianCopilotManifestRead
    snapshot_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    open_escalation_scope: Literal[
        "latest_safety_evaluation_for_visit"
    ] = "latest_safety_evaluation_for_visit"
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    ranks_treatments: Literal[False] = False
    provides_risk_score: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    requires_independent_review: Literal[True] = True
