from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AmendmentType = Literal["correction", "supplement"]
AmendmentReasonCode = Literal[
    "data_entry_error",
    "omitted_information",
    "clinical_clarification",
    "late_result",
    "other",
]
AmendmentDecision = Literal["approved", "rejected"]
AmendmentStatus = Literal["pending", "approved", "rejected"]


class SessionAmendmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amendment_type: AmendmentType
    reason_code: AmendmentReasonCode
    reason_detail: str = Field(min_length=1, max_length=2000)
    statement: str = Field(min_length=1, max_length=10000)
    target_reference: str | None = Field(default=None, max_length=200)

    @field_validator("reason_detail", "statement")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must not be blank.")
        return value

    @field_validator("target_reference")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("target_reference must not be blank when provided.")
        return value

    @model_validator(mode="after")
    def correction_requires_target_reference(self):
        if self.amendment_type == "correction" and self.target_reference is None:
            raise ValueError("A correction requires target_reference.")
        return self


class SessionAmendmentReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: AmendmentDecision
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def rejection_requires_comment(self):
        if self.decision == "rejected" and self.comment is None:
            raise ValueError("A rejection comment is required.")
        return self


class AmendmentActorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_user_id: str
    actor_username: str
    actor_display_name: str
    actor_role: str


class SessionAmendmentPayloadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str
    session_id: str
    sequence: int
    finalization_sha256: str
    amendment_type: AmendmentType
    reason_code: AmendmentReasonCode
    reason_detail: str
    statement: str
    target_reference: str | None
    author: AmendmentActorSnapshot
    created_at: str


class SessionAmendmentReviewPayloadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    amendment_id: str
    session_id: str
    amendment_sha256: str
    decision: AmendmentDecision
    comment: str | None
    reviewer: AmendmentActorSnapshot
    reviewed_at: str


class SessionAmendmentReviewRead(BaseModel):
    amendment_id: str
    decision: AmendmentDecision
    reviewed_at: datetime
    sha256: str
    payload: SessionAmendmentReviewPayloadRead


class SessionAmendmentRead(BaseModel):
    id: str
    session_id: str
    sequence: int
    status: AmendmentStatus
    created_at: datetime
    sha256: str
    payload: SessionAmendmentPayloadRead
    review: SessionAmendmentReviewRead | None
