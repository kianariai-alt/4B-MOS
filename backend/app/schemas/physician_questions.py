"""Physician-authored interview content; approval is not diagnosis authorization."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class InterviewQuestion(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=80)
    text_fa: str = Field(min_length=3, max_length=1000)
    purpose_fa: str = Field(min_length=3, max_length=1000)
    answer_type: Literal["text", "yes_no", "single_choice"] = "text"
    choices: list[str] = Field(default_factory=list, max_length=20)
    depends_on_id: str | None = None
    show_when_answer_in: list[str] = Field(default_factory=list, max_length=20)
    allow_unknown: Literal[True] = True
    allow_decline: Literal[True] = True

    @model_validator(mode="after")
    def validate_choices(self):
        for values in (self.choices, self.show_when_answer_in):
            if len(values) != len(set(values)) or any(not v.strip() or len(v)>200 for v in values):
                raise ValueError("Choices must be unique, nonempty and at most 200 characters.")
        if (self.answer_type == "single_choice" and len(self.choices)<2) or (self.answer_type != "single_choice" and self.choices):
            raise ValueError("Only single-choice questions have choices, at least two.")
        if bool(self.depends_on_id) != bool(self.show_when_answer_in):
            raise ValueError("A condition requires both a predecessor and matching answers.")
        return self

class BankContent(Strict):
    title_fa: str = Field(min_length=3, max_length=200)
    scope_fa: str = Field(min_length=3, max_length=500)
    summary_preferences_fa: str | None = Field(default=None, max_length=2000)
    questions: list[InterviewQuestion] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_order(self):
        previous = {}
        for q in self.questions:
            if q.id in previous:
                raise ValueError("Duplicate question id.")
            if q.depends_on_id:
                parent = previous.get(q.depends_on_id)
                if parent is None:
                    raise ValueError("Conditions must reference an earlier question.")
                allowed = ["yes", "no"] if parent.answer_type == "yes_no" else parent.choices if parent.answer_type == "single_choice" else None
                if allowed is not None and any(v not in allowed for v in q.show_when_answer_in):
                    raise ValueError("Condition answer is not in predecessor choices.")
            previous[q.id] = q
        return self

class DraftCreate(BankContent):
    expected_version: int = Field(strict=True, ge=0)
    request_key: str = Field(min_length=8, max_length=100)

class BankReview(Strict):
    expected_version: int = Field(strict=True, ge=1)
    expected_bank_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: str = Field(min_length=8, max_length=100)
    statement_fa: str = Field(min_length=20, max_length=2000)

class BankEventRead(Strict):
    schema_version: Literal[1]
    id: str
    physician_id: str
    version: int
    action: Literal["draft", "approve", "retire"]
    request_key: str
    recorded_by: str
    created_at: str
    command: dict
    content: BankContent
    reviewed_bank_sha256: str | None
    sha256: str

class BankWorkspaceRead(Strict):
    physician_id: str
    version: int
    latest: BankEventRead | None
    active_bank: BankEventRead | None
    has_approved_bank: bool
    is_trained_model: Literal[False] = False
    authorizes_diagnosis: Literal[False] = False

class VisitQuestionBankRead(Strict):
    visit_id: str
    physician_id: str | None
    bank_id: str | None = None
    bank_sha256: str | None = None
    questions: list[InterviewQuestion] = Field(default_factory=list)
    has_approved_bank: bool = False
    authorizes_diagnosis: Literal[False] = False
