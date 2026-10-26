"""Draft, explanatory knee differentials; no diagnostic probability or order."""
from typing import Literal

from pydantic import Field, field_validator

from backend.app.schemas.medical_knowledge import KnowledgeFactCreate
from backend.app.schemas.orthopedic_interview_tree import DraftTreeModel
from backend.app.schemas.orthopedic_knowledge import Digest, SourceEntry


class AssessmentConsideration(DraftTreeModel):
    id: str
    label_fa: str
    supporting_findings_fa: tuple[str, ...]
    limitations_fa: tuple[str, ...]
    information_gaps_fa: tuple[str, ...]
    assessment_requirements_fa: tuple[str, ...]
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    source_keys: tuple[str, ...]
    is_ranked: Literal[False] = False
    compatibility: Literal["authored_pattern_for_review", "documented_finding_for_review", "urgent_context_for_review"]


class ConditionalTreatmentEvidence(DraftTreeModel):
    id: str
    label_fa: str
    summary_fa: str
    conditions_fa: tuple[str, ...]
    limitations_fa: tuple[str, ...]
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    source_keys: tuple[str, ...]
    requires_card_id: str = "knee_oa"
    required_workflow_status: Literal["ready"] = "ready"
    is_personalized_plan: Literal[False] = False


class AssessmentDraftProposal(DraftTreeModel):
    fact: KnowledgeFactCreate
    version: Literal[1] = 1
    content_sha256: Digest


class KneeAssessmentPreview(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-assessment-preview"] = "4b-mos.knee-assessment-preview"
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["differential_review", "insufficient_information", "prompt_physician_review", "outside_scope", "side_specific_review"]
    headline_fa: str
    considerations: tuple[AssessmentConsideration, ...]
    urgent_considerations: tuple[AssessmentConsideration, ...]
    information_requirements_fa: tuple[str, ...]
    conditional_treatment_evidence: tuple[ConditionalTreatmentEvidence, ...]
    review_reasons_fa: tuple[str, ...]
    source_references: tuple[SourceEntry, ...]
    new_draft_proposals: tuple[AssessmentDraftProposal, ...]
    axis_tokens: dict[str, str]
    lookup_model_sha256: Digest
    preview_sha256: Digest
    request_sha256: Digest
    rules_sha256: Digest
    result_sha256: Digest
    approved_fact_count: Literal[0] = 0
    review_only: Literal[True] = True
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    registry_write_performed: Literal[False] = False
    safety_engine_required: Literal[True] = True
    safety_evaluation: Literal["not_performed"] = "not_performed"

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("Assessment authoring has no approved knowledge.")
        return value

    @field_validator("review_only", "is_diagnosis", "is_recommendation", "is_clinical_clearance",
                     "authorizes_treatment", "registry_write_performed", "safety_engine_required", mode="before")
    @classmethod
    def exact_flags(cls, value, info):
        expected = info.field_name in {"review_only", "safety_engine_required"}
        if type(value) is not bool or value is not expected:
            raise ValueError("Draft governance flags require exact JSON booleans.")
        return value
