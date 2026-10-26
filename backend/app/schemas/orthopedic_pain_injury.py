"""Draft pain/injury roadmap with an explicit primary organizing source."""
from datetime import datetime
from typing import Literal

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from backend.app.schemas.orthopedic_assessment import AssessmentDraftProposal
from backend.app.schemas.orthopedic_interview_tree import DraftTreeModel
from backend.app.schemas.orthopedic_knowledge import Digest, SourceEntry, content_digest
from backend.app.schemas.orthopedic_questions import StrictPreview
from backend.app.schemas.orthopedic_workbench import KneeWorkbench, WorkbenchNextItem, WorkbenchObservation


class ZetamedSourceSnapshot(StrictPreview):
    schema_version: Literal["1.0.0"]
    source_key: Literal["zetamed_knee_pain"]
    url: Literal["https://zetamed.org/knee-pain/"]
    resolved_url: Literal["https://zetamed.org/knee-pain/"]
    retrieved_at: StrictStr
    http_status: StrictInt = Field(ge=200, le=200)
    content_type_reported: StrictStr
    content_encoding_reported: StrictStr | None
    response_body_byte_count: StrictInt = Field(gt=0)
    source_document_sha256: Digest
    displayed_publication_date: Literal["2025-09-05"]
    publication_date_verification_method: StrictStr
    source_version: StrictStr = Field(min_length=1, max_length=100)
    source_text_retained: Literal[False]
    is_medical_approval: Literal[False]
    metadata_sha256: Digest

    @model_validator(mode="before")
    @classmethod
    def metadata_integrity(cls, value):
        if not isinstance(value, dict) or value.get("metadata_sha256") != content_digest(
            {key: item for key, item in value.items() if key != "metadata_sha256"}
        ):
            raise ValueError("Source snapshot metadata hash does not match.")
        if any(type(value.get(key)) is not bool or value[key] is not False
               for key in ("source_text_retained", "is_medical_approval")):
            raise ValueError("The source snapshot retains no article text or medical approval.")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def aware_acquisition_time(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Source acquisition time must include its timezone.")
        return value


class PainInjuryRoute(DraftTreeModel):
    id: str
    label_fa: str
    status: Literal["context_present", "context_not_reported", "information_missing"]
    interpretation_fa: str
    article_section_locator: str
    organizing_source_key: Literal["zetamed_knee_pain"] = "zetamed_knee_pain"
    observations: tuple[WorkbenchObservation, ...]
    differential_comparison_ids: tuple[Literal["oa", "pfp", "meniscus", "cartilage"], ...]
    source_fact_keys: tuple[str, ...] = Field(min_length=1)
    source_content_sha256s: tuple[Digest, ...] = Field(min_length=1)
    question_links: tuple[WorkbenchNextItem, ...]
    limitations_fa: tuple[str, ...] = Field(min_length=1)
    is_excluded: Literal[False] = False
    is_ranked: Literal[False] = False

    @field_validator("is_excluded", "is_ranked", mode="before")
    @classmethod
    def exact_false(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("A route neither ranks nor excludes diseases.")
        return value

    @model_validator(mode="after")
    def bound_fact_hashes(self):
        if len(self.source_fact_keys) != len(self.source_content_sha256s):
            raise ValueError("Every medical fact reference needs its bound content hash.")
        return self


class PainInjuryCoverageGap(DraftTreeModel):
    id: str
    label_fa: str
    reason_fa: str
    status: Literal["not_implemented"] = "not_implemented"
    is_excluded: Literal[False] = False

    @field_validator("is_excluded", mode="before")
    @classmethod
    def exact_false(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("An unimplemented domain cannot exclude disease.")
        return value


class KneePainInjuryReview(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-pain-injury-review"] = "4b-mos.knee-pain-injury-review"
    schema_version: Literal["1.0.0"] = "1.0.0"
    workbench: KneeWorkbench
    organizing_source: SourceEntry
    organizing_source_role: Literal["primary_organizing_source"] = "primary_organizing_source"
    source_document_sha256: Digest
    source_snapshot_metadata_sha256: Digest
    source_document_hash_scope: Literal["recorded_response_bytes_not_independently_rehashed"] = "recorded_response_bytes_not_independently_rehashed"
    routes: tuple[PainInjuryRoute, ...] = Field(min_length=8, max_length=8)
    coverage_gaps: tuple[PainInjuryCoverageGap, ...]
    raw_risk_observations: tuple[WorkbenchObservation, ...]
    routine_evaluation_withheld: bool
    source_references: tuple[SourceEntry, ...]
    new_draft_proposals: tuple[AssessmentDraftProposal, ...] = Field(min_length=2, max_length=2)
    limitations_fa: tuple[str, ...]
    request_sha256: Digest
    rules_sha256: Digest
    source_set_sha256: Digest
    result_sha256: Digest
    review_only: Literal[True] = True
    is_diagnosis: Literal[False] = False
    is_clinically_validated: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    registry_write_performed: Literal[False] = False
    safety_engine_required: Literal[True] = True
    safety_evaluation: Literal["not_performed"] = "not_performed"
    approved_fact_count: Literal[0] = 0

    @field_validator("review_only", "is_diagnosis", "is_clinically_validated", "is_recommendation",
                     "is_clinical_clearance", "authorizes_treatment", "registry_write_performed",
                     "safety_engine_required", mode="before")
    @classmethod
    def exact_governance_flags(cls, value, info):
        expected = info.field_name in {"review_only", "safety_engine_required"}
        if type(value) is not bool or value is not expected:
            raise ValueError("Draft source organization cannot grant clinical authority.")
        return value

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("The source-organizing review approves no medical facts.")
        return value

    @model_validator(mode="after")
    def preserve_workbench_and_source_role(self):
        if self.organizing_source.source_key != "zetamed_knee_pain":
            raise ValueError("The primary organizing source must be the reviewed knee-pain article.")
        if self.routine_evaluation_withheld != self.workbench.routine_evaluation_withheld:
            raise ValueError("The existing workflow hold must be preserved.")
        if len({row.id for row in self.routes}) != 8:
            raise ValueError("The eight pain/injury route identifiers must be distinct.")
        return self
