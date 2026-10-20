"""Minimum-necessary, review-only orthopedic interview preview contracts.

`confirmed` describes a complete structured answer from its stated source. A
patient-reported answer never becomes a physician examination or verified image.
No patient identifiers, demographics or free-text narratives are accepted here.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from backend.app.schemas.physician_questions import BankContent, InterviewQuestion


QuestionField = Literal[
    "chief_complaint", "onset", "duration", "pain_location", "pain_score",
    "pain_pattern", "aggravating_factor", "relieving_factor", "mechanical_locking",
    "functional_limitation", "trauma", "trauma_mechanism", "prior_surgery",
    "prior_treatment", "treatment_response", "relevant_comorbidity", "current_medication",
    "fever", "acute_swelling", "neurovascular_symptoms", "systemic_symptoms", "care_goal",
    "exam_joint_line_tenderness", "exam_effusion", "exam_range_of_motion",
    "imaging_kl_grade", "imaging_meniscal_lesion", "imaging_cartilage_lesion",
]

CHOICES = {
    "chief_complaint": ("pain", "swelling", "locking", "instability", "other"),
    "onset": ("sudden", "gradual", "unclear"),
    "duration": ("days", "weeks", "months", "years"),
    "pain_location": ("anterior", "medial", "lateral", "posterior", "diffuse", "unclear"),
    "pain_pattern": ("activity", "rest", "night", "mixed"),
    "aggravating_factor": ("walking", "stairs", "loaded_flexion", "none", "other"),
    "relieving_factor": ("rest", "activity", "none", "other"),
    "functional_limitation": ("none", "mild", "moderate", "severe"),
    "trauma_mechanism": ("sport_twist", "fall", "direct_impact", "other"),
    "treatment_response": ("improved", "unchanged", "worse", "unclear"),
    "care_goal": ("pain", "function", "activity", "decision_support"),
    "exam_range_of_motion": ("full", "restricted", "unclear"),
}
BOOLEAN_FIELDS = {
    "mechanical_locking", "trauma", "prior_surgery", "prior_treatment",
    "relevant_comorbidity", "current_medication", "fever", "acute_swelling",
    "neurovascular_symptoms", "systemic_symptoms", "exam_joint_line_tenderness",
    "exam_effusion", "imaging_meniscal_lesion", "imaging_cartilage_lesion",
}

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class StrictPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class StructuredAnswer(StrictPreview):
    field: QuestionField
    state: Literal["confirmed", "unverified", "incomplete", "contradictory", "unknown", "declined"]
    value: StrictStr | StrictInt | StrictBool | None = None
    provenance: Literal["patient_report", "physician_exam", "reviewed_imaging", "unreviewed_imaging"]
    source_ref: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def validate_answer(self):
        if self.state in {"unknown", "declined"} and self.value is not None:
            raise ValueError("Unknown or declined answers cannot carry a value.")
        if self.state in {"confirmed", "unverified"} and self.value is None:
            raise ValueError("A complete answer needs a typed value.")
        if self.value is not None:
            if self.field in BOOLEAN_FIELDS:
                valid = type(self.value) is bool
            elif self.field in {"pain_score", "imaging_kl_grade"}:
                valid = type(self.value) is int and 0 <= self.value <= (10 if self.field == "pain_score" else 4)
            else:
                valid = type(self.value) is str and self.value in CHOICES[self.field]
            if not valid:
                raise ValueError("Answer does not match the field's controlled value set.")
        if self.field.startswith("exam_") and self.provenance != "physician_exam":
            raise ValueError("Examination fields require physician examination provenance.")
        if self.field.startswith("imaging_"):
            if self.provenance not in {"reviewed_imaging", "unreviewed_imaging"}:
                raise ValueError("Imaging fields require imaging provenance.")
            if self.provenance == "unreviewed_imaging" and self.state == "confirmed":
                raise ValueError("Unreviewed imaging cannot be a confirmed finding.")
        elif not self.field.startswith("exam_") and self.provenance != "patient_report":
            raise ValueError("History fields require patient-report provenance.")
        return self


class OrthopedicQuestionContext(StrictPreview):
    schema_version: Literal["1.0.0"] = "1.0.0"
    body_region: Literal["knee", "other", "unknown"] = "unknown"
    observations: tuple[StructuredAnswer, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def unique_observation_sources(self):
        keys = [(item.field, item.source_ref) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("Each field/source pair must occur only once; preserve revisions externally.")
        return self


class InformationGap(StrictPreview):
    field: QuestionField
    reason: Literal["missing", "unknown", "declined", "unverified", "incomplete", "contradictory"]
    requires_physician_review: bool


class QuestionCandidate(StrictPreview):
    question: InterviewQuestion
    field: QuestionField
    rule_id: str
    rule_version: Literal["1.0.0"] = "1.0.0"
    source_fact_keys: tuple[str, ...]
    source_content_sha256s: tuple[Digest, ...]
    rationale_fa: str
    action: Literal["ask_missing", "physician_clarification"]
    governance_status: Literal["draft"] = "draft"
    requires_independent_review: Literal[True] = True


class OrthopedicQuestionResult(StrictPreview):
    schema_version: Literal["1.0.0"] = "1.0.0"
    body_region: Literal["knee", "other", "unknown"]
    context_sha256: Digest
    rules_sha256: Digest
    bank: BankContent
    structured_symptoms: tuple[StructuredAnswer, ...]
    examination_findings: tuple[StructuredAnswer, ...]
    reviewed_imaging_findings: tuple[StructuredAnswer, ...]
    unverified_findings: tuple[StructuredAnswer, ...]
    information_gaps: tuple[InformationGap, ...]
    question_candidates: tuple[QuestionCandidate, ...]
    review_reasons: tuple[str, ...]
    governance_status: Literal["draft"] = "draft"
    review_only: Literal[True] = True
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    safety_engine_required: Literal[True] = True
