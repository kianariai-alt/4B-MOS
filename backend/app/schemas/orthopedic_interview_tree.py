"""Additive Draft knee interview tree; no patient store or active safety rules.

Answers record the patient's report, not independently verified clinical facts.
The explicit has_pain observation is a routing fact, not a new numbered question.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from backend.app.schemas.orthopedic_book_questions import BookQuestionSourceReference
from backend.app.schemas.orthopedic_knowledge import Digest, SourceEntry
from backend.app.schemas.orthopedic_questions import StrictPreview, StructuredAnswer
from backend.app.schemas.physician_questions import BankContent, InterviewQuestion


TreeField = Literal[
    "chief_complaint", "laterality", "trauma", "fever", "acute_swelling", "systemic_symptoms",
    "sensory_change", "weakness", "foot_coldness", "foot_color_change", "onset", "duration",
    "pain_location", "pain_score_now", "pain_pattern", "aggravating_factor", "relieving_factor",
    "mechanical_locking", "pain_limited_motion", "functional_limitation", "trauma_mechanism",
    "prior_surgery", "surgery_description", "prior_treatment", "treatment_description",
    "treatment_pain_response", "treatment_function_response", "diagnosed_conditions",
    "medication_list", "care_goal", "has_pain",
]
State = Literal["confirmed", "unverified", "incomplete", "contradictory", "unknown", "declined"]
CHOICES = {
    "chief_complaint": ("pain", "swelling", "locking", "instability", "other"),
    "laterality": ("right", "left", "both"),
    "onset": ("sudden", "gradual", "unclear"),
    "duration": ("days", "weeks", "months", "years"),
    "pain_location": ("anterior", "medial", "lateral", "posterior", "diffuse", "unclear"),
    "pain_pattern": ("activity", "rest", "night", "mixed"),
    "aggravating_factor": ("walking", "stairs", "loaded_flexion", "none", "other"),
    "relieving_factor": ("rest", "activity", "none", "other"),
    "functional_limitation": ("none", "mild", "moderate", "severe"),
    "trauma_mechanism": ("sport_twist", "fall", "direct_impact", "other"),
    "treatment_pain_response": ("improved", "unchanged", "worse", "unclear"),
    "treatment_function_response": ("improved", "unchanged", "worse", "unclear"),
    "care_goal": ("pain", "function", "activity", "decision_support"),
}
BOOLEAN_FIELDS = {
    "trauma", "fever", "acute_swelling", "systemic_symptoms", "sensory_change", "weakness",
    "foot_coldness", "foot_color_change", "mechanical_locking", "pain_limited_motion",
    "prior_surgery", "prior_treatment", "has_pain",
}
TEXT_FIELDS = {"surgery_description", "treatment_description", "diagnosed_conditions", "medication_list"}
TREATMENT_FIELDS = {"treatment_description", "treatment_pain_response", "treatment_function_response"}


class DraftTreeModel(StrictPreview):
    governance_status: Literal["draft"] = "draft"
    source_binding_status: Literal["draft_authored"] = "draft_authored"
    requires_independent_review: Literal[True] = True

    @field_validator("requires_independent_review", mode="before")
    @classmethod
    def exact_review_flag(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Independent clinical review remains required.")
        return value


class TreeInterviewAnswer(StrictPreview):
    field: TreeField
    state: State
    value: StrictStr | StrictInt | StrictBool | None = None
    provenance: Literal["patient_report"] = "patient_report"
    source_ref: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def validate_answer(self):
        if self.state in {"unknown", "declined"} and self.value is not None:
            raise ValueError("Unknown/declined answers cannot contain a value.")
        if self.state in {"confirmed", "unverified"} and self.value is None:
            raise ValueError("Complete answers need a typed value.")
        if self.value is not None:
            if self.field in BOOLEAN_FIELDS:
                valid = type(self.value) is bool
            elif self.field == "pain_score_now":
                valid = type(self.value) is int and 0 <= self.value <= 10
            elif self.field in TEXT_FIELDS:
                valid = (type(self.value) is str and bool(self.value.strip()) and len(self.value) <= 1000)
            else:
                valid = type(self.value) is str and self.value in CHOICES[self.field]
            if not valid:
                raise ValueError("Answer does not match its strict field value set.")
        return self


def _unique_sources(observations):
    keys = [(item.field, item.source_ref) for item in observations]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate field/source pair; retain revisions outside this preview.")


class TreeTreatmentEpisode(StrictPreview):
    episode_ref: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    observations: tuple[TreeInterviewAnswer, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def treatment_answers_only(self):
        if any(item.field not in TREATMENT_FIELDS for item in self.observations):
            raise ValueError("An episode accepts only description and separate pain/function responses.")
        _unique_sources(self.observations)
        return self


class TreeInterviewContext(StrictPreview):
    schema_version: Literal["1.0.0"] = "1.0.0"
    body_region: Literal["knee", "other", "unknown"] = "unknown"
    observations: tuple[TreeInterviewAnswer, ...] = Field(default=(), max_length=200)
    treatment_episodes: tuple[TreeTreatmentEpisode, ...] = Field(default=(), max_length=20)
    clinical_findings: tuple[StructuredAnswer, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def segregate_channels(self):
        if any(item.field in TREATMENT_FIELDS for item in self.observations):
            raise ValueError("Treatment answers must identify their treatment episode.")
        if any(not item.field.startswith(("exam_", "imaging_")) for item in self.clinical_findings):
            raise ValueError("Clinical findings accept only the existing examination/imaging channels.")
        _unique_sources(self.observations)
        _unique_sources(self.clinical_findings)
        refs = [item.episode_ref for item in self.treatment_episodes]
        if len(refs) != len(set(refs)):
            raise ValueError("Treatment episode identifiers must be unique.")
        return self


class KneeInterviewTreePreviewRequest(StrictPreview):
    context: TreeInterviewContext
    review_scopes: tuple[Literal["arthroplasty_review"], ...] = Field(default=(), max_length=1)


# Kept as a readable authoring alias, not a second contract/version.
InterviewTreePreviewRequest = KneeInterviewTreePreviewRequest


class TreeCondition(StrictPreview):
    field: TreeField
    equals: StrictBool


class TreeBookBinding(StrictPreview):
    candidate_key: str
    required_scope: Literal["arthroplasty_review"] = "arthroplasty_review"


class InterviewTreeNode(DraftTreeModel):
    number: int = Field(strict=True, ge=1, le=30)
    field: TreeField
    question: InterviewQuestion
    stage: Literal["opening", "risk_information", "symptoms", "mechanical", "history", "goals"]
    conditions: tuple[TreeCondition, ...] = ()
    repeat_per_treatment: bool = False
    requires_treatment_description: bool = False
    source_fact_keys: tuple[str, ...] = ()
    source_content_sha256s: tuple[Digest, ...] = ()
    book_bindings: tuple[TreeBookBinding, ...] = ()
    rationale_fa: str
    authorship: Literal["existing_reworded", "split_existing", "proposed_follow_up"]


class KneeInterviewTree(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-interview-tree"] = "4b-mos.knee-interview-tree"
    schema_version: Literal["1.0.0"] = "1.0.0"
    bank: BankContent
    bank_export_purpose: Literal["authoring_only"] = "authoring_only"
    bank_export_is_executable_tree: Literal[False] = False
    nodes: tuple[InterviewTreeNode, ...] = Field(min_length=30, max_length=30)
    supplemental_routing_fields: tuple[Literal["has_pain"], ...] = ("has_pain",)
    base_pack_manifest_sha256: Digest
    supplement_manifest_sha256: Digest
    source_references: tuple[SourceEntry, ...]
    book_source_references: tuple[BookQuestionSourceReference, ...]
    tree_sha256: Digest

    @field_validator("bank_export_is_executable_tree", mode="before")
    @classmethod
    def exact_nonexecutable_bank(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("The plain bank export cannot execute the complete tree.")
        return value

    @model_validator(mode="after")
    def tree_integrity(self):
        if {node.number for node in self.nodes} != set(range(1, 31)):
            raise ValueError("The agreed tree must preserve the 30 distinct question numbers.")
        if len({node.field for node in self.nodes}) != 30:
            raise ValueError("Each numbered question must address one distinct field.")
        if [q.model_dump() for q in self.bank.questions] != [node.question.model_dump() for node in self.nodes]:
            raise ValueError("The existing bank export must match the ordered tree nodes.")
        for node in self.nodes:
            if len(node.source_fact_keys) != len(node.source_content_sha256s):
                raise ValueError("Every referenced fact must have its bound hash.")
        return self


class TreeInformationGap(StrictPreview):
    field: str
    episode_ref: str | None = None
    reason: Literal["missing", "unknown", "declined", "unverified", "incomplete", "contradictory"]
    requires_physician_review: bool


class InterviewTreeCandidate(DraftTreeModel):
    number: int = Field(strict=True, ge=1, le=30)
    field: TreeField
    question: InterviewQuestion
    episode_ref: str | None = None
    action: Literal["ask_missing", "physician_clarification"]
    rule_id: str
    rule_version: Literal["1.0.0"] = "1.0.0"
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    book_candidate_keys: tuple[str, ...] = ()
    rationale_fa: str


class KneeInterviewTreePreview(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-interview-tree-preview"] = "4b-mos.knee-interview-tree-preview"
    schema_version: Literal["1.0.0"] = "1.0.0"
    tree: KneeInterviewTree
    context: TreeInterviewContext
    review_scopes: tuple[Literal["arthroplasty_review"], ...]
    question_candidates: tuple[InterviewTreeCandidate, ...]
    information_gaps: tuple[TreeInformationGap, ...]
    structured_answers: tuple[TreeInterviewAnswer, ...]
    unverified_answers: tuple[TreeInterviewAnswer, ...]
    clinical_findings: tuple[StructuredAnswer, ...]
    usable_clinical_findings: tuple[StructuredAnswer, ...]
    source_references: tuple[SourceEntry, ...]
    book_source_references: tuple[BookQuestionSourceReference, ...]
    review_reasons: tuple[str, ...]
    request_sha256: Digest
    rules_sha256: Digest
    result_sha256: Digest
    review_only: Literal[True] = True
    registry_write_performed: Literal[False] = False
    is_clinically_validated: Literal[False] = False
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    safety_engine_required: Literal[True] = True
    safety_evaluation: Literal["not_performed"] = "not_performed"
    approved_fact_count: Literal[0] = 0

    @field_validator("review_only", "registry_write_performed", "is_clinically_validated", "is_diagnosis",
                     "is_recommendation", "is_clinical_clearance", "authorizes_treatment", "safety_engine_required",
                     mode="before")
    @classmethod
    def exact_governance_flags(cls, value, info):
        expected = info.field_name in {"review_only", "safety_engine_required"}
        if type(value) is not bool or value is not expected:
            raise ValueError("Authoring governance flags must be exact JSON booleans.")
        return value

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("The authoring preview has no approved facts.")
        return value
