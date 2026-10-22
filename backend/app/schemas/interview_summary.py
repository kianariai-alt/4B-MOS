"""Versioned patient interview handoff; never a confirmed clinical finding."""
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from backend.app.schemas.physician_questions import (
    FiniteNumber, InterviewQuestion, QuestionProvenance, Strict,
)


class ReportedInterviewAnswer(Strict):
    question_id: str
    question: str
    question_definition: InterviewQuestion
    state: Literal["answered", "unknown", "declined"]
    value: Annotated[str, Field(strict=True)] | FiniteNumber | None
    unit: str | None
    supplementary_text: str | None
    recorded_at: AwareDatetime | None
    source: Literal["patient_portal", "legacy_patient_portal"]
    bank_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    question_version: str
    provenance: QuestionProvenance
    answer_event_id: str

    @model_validator(mode="after")
    def validate_reported_metadata(self):
        if self.state == "answered" and self.value is None:
            raise ValueError("An answered item requires a value.")
        if self.state != "answered" and (self.value is not None or self.unit is not None):
            raise ValueError("Unknown and declined items have no value or unit.")
        if self.state == "answered":
            question = self.question_definition
            if question.answer_type == "number":
                if (type(self.value) not in (int, float)
                        or self.unit != question.numeric_unit
                        or not question.numeric_min <= self.value <= question.numeric_max):
                    raise ValueError("Numeric answer must match the question's type, unit and bounds.")
            else:
                if not isinstance(self.value, str) or not self.value.strip() or self.unit is not None:
                    raise ValueError("Text and choice answers require a nonempty string and no unit.")
                choices = ["yes", "no"] if question.answer_type == "yes_no" else question.choices
                if choices and self.value not in choices:
                    raise ValueError("Choice answer must match the question's allowed codes.")
        if self.source == "patient_portal" and self.recorded_at is None:
            raise ValueError("New answers require a server timestamp.")
        if (self.question_id != self.question_definition.id
                or self.question != self.question_definition.text_fa
                or self.question_version != self.question_definition.question_version
                or self.provenance != self.question_definition.provenance):
            raise ValueError("Question identity and provenance must match its snapshot.")
        return self


class InterviewAssistantSummary(Strict):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source: Literal["patient_portal"] = "patient_portal"
    patient_reported_only: Literal[True] = True
    requires_clinician_review: Literal[True] = True
    bank_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    physician_id: str
    request_id: str
    interview_version: int = Field(strict=True, ge=0)
    items: list[ReportedInterviewAnswer]
    missing_question_ids: list[str]
    unknown_question_ids: list[str]
    declined_question_ids: list[str]
    inactive_question_ids: list[str]
    summary_fa: str

    @model_validator(mode="after")
    def validate_active_partition(self):
        answered_ids = [item.question_id for item in self.items]
        groups = [answered_ids, self.missing_question_ids, self.inactive_question_ids]
        combined = [identifier for group in groups for identifier in group]
        if len(combined) != len(set(combined)):
            raise ValueError("Active answers, missing questions and inactive questions are distinct.")
        if any(item.bank_sha256 != self.bank_sha256 for item in self.items):
            raise ValueError("All answer items must refer to the snapshot bank.")
        if self.unknown_question_ids != [item.question_id for item in self.items if item.state == "unknown"]:
            raise ValueError("Unknown question IDs must reflect active item states.")
        if self.declined_question_ids != [item.question_id for item in self.items if item.state == "declined"]:
            raise ValueError("Declined question IDs must reflect active item states.")
        return self
