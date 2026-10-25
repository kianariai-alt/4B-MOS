"""Patient-grounded audit view of Draft knee-pattern reasoning.

This contract describes which supplied data the current model used. It neither
extends medical compatibility rules nor turns a rule mismatch into exclusion.
"""
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator

from backend.app.schemas.orthopedic_assessment import KneeAssessmentPreview
from backend.app.schemas.orthopedic_interview_tree import DraftTreeModel
from backend.app.schemas.orthopedic_knowledge import Digest
from backend.app.schemas.orthopedic_questions import StrictPreview


class ReasoningObservation(StrictPreview):
    field: str
    label_fa: str
    value: StrictStr | StrictInt | StrictBool | None
    value_fa: str
    state: Literal["confirmed", "unverified", "incomplete", "contradictory", "unknown", "declined"]
    provenance: Literal["patient_report", "physician_exam", "reviewed_imaging", "unreviewed_imaging"]
    source_ref: str
    episode_ref: str | None = None
    usability: Literal["usable", "quarantined"]
    reason: str | None = None


class ReasoningTreatmentEpisode(StrictPreview):
    episode_ref: str
    observations: tuple[ReasoningObservation, ...]


class ClinicalProblemRepresentation(StrictPreview):
    body_region: Literal["knee", "other", "unknown"]
    summary_fa: str
    history: tuple[ReasoningObservation, ...]
    examination: tuple[ReasoningObservation, ...]
    imaging: tuple[ReasoningObservation, ...]
    treatment_episodes: tuple[ReasoningTreatmentEpisode, ...]
    inferred_demographics: Literal[False] = False


class ReasoningDataRequirement(DraftTreeModel):
    id: str
    category: Literal["workflow_prerequisite", "missing_current_field", "schema_coverage_gap", "physician_clinical_review"]
    field: str | None = None
    hypothesis_ids: tuple[str, ...] = ()
    reason_fa: str
    current_reason: str | None = None
    existing_question_id: str | None = None
    existing_question_number: int | None = None
    question_action: Literal["ask_missing", "physician_clarification", "not_automatically_reask", "physician_review", "schema_extension_review"]
    supported_by_current_context: bool
    source_fact_keys: tuple[str, ...] = ()
    source_content_sha256s: tuple[Digest, ...] = ()
    is_imaging_order: Literal[False] = False


class ReasoningCriterion(DraftTreeModel):
    axis_id: str
    field: str
    input_channel: Literal["usable_history", "usable_clinical"]
    observed_token: Literal["p", "n", "u"]
    expected_tokens: tuple[Literal["p", "n", "u"], ...]
    relation: Literal["matched", "mismatched", "unresolved"]
    explanation_fa: str
    observations: tuple[ReasoningObservation, ...]
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    is_diagnostic_criterion: Literal[False] = False
    is_clinical_exclusion: Literal[False] = False


class ReasoningHypothesisReview(DraftTreeModel):
    hypothesis_id: str
    label_fa: str
    status: Literal["matched_pattern", "pattern_not_matched", "information_missing", "withheld_by_workflow"]
    pattern_status: Literal["matched_pattern", "pattern_not_matched", "information_missing"]
    criteria: tuple[ReasoningCriterion, ...]
    patient_grounded_support_fa: tuple[str, ...]
    pattern_mismatches_fa: tuple[str, ...]
    schema_coverage_gaps: tuple[ReasoningDataRequirement, ...]
    limitations_fa: tuple[str, ...]
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    is_excluded: Literal[False] = False
    is_ranked: Literal[False] = False


class KneeReasoningReview(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-reasoning-review"] = "4b-mos.knee-reasoning-review"
    schema_version: Literal["1.0.0"] = "1.0.0"
    baseline_assessment: KneeAssessmentPreview
    problem_representation: ClinicalProblemRepresentation
    quarantined_observations: tuple[ReasoningObservation, ...]
    hypothesis_reviews: tuple[ReasoningHypothesisReview, ...] = Field(min_length=4, max_length=4)
    next_data_requirements: tuple[ReasoningDataRequirement, ...]
    clinical_findings_not_used_by_current_model: tuple[ReasoningObservation, ...]
    structural_limitations_fa: tuple[str, ...]
    request_sha256: Digest
    preview_sha256: Digest
    assessment_sha256: Digest
    lookup_model_sha256: Digest
    rules_sha256: Digest
    result_sha256: Digest
    review_only: Literal[True] = True
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinically_validated: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    registry_write_performed: Literal[False] = False
    safety_engine_required: Literal[True] = True
    safety_evaluation: Literal["not_performed"] = "not_performed"
    approved_fact_count: Literal[0] = 0

    @field_validator("review_only", "is_diagnosis", "is_recommendation", "is_clinically_validated",
                     "is_clinical_clearance", "authorizes_treatment", "registry_write_performed",
                     "safety_engine_required", mode="before")
    @classmethod
    def exact_flags(cls, value, info):
        expected = info.field_name in {"review_only", "safety_engine_required"}
        if type(value) is not bool or value is not expected:
            raise ValueError("Reasoning audit governance requires exact JSON booleans.")
        return value

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("Reasoning review never approves medical knowledge.")
        return value
