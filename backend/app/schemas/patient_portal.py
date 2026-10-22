"""Patient-authored request contracts; not yet exposed by public endpoints.

Tenant, identity, admission codes and verification are assigned by the server,
never accepted as patient claims. These contracts do not authorize clinical care.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PortalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReportedMedication(PortalModel):
    name: str = Field(min_length=1, max_length=200)
    dose_as_reported: str | None = Field(default=None, max_length=200)
    frequency_as_reported: str | None = Field(default=None, max_length=200)
    use_status: Literal["taking", "stopped", "unknown"] = "unknown"


class PatientRequestCreate(PortalModel):
    """Unverified patient statements, distinct from a finalized clinical intake."""

    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    entry_mode: Literal["clinic_arrival", "remote_request"]
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    contact_phone: str | None = Field(default=None, min_length=5, max_length=40, pattern=r"^[+0-9۰-۹٠-٩ ()-]+$")
    date_of_birth: date | None = None
    preferred_language: Literal["fa", "en", "ar", "other"] = "fa"
    complaint: str = Field(min_length=3, max_length=3000)
    symptom_history: str | None = Field(default=None, max_length=6000)
    body_region: str | None = Field(default=None, min_length=1, max_length=100)
    laterality: Literal["right", "left", "bilateral", "midline", "unknown"] = "unknown"
    symptom_onset_date: date | None = None
    pain_score: int | None = Field(default=None, ge=0, le=10, strict=True)
    conditions: list[str] = Field(default_factory=list, max_length=100)
    medications: list[ReportedMedication] = Field(default_factory=list, max_length=100)
    allergies: list[str] = Field(default_factory=list, max_length=100)
    processing_notice_version: str = Field(min_length=1, max_length=100)
    processing_consent: Literal[True]
    marketing_opt_in: bool = Field(default=False, strict=True)
    other_specialists: list[str] = Field(default_factory=list, max_length=30)
    wants_prompt_contact: bool = Field(default=False, strict=True)

    @field_validator("processing_consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit processing consent is required.")
        return value

    @field_validator("date_of_birth", "symptom_onset_date")
    @classmethod
    def dates_not_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Reported date cannot be in the future.")
        return value

    @field_validator("conditions", "allergies", "other_specialists")
    @classmethod
    def bounded_reported_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value.strip()) > 500 for value in values):
            raise ValueError("Each reported item must contain 1 to 500 characters.")
        return [value.strip() for value in values]


class PortalMessageCreate(PortalModel):
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    text: str = Field(min_length=3, max_length=3000)


class PortalLinkCreate(PortalModel):
    identity_checked: Literal[True]
    existing_patient_id: str | None = Field(default=None, min_length=36, max_length=36)

    @field_validator("identity_checked", mode="before")
    @classmethod
    def explicit_identity_check(cls, value):
        if value is not True:
            raise ValueError("Staff must verify patient identity before linking.")
        return value


class PortalAnswerCreate(PortalModel):
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    expected_version: int = Field(ge=0, strict=True)
    question_id: str = Field(min_length=1, max_length=80)
    state: Literal["answered", "unknown", "declined"]
    value: (
        Annotated[str, Field(strict=True, min_length=1, max_length=3000)]
        | Annotated[int, Field(strict=True)]
        | Annotated[float, Field(strict=True, allow_inf_nan=False)]
        | None
    ) = None
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    supplementary_text: str | None = Field(default=None, min_length=1, max_length=3000)

    @field_validator("value", mode="before")
    @classmethod
    def reject_boolean_values(cls, value):
        if isinstance(value, bool):
            raise ValueError("Use yes/no codes for a boolean answer.")
        return value

    @model_validator(mode="after")
    def explicit_answer_state(self):
        if self.state == "answered" and self.value is None:
            raise ValueError("An answered question requires a value.")
        if self.state != "answered" and (self.value is not None or self.unit is not None):
            raise ValueError("Unknown and declined answers have no value or unit.")
        return self
