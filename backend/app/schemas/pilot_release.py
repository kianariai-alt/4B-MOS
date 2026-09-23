from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PilotManualGateName = Literal[
    "clinical_protocol_signoff",
    "clinical_safety_signoff",
    "backup_restore",
    "security_perimeter",
    "monitoring_alerting",
    "human_ui_acceptance",
    "privacy_retention_legal",
]


class PilotManualGateAttestationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_name: PilotManualGateName
    expected_readiness_sha256: str = Field(min_length=64, max_length=64)
    release_ref: str = Field(min_length=1, max_length=200)
    evidence_reference: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=20, max_length=5000)
    supersedes_attestation_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
    )
    expected_supersedes_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )

    @field_validator(
        "expected_readiness_sha256",
        "expected_supersedes_sha256",
    )
    @classmethod
    def validate_sha256(cls, value):
        if value is None:
            return value
        if any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("Expected a hexadecimal SHA-256 value.")
        return value.lower()


class PilotManualGateReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_attestation_sha256: str = Field(min_length=64, max_length=64)
    action: Literal["approve", "reject"]
    rationale: str = Field(min_length=10, max_length=5000)

    @field_validator("expected_attestation_sha256")
    @classmethod
    def validate_sha256(cls, value):
        if any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("Expected a hexadecimal SHA-256 value.")
        return value.lower()


class PilotManualGateReviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    attestation_id: str
    attestation_sha256: str
    action: Literal["approve", "reject"]
    rationale: str
    reviewed_by_user_id: str
    reviewed_by_role: str
    sha256: str
    created_at: datetime


class PilotManualGateAttestationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    gate_name: PilotManualGateName
    readiness_sha256: str
    generation: int
    release_ref: str
    evidence_reference: str
    statement: str
    supersedes_attestation_id: str | None
    attested_by_user_id: str
    attested_by_role: str
    sha256: str
    created_at: datetime
    status: Literal["pending_review", "approved", "rejected"]
    review: PilotManualGateReviewRead | None = None
    append_only: Literal[True] = True
    independent_review_required: Literal[True] = True
    is_clinical_clearance: Literal[False] = False
    controlled_pilot_authorized: Literal[False] = False


class PilotManualGateStatusRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_name: PilotManualGateName
    latest_attestation: PilotManualGateAttestationRead | None
    status: Literal[
        "not_attested",
        "pending_review",
        "approved",
        "rejected",
    ]



class PilotLaunchManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_name: PilotManualGateName
    generation: int
    attestation_id: str
    attestation_sha256: str
    review_id: str
    review_sha256: str


class PilotLaunchPackagePreviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["packageable", "blocked"]
    readiness_sha256: str
    release_ref: str | None
    approved_gate_count: int
    required_gate_count: Literal[7] = 7
    issues: list[str]
    attestation_manifest: list[PilotLaunchManifestItem]
    controlled_pilot_authorized: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    requires_human_release_decision: Literal[True] = True


class PilotLaunchPackageExpectedAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_name: PilotManualGateName
    attestation_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("attestation_sha256")
    @classmethod
    def validate_sha256(cls, value):
        if any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("Expected a hexadecimal SHA-256 value.")
        return value.lower()


class PilotLaunchPackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_readiness_sha256: str = Field(min_length=64, max_length=64)
    expected_release_ref: str = Field(min_length=1, max_length=200)
    expected_attestations: list[PilotLaunchPackageExpectedAttestation] = Field(
        min_length=7,
        max_length=7,
    )

    @field_validator("expected_readiness_sha256")
    @classmethod
    def validate_sha256(cls, value):
        if any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("Expected a hexadecimal SHA-256 value.")
        return value.lower()


class PilotLaunchPackageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    release_ref: str
    readiness_sha256: str
    attestation_manifest: list[PilotLaunchManifestItem]
    created_by_user_id: str
    sha256: str
    created_at: datetime
    append_only: Literal[True] = True
    controlled_pilot_authorized: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    requires_human_release_decision: Literal[True] = True
