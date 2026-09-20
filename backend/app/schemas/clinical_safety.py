from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SafetyRuleStatus = Literal[
    "draft",
    "in_review",
    "approved",
    "rejected",
    "retired",
]
SafetySeverity = Literal["info", "warning", "high", "critical"]
SafetyAction = Literal[
    "document",
    "review_before_proceeding",
    "urgent_clinical_review",
]
SafetyCombinator = Literal["all", "any"]
SafetyConditionSource = Literal["intake", "observation"]
SafetyOperator = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "in",
    "contains_text",
    "contains_any",
    "is_missing",
    "is_present",
    "is_empty",
    "is_not_empty",
]

RuleScalar = bool | int | Decimal | str
RuleValue = RuleScalar | list[str] | list[Decimal] | None

INTAKE_NUMERIC_FIELDS = frozenset({"pain_score"})
INTAKE_TEXT_FIELDS = frozenset(
    {
        "chief_complaint",
        "history_present_illness",
        "body_region",
        "laterality",
        "exam_findings",
        "clinical_impression",
        "care_goal",
    }
)
INTAKE_LIST_FIELDS = frozenset(
    {
        "functional_limitations",
        "relevant_history",
        "current_medications",
        "allergies",
        "red_flags",
    }
)
OBSERVATION_NUMERIC_FIELDS = frozenset({"quantity_value", "integer_value"})
OBSERVATION_TEXT_FIELDS = frozenset(
    {"string_value", "coded_value", "interpretation"}
)
OBSERVATION_BOOLEAN_FIELDS = frozenset({"boolean_value"})
OBSERVATION_FIELDS = (
    OBSERVATION_NUMERIC_FIELDS
    | OBSERVATION_TEXT_FIELDS
    | OBSERVATION_BOOLEAN_FIELDS
    | {"existence"}
)
UNARY_OPERATORS = frozenset(
    {"is_missing", "is_present", "is_empty", "is_not_empty"}
)
NUMERIC_OPERATORS = frozenset(
    {"eq", "ne", "gt", "gte", "lt", "lte", "between"}
)
TEXT_OPERATORS = frozenset(
    {"eq", "ne", "in", "contains_text", "is_missing", "is_present"}
)


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


