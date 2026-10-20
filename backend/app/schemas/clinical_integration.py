"""Unified Clinical Data Contract 1.0.0 (internal, FHIR-inspired, not FHIR)."""

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.clinical_context import (
    ClinicalLaterality,
    ParaclinicalObservationInput,
)

CONTRACT_VERSION = "1.0.0"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=100)]
CoreName = Literal["orthopedic", "imaging"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class IntegrationObservation(ParaclinicalObservationInput):
    """Strict transport view of the existing typed observation contract.

    Existing local observation objects are copied through validation; unsupported
    producer fields must fail rather than silently lose quality or review data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def copy_local_observation(cls, value):
        if isinstance(value, ParaclinicalObservationInput):
            return value.model_dump()
        return value


class PatientReference(ContractModel):
    """Existing internal patient ID only; never sent to a core adapter."""

    patient_id: Identifier


class VisitReference(ContractModel):
    visit_id: Identifier
    status: Literal["open", "completed", "cancelled"]


class ComponentVersion(ContractModel):
    component_id: Identifier
    version: Identifier
    artifact_sha256: Digest
    kind: Literal["adapter", "model", "rule"]


class RecordReference(ContractModel):
    record_type: Literal["clinical_intake", "paraclinical_report"]
    record_id: Identifier
    version: int = Field(ge=1)
    content_sha256: Digest
    observation_id: Identifier | None = None
    field: Literal["exam_findings", "pain_score", "observation"]

    @model_validator(mode="after")
    def source_shape(self):
        if self.record_type == "clinical_intake":
            if self.field == "observation" or self.observation_id is not None:
                raise ValueError("Intake references must identify an allowed intake field.")
        elif self.field != "observation" or self.observation_id is None:
            raise ValueError("Report references must identify a structured observation.")
        return self


class ClinicalAssessmentReference(ContractModel):
    intake_id: Identifier
    version: int = Field(ge=1)
    content_sha256: Digest
    status: Literal["final"] = "final"
    body_region: str | None = None
    laterality: ClinicalLaterality | None = None


class ImagingStudyReference(ContractModel):
    """A local report proxy, not a claim of verified DICOM identity or modality."""

    report_id: Identifier
    version: int = Field(ge=1)
    content_sha256: Digest
    modality: Literal["unknown", "DX", "CR", "MR", "CT"] = "unknown"
    dicom_identity_verified: Literal[False] = False


class SourceObservation(ContractModel):
    source: RecordReference
    observation: IntegrationObservation


class CoreInput(ContractModel):
    """Minimum necessary local data. No demographics, URLs, or patient ID."""

    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    visit_id: Identifier
    clinical_context_sha256: Digest
    observations: tuple[SourceObservation, ...] = Field(max_length=1000)


class CoreFinding(ContractModel):
    finding_id: Identifier
    source: RecordReference
    observation: IntegrationObservation
    origin: Literal["record", "model"]
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def no_record_probability(self):
        if self.origin == "record" and self.confidence is not None:
            raise ValueError("A source-record finding cannot carry model confidence.")
        return self


class CoreOutput(ContractModel):
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    core: CoreName
    visit_id: Identifier
    clinical_context_sha256: Digest
    component: ComponentVersion
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    status: Literal["available", "missing", "unavailable"]
    findings: tuple[CoreFinding, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def envelope_shape(self):
        if self.valid_until <= self.generated_at:
            raise ValueError("Core validity must end after generation.")
        if self.status != "available" and self.findings:
            raise ValueError("An unavailable core cannot supply findings.")
        ids = [item.finding_id for item in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("Finding IDs must be unique within a core.")
        if any(item.origin == "model" for item in self.findings):
            if self.component.kind != "model":
                raise ValueError("Model findings require model provenance.")
        return self


class PhysicianApproval(ContractModel):
    """Source finalization attribution, checked against server records."""

    physician_user_id: Identifier
    reviewed_at: AwareDatetime
    scope: Literal["source_record_finalization"] = "source_record_finalization"


class IntegratedFinding(ContractModel):
    core: CoreName
    finding: CoreFinding
    review_status: Literal["confirmed_source", "unreviewed_model", "unreviewed_source"]
    approval: PhysicianApproval | None = None
    usable_as_confirmed_finding: bool

    @model_validator(mode="after")
    def review_matches_origin(self):
        if self.review_status == "confirmed_source":
            if (self.finding.origin != "record" or self.approval is None
                    or not self.usable_as_confirmed_finding):
                raise ValueError("Only physician-attributed source records can be confirmed.")
        else:
            expected = "unreviewed_model" if self.finding.origin == "model" else "unreviewed_source"
            if (self.review_status != expected or self.approval is not None
                    or self.usable_as_confirmed_finding):
                raise ValueError("Unreviewed findings cannot carry approval or confirmation.")
        return self


class KnowledgeReference(ContractModel):
    fact_id: Identifier
    fact_key: Identifier
    version: int = Field(ge=1)
    content_sha256: Digest
    evidence_grade: str
    source_ids: tuple[Identifier, ...]
    valid_from: date | None = None
    valid_to: date | None = None
    status: Literal["approved"] = "approved"
    applicability: Literal["not_assessed"] = "not_assessed"


class ClinicalEvidenceReference(ContractModel):
    brief_id: Identifier
    content_sha256: Digest
    clinical_context_sha256: Digest
    knowledge_set_sha256: Digest
    context_matches: bool
    knowledge_status: Literal["historical_snapshot_only"] = "historical_snapshot_only"


class IntegrationIssue(ContractModel):
    code: Identifier
    severity: Literal["warning", "blocking"]
    core: CoreName | None = None
    finding_ids: tuple[Identifier, ...] = ()
    source_references: tuple[RecordReference, ...] = ()


class Provenance(ContractModel):
    engine_version: Identifier
    clinical_context_sha256: Digest
    copilot_snapshot_sha256: Digest
    safety_rule_set_sha256: Digest
    components: tuple[ComponentVersion, ...]
    core_output_sha256s: tuple[Digest, ...]


class DecisionSupportResult(ContractModel):
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    patient: PatientReference
    visit: VisitReference
    assessment: ClinicalAssessmentReference | None
    imaging_studies: tuple[ImagingStudyReference, ...]
    raw_record_references: tuple[RecordReference, ...]
    confirmed_findings: tuple[IntegratedFinding, ...]
    unreviewed_findings: tuple[IntegratedFinding, ...]
    knowledge: tuple[KnowledgeReference, ...]
    evidence_briefs: tuple[ClinicalEvidenceReference, ...] = ()
    cores: tuple[CoreOutput, ...]
    issues: tuple[IntegrationIssue, ...]
    provenance: Provenance
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    workflow_state: Literal["blocked", "awaiting_physician_review"]
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    requires_independent_review: Literal[True] = True

    @model_validator(mode="after")
    def review_collections_are_consistent(self):
        if any(item.review_status != "confirmed_source" for item in self.confirmed_findings):
            raise ValueError("Confirmed findings must contain only confirmed source records.")
        if any(item.review_status == "confirmed_source" for item in self.unreviewed_findings):
            raise ValueError("Confirmed source records cannot be placed in unreviewed findings.")
        identities = [(item.core, item.finding.finding_id)
                      for item in self.confirmed_findings + self.unreviewed_findings]
        if len(identities) != len(set(identities)):
            raise ValueError("Integrated finding identities must be unique across review collections.")
        if self.workflow_state == "awaiting_physician_review" and (
            self.unreviewed_findings or any(issue.severity == "blocking" for issue in self.issues)
        ):
            raise ValueError("An incomplete or blocked result cannot be ready for summary approval.")
        return self


class IntegrationRunCreate(ContractModel):
    request_key: Identifier = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    expected_clinical_context_sha256: Digest
    knowledge_fact_ids: tuple[Identifier, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def unique_knowledge(self):
        if len(self.knowledge_fact_ids) != len(set(self.knowledge_fact_ids)):
            raise ValueError("Knowledge fact IDs must be unique.")
        return self


class IntegrationReviewCreate(ContractModel):
    request_key: Identifier = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    expected_result_sha256: Digest
    action: Literal["approve_summary", "reject", "defer", "request_revision"]
    rationale: str = Field(min_length=10, max_length=5000)


class PhysicianReview(ContractModel):
    id: Identifier
    run_id: Identifier
    visit_id: Identifier
    physician_user_id: Identifier
    result_sha256: Digest
    action: Literal["approve_summary", "reject", "defer", "request_revision"]
    rationale: str
    reviewed_at: AwareDatetime
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False


class IntegrationRunRead(ContractModel):
    id: Identifier
    result_sha256: Digest
    result: DecisionSupportResult
    freshness: Literal["current", "stale", "unverifiable"]
    invalidation_reasons: tuple[str, ...]
    reviews: tuple[PhysicianReview, ...]


class IntegrationRunSnapshot(ContractModel):
    id: Identifier
    request_sha256: Digest
    created_by_user_id: Identifier
    created_at: AwareDatetime
    result: DecisionSupportResult


class IntegrationAuditEvent(ContractModel):
    id: Identifier
    event_type: str
    actor_user_id: str | None
    created_at: AwareDatetime
    result_sha256: Digest


class IntegrationCopilotView(ContractModel):
    visit_id: Identifier
    copilot_snapshot_sha256: Digest
    clinical_context_sha256: Digest
    latest_run: IntegrationRunRead | None
    raw_data_location: Literal["existing_physician_copilot.clinical_context"] = (
        "existing_physician_copilot.clinical_context"
    )
    physician_decisions_location: Literal["existing_treatment_decisions_api"] = (
        "existing_treatment_decisions_api"
    )
    is_clinical_clearance: Literal[False] = False
