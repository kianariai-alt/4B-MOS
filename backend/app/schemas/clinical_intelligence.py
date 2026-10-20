"""Read-only integration view; internal FHIR-inspired references, not FHIR."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from backend.app.schemas.clinical_decision_exchange import DecisionModelReference
from backend.app.schemas.clinical_integration import (
    ComponentVersion, ContractModel, DecisionSupportResult, Digest, Identifier,
)

ClinicalReviewStatus = Literal["verified", "unverified", "rejected", "invalid"]


class ClinicalCaseReference(ContractModel):
    visit_id: Identifier
    clinical_context_sha256: Digest


class SafetyEvaluationReference(ContractModel):
    evaluation_id: Identifier
    result_sha256: Digest
    clinical_context_sha256: Digest
    rule_set_sha256: Digest
    engine_version: Identifier
    created_at: AwareDatetime


class SafetyAlertReference(ContractModel):
    finding_id: Identifier
    rule_id: Identifier
    rule_version: int = Field(ge=1)
    rule_content_sha256: Digest
    severity: Literal["info", "warning", "high", "critical"]
    required_action: Literal["document", "review_before_proceeding", "urgent_clinical_review"]
    review_status: Literal["unreviewed", "acknowledged", "escalated", "assessed"]


class ClinicalSafetyStatus(ContractModel):
    status: Literal["missing", "stale", "alerts_present", "no_alerts", "no_active_rules"]
    evaluation: SafetyEvaluationReference | None = None
    alerts: tuple[SafetyAlertReference, ...] = ()
    evaluated_rule_count: int = Field(default=0, ge=0)
    open_escalation_count: int = Field(default=0, ge=0)
    is_clinical_clearance: Literal[False] = False

    @model_validator(mode="after")
    def evaluation_required(self):
        if (self.status == "missing") != (self.evaluation is None):
            raise ValueError("Safety status must reference the observed evaluation.")
        if self.status in {"no_alerts", "no_active_rules"} and (self.alerts or self.open_escalation_count):
            raise ValueError("Safety alerts cannot be represented as an alert-free evaluation.")
        return self


class ImagingReviewReference(ContractModel):
    """Review of a local report, not of DICOM identity or model interpretation.

    entered_in_error maps to rejected source; superseded maps to invalid for
    current use. Neither mapping claims a radiologist reviewed an AI model.
    """

    report_id: Identifier
    version: int = Field(ge=1)
    content_sha256: Digest
    source_status: Literal["draft", "final", "superseded", "entered_in_error"]
    review_status: ClinicalReviewStatus
    physician_user_id: Identifier | None = None
    reviewed_at: AwareDatetime | None = None
    review_scope: Literal["source_record_finalization"] = "source_record_finalization"
    eligible_as_current_source: bool
    dicom_identity_verified: Literal[False] = False

    @model_validator(mode="after")
    def review_consistent(self):
        verified = self.review_status == "verified"
        if verified != self.eligible_as_current_source:
            raise ValueError("Only verified reports can be eligible.")
        if verified and (self.source_status != "final" or not self.physician_user_id or not self.reviewed_at):
            raise ValueError("Verified reports require server-owned physician finalization.")
        expected = {"draft": "unverified", "superseded": "invalid", "entered_in_error": "rejected"}
        if self.source_status in expected and self.review_status != expected[self.source_status]:
            raise ValueError("Review state does not match source lifecycle.")
        if self.source_status == "final" and self.review_status not in {"verified", "unverified"}:
            raise ValueError("Final source requires a review attribution status.")
        return self


class ProvenanceManifest(ContractModel):
    """Opaque dependency digests only; no patient IDs, text or source URLs."""

    engine_version: Identifier
    clinical_context_sha256: Digest
    copilot_snapshot_sha256: Digest
    safety_rule_set_sha256: Digest
    safety_evaluation_sha256: Digest | None
    components: tuple[ComponentVersion, ...]
    core_semantic_sha256s: tuple[Digest, ...]
    knowledge_sha256s: tuple[Digest, ...]
    imaging_review_sha256: Digest
    decision_reference_sha256: Digest
    manifest_sha256: Digest


class IntegratedClinicalSnapshot(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["imaging_unavailable", "degraded", "awaiting_physician_review"]
    clinical_context_reference: ClinicalCaseReference
    result: DecisionSupportResult
    imaging_review: tuple[ImagingReviewReference, ...]
    decision_model_reference: DecisionModelReference
    safety_status: ClinicalSafetyStatus
    review_requirements: tuple[Identifier, ...]
    data_limitations: tuple[Identifier, ...]
    provenance_manifest: ProvenanceManifest
    observed_at: AwareDatetime
    snapshot_sha256: Digest
    hash_scope: Literal["clinical-intelligence-semantic-v1"] = "clinical-intelligence-semantic-v1"
    review_status: Literal["requires_physician_review"] = "requires_physician_review"
    is_diagnosis: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
