from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


ClinicalRecordStatus = Literal[
    "draft",
    "final",
    "superseded",
    "entered_in_error",
]
ClinicalLaterality = Literal[
    "left",
    "right",
    "bilateral",
    "midline",
    "not_applicable",
    "unknown",
]
ParaclinicalCategory = Literal[
    "laboratory",
    "imaging",
    "pathology",
    "vital_sign",
    "clinical_test",
    "other",
]
ObservationCodeSystem = Literal["LOINC", "SNOMED_CT", "LOCAL", "OTHER"]
ObservationValueType = Literal[
    "quantity",
    "string",
    "boolean",
    "integer",
    "coded",
    "datetime",
    "absent",
]
ObservationInterpretation = Literal[
    "normal",
    "low",
    "high",
    "critical_low",
    "critical_high",
    "abnormal",
    "indeterminate",
]

ListItem = Annotated[str, Field(min_length=1, max_length=500)]
MeasuredDecimal = Annotated[
    Decimal,
    Field(max_digits=18, decimal_places=6),
]


def _clean_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            raise ValueError("List values cannot be empty.")
        key = normalized.casefold()
        if key not in seen:
            cleaned.append(normalized)
            seen.add(key)
    return cleaned


class ClinicalIntakeContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    chief_complaint: str = Field(min_length=3, max_length=5000)
    history_present_illness: str = Field(min_length=3, max_length=20000)
    body_region: str | None = Field(default=None, max_length=100)
    laterality: ClinicalLaterality | None = None
    symptom_onset_date: date | None = None
    pain_score: int | None = Field(default=None, ge=0, le=10)
    functional_limitations: list[ListItem] = Field(
        default_factory=list,
        max_length=100,
    )
    relevant_history: list[ListItem] = Field(
        default_factory=list,
        max_length=100,
    )
    current_medications: list[ListItem] = Field(
        default_factory=list,
        max_length=100,
    )
    allergies: list[ListItem] = Field(default_factory=list, max_length=100)
    exam_findings: str | None = Field(default=None, max_length=20000)
    red_flags: list[ListItem] = Field(default_factory=list, max_length=100)
    clinical_impression: str | None = Field(default=None, max_length=10000)
    care_goal: str | None = Field(default=None, max_length=5000)

    @field_validator(
        "body_region",
        "exam_findings",
        "clinical_impression",
        "care_goal",
        mode="after",
    )
    @classmethod
    def optional_empty_strings_are_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator(
        "functional_limitations",
        "relevant_history",
        "current_medications",
        "allergies",
        "red_flags",
        mode="after",
    )
    @classmethod
    def clean_lists(cls, values: list[str]) -> list[str]:
        return _clean_list(values)

    @field_validator("symptom_onset_date", mode="after")
    @classmethod
    def onset_cannot_be_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("symptom_onset_date cannot be in the future.")
        return value


class ClinicalIntakeCreate(ClinicalIntakeContent):
    pass


class ClinicalIntakeSupersede(ClinicalIntakeContent):
    revision_reason: str = Field(min_length=10, max_length=5000)


