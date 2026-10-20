"""Immutable, privacy-minimal contracts for data validation, not diagnosis.

These contracts are internal. A trusted caller must establish review authority
before setting a finding's review status. They are not HTTP request schemas.
"""

from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class ClinicalInput:
    """Presence of controlled clinical fields; never clinical narrative or PHI."""

    available_fields: tuple[str, ...] = ()
    body_region: str | None = None
    laterality: str | None = None


@dataclass(frozen=True)
class ImagingInput:
    """Projection of a sanitized metadata reader result, without raw DICOM UIDs."""

    metadata_status: str
    metadata_sha256: str
    metadata_schema_version: str = "imaging-metadata-v1"
    modality: str | None = None
    body_region: str | None = None
    laterality: str | None = None
    study_reference: str | None = None
    series_reference: str | None = None
    instance_reference: str | None = None
    technical_fields: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FindingProvenance:
    source_instance_reference: str | None = None
    source_metadata_sha256: str | None = None
    source_metadata_schema_version: str | None = None
    review_record_reference: str | None = None
    review_policy_version: str | None = None


@dataclass(frozen=True)
class FindingInput:
    """A coded finding. Codes are never copied to the result or interpreted."""

    finding_reference: str
    finding_code: str
    review_status: str = "unverified"
    provenance: FindingProvenance | None = None


@dataclass(frozen=True)
class ValidationRequest:
    clinical: ClinicalInput
    imaging: ImagingInput | None = None
    findings: tuple[FindingInput, ...] = ()


@dataclass(frozen=True)
class EvaluationRequirements:
    """A versioned, trusted data contract, never an imaging-order policy.

    Defaults intentionally do not require pixel data: phase one reads metadata.
    A caller can require particular metadata fields for a later processor.
    """

    policy_version: str = "data-requirements-v1"
    required_clinical_fields: tuple[str, ...] = (
        "assessment_context", "clinical_review"
    )
    require_imaging: bool = True
    required_imaging_fields: tuple[str, ...] = (
        "modality", "study_reference", "series_reference", "instance_reference"
    )
    required_technical_fields: tuple[str, ...] = ()
    expected_modality: str | None = None
    expected_body_region: str | None = None
    expected_laterality: str | None = None
    metadata_schema_version: str = "imaging-metadata-v1"
    review_policy_version: str = "finding-review-v1"
    minimum_verified_findings: int = 0


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    rule_version: str
    outcome: str
    codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FindingValidation:
    """Per-finding check outcomes; only an opaque reference may be echoed."""

    finding_reference: str
    eligible: bool
    verification_codes: tuple[str, ...] = ()
    provenance_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    """data_ready means input readiness only; never a clinical recommendation."""

    status: str
    adapter_id: str
    adapter_version: str
    policy_version: str
    input_sha256: str | None
    rules_sha256: str
    result_sha256: str
    traces: tuple[RuleTrace, ...]
    missing_clinical_fields: tuple[str, ...] = ()
    missing_imaging_fields: tuple[str, ...] = ()
    eligible_finding_references: tuple[str, ...] = ()
    blocked_finding_references: tuple[str, ...] = ()
    finding_checks: tuple[FindingValidation, ...] = ()
    next_steps: tuple[str, ...] = ()
    scope: str = "data_validation_only"
    is_diagnosis: bool = False
    is_treatment_recommendation: bool = False

    def to_dict(self) -> dict:
        """JSON-serializable representation; contains no narratives or raw UIDs."""
        return asdict(self)


class DecisionModelAdapter(Protocol):
    """Implementations may validate data; they must not bypass safety services."""

    adapter_id: str
    adapter_version: str

    def evaluate(self, request: ValidationRequest) -> ValidationResult:
        ...
