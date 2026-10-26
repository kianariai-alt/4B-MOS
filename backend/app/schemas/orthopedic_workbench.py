"""Additive Draft authoring contracts for a source-bound knee workbench.

The original interview and assessment contracts remain unchanged. Multi-choice
reports preserve every selection; examination is a separate physician channel.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from backend.app.schemas.orthopedic_assessment import AssessmentDraftProposal
from backend.app.schemas.orthopedic_interview_tree import (
    DraftTreeModel, KneeInterviewTreePreviewRequest, State,
)
from backend.app.schemas.orthopedic_knowledge import Digest, SourceEntry
from backend.app.schemas.orthopedic_questions import StrictPreview
from backend.app.schemas.orthopedic_reasoning_review import KneeReasoningReview


SUPPLEMENTAL_CHOICES = {
    "age_band": ("under_45", "45_or_over"),
    "morning_stiffness": ("none", "up_to_30_min", "over_30_min"),
    "exam_mcmurray": ("positive", "negative", "indeterminate"),
    "pain_locations": ("anterior", "medial", "lateral", "posterior", "diffuse"),
    "aggravating_activities": ("walking", "stairs", "loaded_flexion", "none", "other"),
    "care_goals": ("pain", "function", "activity", "decision_support"),
}
MULTI_FIELDS = {"pain_locations", "aggravating_activities", "care_goals"}
SupplementalField = Literal[
    "age_band", "morning_stiffness", "exam_squat_anterior_pain", "exam_mcmurray",
    "pain_locations", "aggravating_activities", "care_goals",
]


class SupplementalObservation(StrictPreview):
    field: SupplementalField
    state: State
    value: StrictStr | StrictBool | tuple[StrictStr, ...] | None = None
    provenance: Literal["patient_report", "physician_exam"]
    source_ref: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def strict_channel_and_value(self):
        channel = "physician_exam" if self.field.startswith("exam_") else "patient_report"
        if self.provenance != channel:
            raise ValueError("A patient report cannot supply a physician examination.")
        if self.state in {"unknown", "declined"} and self.value is not None:
            raise ValueError("Unknown or declined answers cannot carry selections.")
        if self.state in {"confirmed", "unverified"} and self.value is None:
            raise ValueError("A complete observation requires a typed value.")
        if self.value is not None:
            if self.field == "exam_squat_anterior_pain":
                valid = type(self.value) is bool
            elif self.field in MULTI_FIELDS:
                valid = (type(self.value) is tuple and 1 <= len(self.value) <= len(SUPPLEMENTAL_CHOICES[self.field])
                         and len(set(self.value)) == len(self.value)
                         and all(type(item) is str and item in SUPPLEMENTAL_CHOICES[self.field] for item in self.value)
                         and not ("none" in self.value and len(self.value) > 1))
            else:
                valid = type(self.value) is str and self.value in SUPPLEMENTAL_CHOICES[self.field]
            if not valid:
                raise ValueError("Observation does not match the declared field's controlled values.")
        return self


class KneeWorkbenchRequest(StrictPreview):
    interview: KneeInterviewTreePreviewRequest
    supplemental_observations: tuple[SupplementalObservation, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def unique_observation_sources(self):
        pairs = [(item.field, item.source_ref) for item in self.supplemental_observations]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Duplicate field/source pair; preserve revisions outside this request.")
        return self


class WorkbenchQuestion(StrictPreview):
    id: str
    field: str
    text_fa: str
    purpose_fa: str
    answer_type: Literal["text", "yes_no", "single_choice", "multi_choice"]
    choices: tuple[str, ...] = ()
    channel: Literal["patient_report", "physician_exam", "reviewed_imaging"]
    allow_unknown: Literal[True] = True
    allow_decline: Literal[True] = True


class WorkbenchObservation(StrictPreview):
    field: str
    value: StrictStr | StrictBool | StrictInt | tuple[StrictStr, ...] | None
    value_fa: str
    state: State
    provenance: Literal["patient_report", "physician_exam", "reviewed_imaging", "unreviewed_imaging"]
    source_ref: str
    usability: Literal["usable", "quarantined"]
    reason: str | None = None


class WorkbenchRelationship(DraftTreeModel):
    id: str
    field: str
    relation: Literal["supports", "discordant", "unavailable", "neutral"]
    explanation_fa: str
    observations: tuple[WorkbenchObservation, ...]
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    is_diagnostic_criterion: Literal[False] = False
    is_clinical_exclusion: Literal[False] = False

    @model_validator(mode="after")
    def bound_references(self):
        if not self.source_fact_keys or len(self.source_fact_keys) != len(self.source_content_sha256s):
            raise ValueError("Each clinical relationship must bind every referenced fact hash.")
        return self


class DifferentialComparison(DraftTreeModel):
    id: str
    label_fa: str
    status: Literal["evidence_for_physician_review", "information_missing", "withheld_by_workflow"]
    summary_fa: str
    relationships: tuple[WorkbenchRelationship, ...]
    limitations_fa: tuple[str, ...]
    is_ranked: Literal[False] = False
    is_excluded: Literal[False] = False
    diagnostic_probability: None = None


class WorkbenchNextItem(DraftTreeModel):
    id: str
    field: str | None = None
    episode_ref: str | None = None
    category: Literal["patient_question", "clinician_exam", "physician_review", "imaging_review"]
    action: Literal["ask_missing", "physician_clarification", "not_automatically_reask", "review_existing", "consider_examination"]
    question: WorkbenchQuestion | None = None
    reason_fa: str
    addresses_comparison_ids: tuple[str, ...] = ()
    source_fact_keys: tuple[str, ...] = ()
    source_content_sha256s: tuple[Digest, ...] = ()
    priority: Literal["workflow_first", "clarification", "discriminating_information", "context_review"]
    is_imaging_order: Literal[False] = False


class ManagementContextReview(StrictPreview):
    observations: tuple[WorkbenchObservation, ...]
    review_points_fa: tuple[str, ...]
    is_personalized_plan: Literal[False] = False
    infers_treatment_efficacy: Literal[False] = False
    infers_cartilage_regeneration: Literal[False] = False


class WorkbenchWorkflowEquivalence(StrictPreview):
    guard_id: Literal["core:pain_location"]
    base_field: Literal["pain_location"] = "pain_location"
    supplemental_field: Literal["pain_locations"] = "pain_locations"
    source_refs: tuple[str, ...]
    explanation_fa: str


class KneeWorkbench(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-clinical-workbench"] = "4b-mos.knee-clinical-workbench"
    schema_version: Literal["1.0.0"] = "1.0.0"
    baseline_review: KneeReasoningReview
    baseline_workflow_status: Literal["differential_review", "insufficient_information", "prompt_physician_review", "outside_scope", "side_specific_review"]
    workflow_status: Literal["differential_review", "insufficient_information", "prompt_physician_review", "outside_scope", "side_specific_review"]
    workflow_equivalences: tuple[WorkbenchWorkflowEquivalence, ...] = ()
    summary_fa: str
    routine_evaluation_withheld: bool
    supplemental_observations: tuple[WorkbenchObservation, ...]
    quarantined_observations: tuple[WorkbenchObservation, ...]
    comparisons: tuple[DifferentialComparison, ...] = Field(min_length=4, max_length=4)
    next_items: tuple[WorkbenchNextItem, ...]
    management_review: ManagementContextReview
    source_references: tuple[SourceEntry, ...]
    new_draft_proposals: tuple[AssessmentDraftProposal, ...]
    limitations_fa: tuple[str, ...]
    request_sha256: Digest
    rules_sha256: Digest
    source_set_sha256: Digest
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
            raise ValueError("Workbench governance requires exact JSON booleans.")
        return value

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("The workbench does not approve knowledge.")
        return value

    @model_validator(mode="after")
    def workflow_consistency(self):
        if self.routine_evaluation_withheld != (self.workflow_status != "differential_review"):
            raise ValueError("Workflow hold and status must agree.")
        if self.baseline_workflow_status != self.baseline_review.baseline_assessment.status:
            raise ValueError("The baseline workflow must be retained unchanged.")
        if self.routine_evaluation_withheld and any(item.status != "withheld_by_workflow" for item in self.comparisons):
            raise ValueError("Routine comparisons must visibly retain workflow withholding.")
        return self