class ClinicalIntakeRead(ClinicalIntakeContent):
    model_config = ConfigDict(from_attributes=True)

    id: str
    visit_id: str
    version: int
    status: ClinicalRecordStatus
    revision_reason: str | None
    content_sha256: str
    supersedes_intake_id: str | None
    created_by_user_id: str
    finalized_by_user_id: str | None
    finalized_at: datetime | None
    entered_in_error_by_user_id: str | None
    entered_in_error_at: datetime | None
    error_reason: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class ParaclinicalObservationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: ParaclinicalCategory
    code_system: ObservationCodeSystem
    code_system_uri: str | None = Field(default=None, max_length=500)
    code_system_version: str | None = Field(default=None, max_length=50)
    code: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=300)
    value_type: ObservationValueType
    quantity_value: MeasuredDecimal | None = None
    string_value: str | None = Field(default=None, max_length=20000)
    boolean_value: bool | None = None
    integer_value: int | None = None
    coded_value: str | None = Field(default=None, max_length=100)
    coded_system: str | None = Field(default=None, max_length=100)
    coded_display: str | None = Field(default=None, max_length=300)
    datetime_value: AwareDatetime | None = None
    absent_reason: str | None = Field(default=None, max_length=100)
    unit_code: str | None = Field(default=None, max_length=100)
    unit_display: str | None = Field(default=None, max_length=100)
    reference_low: MeasuredDecimal | None = None
    reference_high: MeasuredDecimal | None = None
    reference_text: str | None = Field(default=None, max_length=2000)
    interpretation: ObservationInterpretation | None = None
    body_site: str | None = Field(default=None, max_length=200)
    specimen: str | None = Field(default=None, max_length=200)
    method: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=5000)
    observed_at: AwareDatetime | None = None

    @field_serializer(
        "quantity_value",
        "reference_low",
        "reference_high",
        when_used="json",
    )
    def serialize_measured_decimal(
        self,
        value: Decimal | None,
    ) -> str | None:
        # The database stores six decimal places. Emit that same representation
        # before and after persistence so API clients never see format drift.
        return format(value, ".6f") if value is not None else None

    @field_validator(
        "code_system_version",
        "code_system_uri",
        "string_value",
        "coded_value",
        "coded_system",
        "coded_display",
        "absent_reason",
        "unit_code",
        "unit_display",
        "reference_text",
        "body_site",
        "specimen",
        "method",
        "note",
        mode="after",
    )
    @classmethod
    def optional_empty_strings_are_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("datetime_value", "observed_at", mode="after")
    @classmethod
    def normalize_datetime(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_typed_value(self):
        if self.code_system == "OTHER" and not self.code_system_uri:
            raise ValueError(
                "code_system_uri is required when code_system is OTHER."
            )
        required_field = {
            "quantity": "quantity_value",
            "string": "string_value",
            "boolean": "boolean_value",
            "integer": "integer_value",
            "coded": "coded_value",
            "datetime": "datetime_value",
            "absent": "absent_reason",
        }[self.value_type]
        value_fields = (
            "quantity_value",
            "string_value",
            "boolean_value",
            "integer_value",
            "coded_value",
            "datetime_value",
            "absent_reason",
        )
        if getattr(self, required_field) is None:
            raise ValueError(
                f"{required_field} is required for value_type={self.value_type}."
            )
        unexpected = [
            field
            for field in value_fields
            if field != required_field and getattr(self, field) is not None
        ]
        if unexpected:
            raise ValueError(
                "Value fields do not match value_type: "
                + ", ".join(sorted(unexpected))
            )
        if self.value_type == "coded":
            if not self.coded_system:
                raise ValueError("coded_system is required for a coded value.")
        elif self.coded_system is not None or self.coded_display is not None:
            raise ValueError(
                "coded_system and coded_display are only valid for coded values."
            )
        if self.value_type == "quantity":
            if not self.unit_code:
                raise ValueError(
                    "unit_code is required for a quantity; use UCUM '1' "
                    "for a dimensionless result."
                )
            if (
                self.reference_low is not None
                and self.reference_high is not None
                and self.reference_high < self.reference_low
            ):
                raise ValueError("reference_high cannot be below reference_low.")
        elif any(
            value is not None
            for value in (
                self.unit_code,
                self.unit_display,
                self.reference_low,
                self.reference_high,
            )
        ):
            raise ValueError(
                "Units and numeric reference limits are only valid for quantities."
            )
        return self


class ParaclinicalObservationRead(ParaclinicalObservationInput):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sort_order: int
    created_at: datetime


class ParaclinicalReportContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: ParaclinicalCategory
    title: str = Field(min_length=3, max_length=300)
    external_identifier: str | None = Field(default=None, max_length=200)
    performed_at: AwareDatetime | None = None
    issued_at: AwareDatetime | None = None
    performer: str | None = Field(default=None, max_length=300)
    conclusion: str | None = Field(default=None, max_length=20000)
    source_reference: str | None = Field(default=None, max_length=1000)
    observations: list[ParaclinicalObservationInput] = Field(
        default_factory=list,
        max_length=500,
    )

    @field_validator(
        "external_identifier",
        "performer",
        "conclusion",
        "source_reference",
        mode="after",
    )
    @classmethod
    def optional_empty_strings_are_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("performed_at", "issued_at", mode="after")
    @classmethod
    def normalize_datetime(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_report(self):
        if not self.observations and not self.conclusion:
            raise ValueError(
                "A paraclinical report needs at least one observation or a conclusion."
            )
        if (
            self.performed_at is not None
            and self.issued_at is not None
            and self.issued_at < self.performed_at
        ):
            raise ValueError("issued_at cannot be earlier than performed_at.")
        return self


class ParaclinicalReportCreate(ParaclinicalReportContent):
    report_key: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )

    @field_validator("report_key", mode="after")
    @classmethod
    def normalize_report_key(cls, value: str) -> str:
        return value.upper()


class ParaclinicalReportSupersede(ParaclinicalReportContent):
    revision_reason: str = Field(min_length=10, max_length=5000)


class ParaclinicalReportRead(ParaclinicalReportContent):
    model_config = ConfigDict(from_attributes=True)

    id: str
    visit_id: str
    report_key: str
    version: int
    status: ClinicalRecordStatus
    revision_reason: str | None
    content_sha256: str
    supersedes_report_id: str | None
    created_by_user_id: str
    finalized_by_user_id: str | None
    finalized_at: datetime | None
    entered_in_error_by_user_id: str | None
    entered_in_error_at: datetime | None
    error_reason: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    observations: list[ParaclinicalObservationRead]


class EnterClinicalRecordInError(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=10, max_length=5000)


class ClinicalContextRead(BaseModel):
    visit_id: str
    generated_at: datetime
    intake: ClinicalIntakeRead | None
    reports: list[ParaclinicalReportRead]
