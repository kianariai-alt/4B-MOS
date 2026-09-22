from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.protocol import ProtocolCreate, ProtocolRead


GovernanceSignal = Literal[
    "insufficient_outcome_volume",
    "limited_outcome_volume",
    "no_decision_linked_treatments",
    "patient_rating_incomplete",
    "physician_rating_incomplete",
    "pain_score_incomplete",
    "function_score_incomplete",
    "early_followup_gap",
    "intermediate_followup_gap",
    "long_term_followup_gap",
    "eligible_for_human_pattern_review",
]
GovernanceCaseType = Literal[
    "collect_more_data",
    "monitor_no_change",
    "revision_candidate",
    "deactivation_candidate",
    "reactivation_candidate",
    "rollback_revision_candidate",
]
GovernanceReviewAction = Literal[
    "clinical_approve",
    "clinical_reject",
    "request_changes",
    "operational_acknowledge",
    "operational_hold",
]


class ProtocolGovernanceSignalRead(BaseModel):
    protocol_code: str
    protocol_version: str
    protocol_name: str
    treatment_type: str
    is_active: bool
    data_volume: str
    signals: list[GovernanceSignal]
    source_learning_review_sha256: str
    system_recommends_protocol_change: Literal[False] = False
    requires_human_review: Literal[True] = True


class ProtocolGovernanceCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    protocol_code: str = Field(min_length=1, max_length=100)
    protocol_version: str = Field(min_length=1, max_length=30)
    source_learning_review_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    case_type: GovernanceCaseType
    rationale: str = Field(min_length=20, max_length=5000)
    evidence_needed: list[str] = Field(default_factory=list, max_length=20)
    proposed_protocol: ProtocolCreate | None = None

    @model_validator(mode="after")
    def validate_case(self):
        if self.case_type == "revision_candidate" and self.proposed_protocol is None:
            raise ValueError("revision_candidate requires proposed_protocol.")
        if self.case_type != "revision_candidate" and self.proposed_protocol is not None:
            raise ValueError("proposed_protocol is only valid for revision_candidate.")
        return self


class ProtocolGovernanceRecoveryCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_release_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_learning_review_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    rationale: str = Field(min_length=20, max_length=5000)
    evidence_needed: list[str] = Field(default_factory=list, max_length=20)


class ProtocolGovernanceReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_case_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    action: GovernanceReviewAction
    rationale: str = Field(min_length=10, max_length=5000)


class ProtocolGovernanceReviewRead(BaseModel):
    id: str
    case_id: str
    case_sha256: str
    action: GovernanceReviewAction
    rationale: str
    reviewer_user_id: str
    sha256: str
    created_at: datetime


class ProtocolGovernanceReleaseExecute(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_case_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    execution_note: str = Field(min_length=10, max_length=5000)


class ProtocolGovernanceReleaseRead(BaseModel):
    id: str
    case_id: str
    case_sha256: str
    action: Literal["publish_revision", "deactivate"]
    source_protocol_id: str
    released_protocol_id: str | None
    source_protocol_before: dict
    source_protocol_after: dict
    released_protocol_snapshot: dict | None
    executed_by_user_id: str
    execution_note: str
    sha256: str
    created_at: datetime
    is_rollback: Literal[False] = False
    preserves_history: Literal[True] = True


class ProtocolGovernanceRecoveryExecute(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_case_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    execution_note: str = Field(min_length=10, max_length=5000)


class ProtocolGovernanceRecoveryRead(BaseModel):
    id: str
    case_id: str
    case_sha256: str
    source_release_id: str
    source_release_sha256: str
    action: Literal["reactivate", "rollback_revision"]
    deactivated_protocol_id: str | None
    reactivated_protocol_id: str
    before_snapshots: dict
    after_snapshots: dict
    executed_by_user_id: str
    execution_note: str
    sha256: str
    created_at: datetime
    preserves_history: Literal[True] = True
    destructive_rollback: Literal[False] = False


class ProtocolGovernanceCaseRead(BaseModel):
    id: str
    protocol_code: str
    protocol_version: str
    treatment_type: str
    case_type: GovernanceCaseType
    source_learning_review_sha256: str
    protocol_snapshot: dict
    learning_snapshot: dict
    proposed_protocol: dict | None
    source_release_id: str | None = None
    source_release_sha256: str | None = None
    recovery_snapshot: dict | None = None
    rationale: str
    evidence_needed: list[str]
    created_by_user_id: str
    sha256: str
    created_at: datetime
    reviews: list[ProtocolGovernanceReviewRead]
    release: ProtocolGovernanceReleaseRead | None = None
    recovery: ProtocolGovernanceRecoveryRead | None = None
    status: Literal[
        "awaiting_clinical_review",
        "changes_requested",
        "clinically_rejected",
        "awaiting_operational_review",
        "operational_hold",
        "approved_for_manual_action",
        "released",
        "recovered",
    ]
    automatically_changes_protocol: Literal[False] = False
    requires_manual_protocol_action: bool



class ProtocolGovernanceLineageRead(BaseModel):
    protocol_code: str
    treatment_type: str
    versions: list[ProtocolRead]
    releases: list[ProtocolGovernanceReleaseRead]
    recoveries: list[ProtocolGovernanceRecoveryRead]
    active_protocol_ids: list[str]
    lineage_consistent: Literal[True] = True
    automatically_selects_protocol: Literal[False] = False
