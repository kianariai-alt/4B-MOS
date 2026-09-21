from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.clinical_safety import (
    SafetyEvaluationRead,
    SafetyFindingRead,
)


SafetyFindingReviewAction = Literal["acknowledged", "escalated", "assessed"]
SafetyFindingReviewDisposition = Literal[
    "requires_action",
    "not_applicable",
    "action_documented",
    "monitoring",
]
SafetyFindingReviewReason = Literal[
    "clinical_context",
    "measurement_quality",
    "rule_scope",
    "patient_specific_factor",
    "action_taken",
    "other",
]
SafetyFindingReviewStatus = Literal[
    "unreviewed",
    "acknowledged",
    "escalated",
    "assessed",
]


class SafetyFindingReviewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: SafetyFindingReviewAction
    expected_evaluation_result_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    disposition: SafetyFindingReviewDisposition | None = None
    reason_code: SafetyFindingReviewReason | None = None
    note: str | None = Field(default=None, max_length=5000)

    @field_validator("note", mode="after")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == "assessed":
            if self.disposition is None:
                raise ValueError("An assessed finding requires a disposition.")
            if self.reason_code is None:
                raise ValueError("An assessed finding requires a reason_code.")
            if self.note is None:
                raise ValueError("An assessed finding requires a note.")
            return self
        if self.disposition is not None or self.reason_code is not None:
            raise ValueError(
                "disposition and reason_code are only valid for assessed findings."
            )
        if self.action == "escalated" and self.note is None:
            raise ValueError("An escalated finding requires a note.")
        return self


class SafetyReviewActorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_user_id: str
    actor_username: str
    actor_display_name: str
    actor_role: str


class SafetyFindingReviewPayloadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str
    visit_id: str
    evaluation_id: str
    evaluation_result_sha256: str
    finding_id: str
    rule_id: str
    rule_content_sha256: str
    sequence: int
    previous_review_sha256: str | None
    action: SafetyFindingReviewAction
    disposition: SafetyFindingReviewDisposition | None
    reason_code: SafetyFindingReviewReason | None
    note: str | None
    actor: SafetyReviewActorSnapshot
    created_at: str


class SafetyFindingReviewRead(BaseModel):
    id: str
    finding_id: str
    sequence: int
    action: SafetyFindingReviewAction
    disposition: SafetyFindingReviewDisposition | None
    created_by_user_id: str
    evaluation_result_sha256: str
    rule_content_sha256: str
    previous_review_sha256: str | None
    sha256: str
    created_at: datetime
    payload: SafetyFindingReviewPayloadRead
    changes_evaluation_result: Literal[False] = False
    is_clinical_clearance: Literal[False] = False


class SafetyFindingReviewTimelineRead(BaseModel):
    visit_id: str
    evaluation_id: str
    evaluation_result_sha256: str
    finding_id: str
    rule_id: str
    rule_key: str
    rule_version: int
    severity: Literal["info", "warning", "high", "critical"]
    required_action: Literal[
        "document",
        "review_before_proceeding",
        "urgent_clinical_review",
    ]
    review_status: SafetyFindingReviewStatus
    reviews: list[SafetyFindingReviewRead]
    changes_evaluation_result: Literal[False] = False
    is_clinical_clearance: Literal[False] = False


class SafetyInboxFindingRead(BaseModel):
    finding: SafetyFindingRead
    timeline: SafetyFindingReviewTimelineRead


class SafetyInboxRead(BaseModel):
    visit_id: str
    current_clinical_context_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    evaluation_matches_current_context: bool | None
    evaluation: SafetyEvaluationRead | None
    findings: list[SafetyInboxFindingRead]
    is_clinical_clearance: Literal[False] = False
