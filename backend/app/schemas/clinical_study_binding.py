"""Opaque study-to-visit association contracts, without image interpretation.

Physician review applies only to the recorded association. These schemas do not
verify DICOM identity, model findings, or a producer's data-quality assertion.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, Field, field_validator, model_validator

from backend.app.schemas.clinical_integration import ComponentVersion, ContractModel, Digest, Identifier


Token = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$", strict=True)]


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, (str, UUID)):
        raise ValueError("An opaque UUID reference is required.")
    try:
        return str(UUID(str(value)))
    except ValueError as error:
        raise ValueError("An opaque UUID reference is required.") from error


OpaqueStudyReference = Annotated[
    str, BeforeValidator(_canonical_uuid),
    Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
          json_schema_extra={"format": "uuid"}),
]
OpaqueSeriesReference = OpaqueStudyReference


class StudyBindingComponent(ComponentVersion):
    """Versioned component identity; URLs and free-text descriptions are excluded."""

    component_id: Token
    version: Token


class StudyBindingContent(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    report_id: Identifier
    report_version: int = Field(ge=1)
    report_content_sha256: Digest
    clinical_context_sha256: Digest
    opaque_study_reference: OpaqueStudyReference
    opaque_series_reference: OpaqueSeriesReference
    study_sha256: Digest
    series_sha256: Digest
    quality_assessment_sha256: Digest
    modality: Literal["DX", "CR", "MR", "CT"]
    imaging_component: StudyBindingComponent
    quality_component: StudyBindingComponent
    quality_status: Literal["data_ready", "blocked", "not_assessed"]
    source_generated_at: AwareDatetime
    source_valid_until: AwareDatetime

    @field_validator("source_generated_at", "source_valid_until", mode="after")
    @classmethod
    def source_times_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def bounded_source_validity(self):
        duration = self.source_valid_until - self.source_generated_at
        if duration <= timedelta(0) or duration > timedelta(hours=24):
            raise ValueError("Source validity must be positive and at most 24 hours.")
        return self


class StudyBindingCreate(StudyBindingContent):
    request_key: Token
    expected_previous_binding_sha256: Digest | None = None


class BindingSnapshot(StudyBindingContent):
    id: Identifier
    visit_id: Identifier
    report_key: Identifier
    revision: int = Field(ge=1)
    previous_binding_sha256: Digest | None = None
    request_sha256: Digest
    created_by_user_id: Identifier
    created_at: AwareDatetime

    @field_validator("created_at", mode="after")
    @classmethod
    def creation_time_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class StudyBindingReviewCreate(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_key: Token
    expected_binding_sha256: Digest
    expected_previous_review_sha256: Digest | None = None
    action: Literal["confirm", "reject", "invalidate"]
    rationale: str = Field(min_length=10, max_length=5000)


class StudyBindingReview(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_key: Token
    id: Identifier
    binding_id: Identifier
    visit_id: Identifier
    sequence: int = Field(ge=1)
    binding_sha256: Digest
    previous_review_sha256: Digest | None = None
    physician_user_id: Identifier
    reviewed_at: AwareDatetime
    action: Literal["confirm", "reject", "invalidate"]
    rationale: str = Field(min_length=10, max_length=5000)
    review_scope: Literal["study_to_visit_association"] = "study_to_visit_association"
    verifies_model_findings: Literal[False] = False
    dicom_identity_verified: Literal[False] = False

    @field_validator("reviewed_at", mode="after")
    @classmethod
    def review_time_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class StudyBindingRead(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    binding: BindingSnapshot
    binding_sha256: Digest
    reviews: tuple[StudyBindingReview, ...]
    review_status: Literal["unverified", "verified", "rejected", "invalid"]
    freshness: Literal["current", "stale"]
    invalidation_reasons: tuple[Identifier, ...]
    eligible_for_contextual_link: bool
    latest_review_sha256: Digest | None = None
    review_scope: Literal["study_to_visit_association"] = "study_to_visit_association"
    dicom_identity_verified: Literal[False] = False
    verifies_model_findings: Literal[False] = False
    quality_assertion_verified: Literal[False] = False

    @model_validator(mode="after")
    def eligibility_requires_current_review(self):
        if self.eligible_for_contextual_link and (
            self.review_status != "verified" or self.freshness != "current"
            or self.binding.quality_status != "data_ready" or not self.reviews
            or self.reviews[-1].action != "confirm" or self.latest_review_sha256 is None
        ):
            raise ValueError("An eligible association requires a current, confirmed, data-ready binding.")
        return self


class StudyBindingInventory(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    bindings: tuple[StudyBindingRead, ...]
    sha256: Digest
