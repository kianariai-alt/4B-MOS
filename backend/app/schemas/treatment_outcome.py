from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Sha256 = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
]
OutcomeStatus = Literal[
    "improved",
    "unchanged",
    "worsened",
    "mixed",
    "unknown",
]
OutcomeText = Annotated[
    str,
    Field(min_length=1, max_length=500),
]


class OutcomeMeasureInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    measure_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    label: str = Field(min_length=1, max_length=200)
    instrument: str | None = Field(default=None, max_length=200)
    value: Decimal
    unit: str | None = Field(default=None, max_length=50)
    scale_min: Decimal | None = None
    scale_max: Decimal | None = None
    higher_is_better: bool | None = None

    @model_validator(mode="after")
    def validate_scale(self):
        if (self.scale_min is None) != (self.scale_max is None):
            raise ValueError(
                "scale_min and scale_max must be supplied together."
            )
        if (
            self.scale_min is not None
            and self.scale_max is not None
            and self.scale_max <= self.scale_min
        ):
            raise ValueError("scale_max must be greater than scale_min.")
        if (
            self.scale_min is not None
            and (
                self.value < self.scale_min
                or self.value > self.scale_max
            )
        ):
            raise ValueError("value must be inside the declared scale.")
        return self


class TreatmentOutcomeCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    expected_clinical_context_sha256: Sha256
    follow_up_day: int = Field(ge=0, le=3650)
    outcome_status: OutcomeStatus
    patient_rating: int | None = Field(default=None, ge=1, le=5)
    physician_rating: int | None = Field(default=None, ge=1, le=5)
    pain_score: int | None = Field(default=None, ge=0, le=10)
    function_score: int | None = Field(default=None, ge=0, le=100)
    outcome_measures: list[OutcomeMeasureInput] = Field(
        default_factory=list,
        max_length=50,
    )
    adverse_events: list[OutcomeText] = Field(
        default_factory=list,
        max_length=20,
    )
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_observed_content(self):
        if (
            self.outcome_status == "unknown"
            and self.patient_rating is None
            and self.physician_rating is None
            and self.pain_score is None
            and self.function_score is None
            and not self.outcome_measures
            and not self.adverse_events
        ):
            raise ValueError(
                "An outcome observation needs at least one observed result."
            )
        keys = [item.measure_key for item in self.outcome_measures]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Each outcome measure key can appear only once per follow-up."
            )
        return self


class OutcomeFinalizationReference(BaseModel):
    session_id: str
    session_number: int
    finalization_sha256: Sha256


class TreatmentOutcomePayloadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str
    treatment_id: str
    visit_id: str
    treatment_type: str
    protocol_code: str | None
    protocol_version: str | None
    body_region: str | None
    clinical_context_sha256: Sha256
    treatment_snapshot_sha256: Sha256
    treatment_snapshot: dict
    finalizations: list[OutcomeFinalizationReference]
    follow_up_day: int
    outcome_status: OutcomeStatus
    patient_rating: int | None
    patient_rating_source: Literal["patient_reported"] | None
    physician_rating: int | None
    pain_score: int | None
    function_score: int | None
    outcome_measures: list[OutcomeMeasureInput]
    adverse_events: list[str]
    notes: str | None
    created_by_user_id: str
    recorded_at: str
    known_limitations: list[str]


class TreatmentOutcomeRead(BaseModel):
    id: str
    treatment_id: str
    visit_id: str
    treatment_type: str
    protocol_code: str | None
    protocol_version: str | None
    body_region: str | None
    clinical_context_sha256: Sha256
    treatment_snapshot_sha256: Sha256
    finalization_sha256s: list[Sha256]
    follow_up_day: int
    outcome_status: OutcomeStatus
    patient_rating: int | None
    physician_rating: int | None
    pain_score: int | None
    function_score: int | None
    outcome_measures: list[OutcomeMeasureInput]
    adverse_events: list[str]
    notes: str | None
    created_by_user_id: str
    sha256: Sha256
    recorded_at: datetime
    payload: TreatmentOutcomePayloadRead
    is_causal_evidence: Literal[False] = False
    is_treatment_recommendation: Literal[False] = False
    requires_bias_review: Literal[True] = True
