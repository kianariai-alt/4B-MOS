"""Physician-authored interview content; approval is not diagnosis authorization."""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_serializer, model_validator

FiniteNumber = Union[StrictInt, Annotated[StrictFloat, Field(allow_inf_nan=False)]]
ConditionValue = Union[StrictStr, FiniteNumber]

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionProvenance(Strict):
    """An unspecified legacy source never becomes a claimed clinical citation."""
    kind: Literal["unspecified", "physician_authored", "reference", "clinic_protocol", "design_draft"] = "unspecified"
    reference: str | None = Field(default=None, min_length=1, max_length=1000)


class PredicateCondition(Strict):
    question_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=80)
    operator: Literal["eq", "ne", "in", "gt", "gte", "lt", "lte", "state_in"]
    value: ConditionValue | None = None
    values: list[ConditionValue] = Field(default_factory=list, max_length=20)
    states: list[Literal["answered", "unknown", "declined", "missing"]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_operand(self):
        if self.operator == "state_in":
            if not self.states or self.value is not None or self.values or len(self.states) != len(set(self.states)):
                raise ValueError("A state predicate requires only unique states.")
        elif self.operator == "in":
            if not self.values or self.value is not None or self.states:
                raise ValueError("An in predicate requires only values.")
        elif self.value is None or self.values or self.states:
            raise ValueError("A comparison predicate requires one value.")
        return self


class AllCondition(Strict):
    all: list["DisplayCondition"] = Field(min_length=1, max_length=20)


class AnyCondition(Strict):
    any: list["DisplayCondition"] = Field(min_length=1, max_length=20)


DisplayCondition = Union[PredicateCondition, AllCondition, AnyCondition]
AllCondition.model_rebuild()
AnyCondition.model_rebuild()


def condition_predicates(condition, depth=0):
    """Bound nesting and collect references for authoring-time validation."""
    if depth > 8:
        raise ValueError("Display conditions may nest at most eight levels.")
    if isinstance(condition, PredicateCondition):
        return [condition]
    children = condition.all if isinstance(condition, AllCondition) else condition.any
    predicates = [p for child in children for p in condition_predicates(child, depth + 1)]
    if len(predicates) > 100:
        raise ValueError("A display condition has too many predicates.")
    return predicates

class InterviewQuestion(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=80)
    text_fa: str = Field(min_length=3, max_length=1000)
    purpose_fa: str = Field(min_length=3, max_length=1000)
    answer_type: Literal["text", "yes_no", "single_choice", "number"] = "text"
    choices: list[str] = Field(default_factory=list, max_length=20)
    depends_on_id: str | None = None
    show_when_answer_in: list[str] = Field(default_factory=list, max_length=20)
    allow_unknown: Literal[True] = True
    allow_decline: Literal[True] = True
    question_version: str = Field(default="legacy-unspecified", min_length=1, max_length=80)
    provenance: QuestionProvenance = Field(default_factory=QuestionProvenance)
    display_condition: DisplayCondition | None = None
    numeric_unit: str | None = Field(default=None, min_length=1, max_length=80)
    numeric_min: FiniteNumber | None = None
    numeric_max: FiniteNumber | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_content(self, handler):
        data = handler(self)
        # Existing bank digests and request retries bind exact JSON content.
        # New defaults must not rewrite an old question when it is read/dumped.
        for name in ("question_version", "provenance", "display_condition", "numeric_unit", "numeric_min", "numeric_max"):
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data

    @model_validator(mode="after")
    def validate_choices(self):
        for values in (self.choices, self.show_when_answer_in):
            if len(values) != len(set(values)) or any(not v.strip() or len(v)>200 for v in values):
                raise ValueError("Choices must be unique, nonempty and at most 200 characters.")
        if (self.answer_type == "single_choice" and len(self.choices)<2) or (self.answer_type != "single_choice" and self.choices):
            raise ValueError("Only single-choice questions have choices, at least two.")
        if bool(self.depends_on_id) != bool(self.show_when_answer_in):
            raise ValueError("A condition requires both a predecessor and matching answers.")
        if self.display_condition is not None and self.depends_on_id is not None:
            raise ValueError("Use either a legacy condition or a compound condition.")
        if self.answer_type == "number":
            if self.numeric_unit is None or self.numeric_min is None or self.numeric_max is None:
                raise ValueError("A numeric question requires an explicit unit and both bounds.")
            if self.numeric_min > self.numeric_max:
                raise ValueError("Numeric minimum must not exceed maximum.")
        elif any(v is not None for v in (self.numeric_unit, self.numeric_min, self.numeric_max)):
            raise ValueError("Numeric metadata is only valid for numeric questions.")
        if self.display_condition is not None:
            condition_predicates(self.display_condition)
        return self

class BankContent(Strict):
    contract_version: Literal["1.0.0"] = "1.0.0"
    title_fa: str = Field(min_length=3, max_length=200)
    scope_fa: str = Field(min_length=3, max_length=500)
    summary_preferences_fa: str | None = Field(default=None, max_length=2000)
    questions: list[InterviewQuestion] = Field(min_length=1, max_length=100)

    @model_serializer(mode="wrap")
    def preserve_legacy_contract(self, handler):
        data = handler(self)
        if "contract_version" not in self.model_fields_set:
            data.pop("contract_version", None)
        return data

    @model_validator(mode="after")
    def validate_order(self):
        previous = {}
        for q in self.questions:
            if "contract_version" in self.model_fields_set and (q.question_version == "legacy-unspecified" or q.provenance.kind == "unspecified"):
                raise ValueError("An explicitly versioned bank requires question versions and provenance.")
            if q.id in previous:
                raise ValueError("Duplicate question id.")
            if q.depends_on_id:
                parent = previous.get(q.depends_on_id)
                if parent is None:
                    raise ValueError("Conditions must reference an earlier question.")
                allowed = ["yes", "no"] if parent.answer_type == "yes_no" else parent.choices if parent.answer_type == "single_choice" else None
                if allowed is not None and any(v not in allowed for v in q.show_when_answer_in):
                    raise ValueError("Condition answer is not in predecessor choices.")
                if parent.answer_type == "number":
                    raise ValueError("Numeric predecessors require a typed display condition.")
            if q.display_condition is not None:
                for predicate in condition_predicates(q.display_condition):
                    parent = previous.get(predicate.question_id)
                    if parent is None:
                        raise ValueError("Conditions must reference an earlier question.")
                    if predicate.operator == "state_in":
                        continue
                    operands = predicate.values if predicate.operator == "in" else [predicate.value]
                    if parent.answer_type == "number":
                        if any(type(value) not in (int, float) for value in operands):
                            raise ValueError("Numeric predicates require numeric operands.")
                    elif any(not isinstance(value, str) for value in operands) or predicate.operator in {"gt", "gte", "lt", "lte"}:
                        raise ValueError("Text and choice predicates require string equality or membership.")
                    allowed = ["yes", "no"] if parent.answer_type == "yes_no" else parent.choices if parent.answer_type == "single_choice" else None
                    if allowed is not None and any(value not in allowed for value in operands):
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