class SafetyCondition(BaseModel):
    """One declarative condition; it never contains executable code."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    source: SafetyConditionSource
    field: str = Field(min_length=1, max_length=100)
    operator: SafetyOperator
    value: RuleValue = None
    case_sensitive: bool = False
    code_system: Literal["LOINC", "SNOMED_CT", "LOCAL", "OTHER"] | None = None
    code_system_uri: str | None = Field(default=None, max_length=500)
    code_system_version: str | None = Field(default=None, max_length=50)
    code: str | None = Field(default=None, max_length=100)
    unit_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def normalize_numeric_json_values(cls, data):
        """Preserve decimal thresholds sent through JSON without accepting code."""
        if not isinstance(data, dict):
            return data
        source = data.get("source")
        field = data.get("field")
        is_numeric_field = (
            source == "intake" and field in INTAKE_NUMERIC_FIELDS
        ) or (
            source == "observation" and field in OBSERVATION_NUMERIC_FIELDS
        )
        if not is_numeric_field or data.get("operator") in UNARY_OPERATORS:
            return data

        value = data.get("value")
        normalized = dict(data)
        try:
            if isinstance(value, str):
                normalized["value"] = Decimal(value)
            elif isinstance(value, list):
                normalized["value"] = [
                    Decimal(item) if isinstance(item, str) else item
                    for item in value
                ]
        except InvalidOperation as exc:
            raise ValueError("A numeric condition requires a numeric value.") from exc
        return normalized

    @field_validator(
        "code_system_uri",
        "code_system_version",
        "code",
        "unit_code",
        mode="after",
    )
    @classmethod
    def empty_strings_are_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def validate_condition(self):
        if self.operator in UNARY_OPERATORS:
            if self.value is not None:
                raise ValueError(f"{self.operator} does not accept a value.")
        elif self.value is None:
            raise ValueError(f"{self.operator} requires a value.")

        if self.source == "intake":
            if any(
                item is not None
                for item in (
                    self.code_system,
                    self.code_system_uri,
                    self.code_system_version,
                    self.code,
                    self.unit_code,
                )
            ):
                raise ValueError(
                    "Observation selectors are not valid for intake conditions."
                )
            self._validate_intake_condition()
        else:
            self._validate_observation_condition()
        return self

    def _validate_intake_condition(self) -> None:
        if self.field in INTAKE_NUMERIC_FIELDS:
            if self.operator not in NUMERIC_OPERATORS | {
                "is_missing",
                "is_present",
            }:
                raise ValueError("The intake numeric field uses an invalid operator.")
            self._validate_numeric_value()
            return
        if self.field in INTAKE_TEXT_FIELDS:
            if self.operator not in TEXT_OPERATORS:
                raise ValueError("The intake text field uses an invalid operator.")
            self._validate_text_value()
            return
        if self.field in INTAKE_LIST_FIELDS:
            if self.operator not in {
                "contains_text",
                "contains_any",
                "is_empty",
                "is_not_empty",
            }:
                raise ValueError("The intake list field uses an invalid operator.")
            self._validate_text_value()
            return
        raise ValueError(f"Unsupported intake field: {self.field}.")

    def _validate_observation_condition(self) -> None:
        if self.field not in OBSERVATION_FIELDS:
            raise ValueError(f"Unsupported observation field: {self.field}.")
        if self.code_system is None or self.code is None:
            raise ValueError(
                "code_system and code are required for observation conditions."
            )
        if self.code_system == "OTHER" and not self.code_system_uri:
            raise ValueError(
                "code_system_uri is required when code_system is OTHER."
            )
        if self.code_system != "OTHER" and self.code_system_uri is not None:
            raise ValueError(
                "code_system_uri is only valid when code_system is OTHER."
            )
        if self.field == "existence":
            if self.operator not in {"is_missing", "is_present"}:
                raise ValueError(
                    "Observation existence supports only is_missing or is_present."
                )
            if self.unit_code is not None:
                raise ValueError("unit_code is not valid for observation existence.")
            return
        if self.field in OBSERVATION_NUMERIC_FIELDS:
            if self.operator not in NUMERIC_OPERATORS | {
                "is_missing",
                "is_present",
            }:
                raise ValueError(
                    "The observation numeric field uses an invalid operator."
                )
            if self.field == "quantity_value" and self.unit_code is None:
                raise ValueError(
                    "unit_code is required for quantity_value comparisons."
                )
            if self.field == "integer_value" and self.unit_code is not None:
                raise ValueError("unit_code is not valid for integer_value.")
            self._validate_numeric_value()
            return
        if self.unit_code is not None:
            raise ValueError("unit_code is only valid for quantity_value.")
        if self.field in OBSERVATION_TEXT_FIELDS:
            if self.operator not in TEXT_OPERATORS:
                raise ValueError(
                    "The observation text field uses an invalid operator."
                )
            self._validate_text_value()
            return
        if self.field in OBSERVATION_BOOLEAN_FIELDS:
            if self.operator not in {"eq", "ne", "is_missing", "is_present"}:
                raise ValueError(
                    "The observation boolean field uses an invalid operator."
                )
            if (
                self.operator not in UNARY_OPERATORS
                and not isinstance(self.value, bool)
            ):
                raise ValueError("A boolean condition requires a boolean value.")

    def _validate_numeric_value(self) -> None:
        if self.operator in UNARY_OPERATORS:
            return
        if self.operator == "between":
            if (
                not isinstance(self.value, list)
                or len(self.value) != 2
                or not all(_is_numeric(item) for item in self.value)
            ):
                raise ValueError("between requires exactly two numeric values.")
            if Decimal(str(self.value[1])) < Decimal(str(self.value[0])):
                raise ValueError("between upper bound cannot be below lower bound.")
            return
        if not _is_numeric(self.value):
            raise ValueError("A numeric condition requires a numeric value.")

    def _validate_text_value(self) -> None:
        if self.operator in UNARY_OPERATORS:
            return
        if self.operator in {"in", "contains_any"}:
            if (
                not isinstance(self.value, list)
                or not self.value
                or not all(isinstance(item, str) and item for item in self.value)
            ):
                raise ValueError(
                    f"{self.operator} requires a non-empty list of strings."
                )
            return
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("A text condition requires a non-empty string value.")


class SafetyPredicate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    combinator: SafetyCombinator
    conditions: list[SafetyCondition] = Field(min_length=1, max_length=50)


class SafetyRuleContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=20, max_length=10000)
    clinical_domain: str = Field(min_length=2, max_length=100)
    severity: SafetySeverity
    action: SafetyAction
    message: str = Field(min_length=10, max_length=5000)
    predicate: SafetyPredicate
    knowledge_fact_ids: list[str] = Field(min_length=1, max_length=20)
    valid_from: date | None = None
    valid_to: date | None = None

    @field_validator("knowledge_fact_ids", mode="after")
    @classmethod
    def unique_knowledge_facts(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip()
            if not normalized:
                raise ValueError("knowledge_fact_ids cannot contain empty values.")
            if normalized not in seen:
                cleaned.append(normalized)
                seen.add(normalized)
        return cleaned

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to cannot be earlier than valid_from.")
        return self


class SafetyRuleCreate(SafetyRuleContent):
    rule_key: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )

    @field_validator("rule_key", mode="after")
    @classmethod
    def normalize_rule_key(cls, value: str) -> str:
        return value.upper()


class SafetyRuleUpdate(SafetyRuleContent):
    pass


class SafetyRuleSupersede(SafetyRuleContent):
    pass


class SafetyRuleReview(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_rejection_comment(self):
        if self.decision == "rejected" and not self.comment:
            raise ValueError("A review comment is required when rejecting a rule.")
        return self


class SafetyRuleKnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sort_order: int
    medical_knowledge_fact_id: str
    fact_content_sha256: str


class SafetyRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_key: str
    version: int
    title: str
    description: str
    clinical_domain: str
    severity: SafetySeverity
    action: SafetyAction
    message: str
    predicate: SafetyPredicate
    status: SafetyRuleStatus
    content_sha256: str
    supersedes_rule_id: str | None
    created_by_user_id: str
    submitted_at: datetime | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    review_comment: str | None
    valid_from: date | None
    valid_to: date | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    knowledge_links: list[SafetyRuleKnowledgeRead]


class SafetyConditionTrace(BaseModel):
    condition_index: int
    matched: bool
    source: SafetyConditionSource
    field: str
    operator: SafetyOperator
    code_system: str | None = None
    code: str | None = None
    matched_record_ids: list[str] = Field(default_factory=list)


class SafetyFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sort_order: int
    rule_id: str
    rule_key: str
    rule_version: int
    rule_content_sha256: str
    title: str
    severity: SafetySeverity
    action: SafetyAction
    message: str
    knowledge_fact_ids: list[str]
    condition_trace: list[SafetyConditionTrace]
    created_at: datetime


class SafetyEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    visit_id: str
    intake_id: str | None
    report_ids: list[str]
    engine_version: str
    outcome: Literal["alerts_present", "no_alerts", "no_active_rules"]
    evaluated_rule_count: int
    triggered_count: int
    highest_severity: SafetySeverity | None
    clinical_context_sha256: str
    rule_set_sha256: str
    result_sha256: str
    evaluated_by_user_id: str
    created_at: datetime
    findings: list[SafetyFindingRead]
    is_clinical_clearance: Literal[False] = False


class SafetyEvaluationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_clinical_context_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_rule_set_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
