"""Patient-free literature-discovery contracts; never an approved knowledge store."""
from datetime import date, datetime
from typing import Literal

from pydantic import Field, StrictInt, field_validator

from backend.app.schemas.orthopedic_knowledge import Digest, Strict


EvidenceTopic = Literal["knee_oa", "meniscus", "cartilage", "orthobiologics"]


class EvidenceWatchRequest(Strict):
    topic: EvidenceTopic
    since: date | None = None
    max_records: StrictInt = Field(default=10, ge=1, le=20)


class EvidenceCandidate(Strict):
    candidate_id: str
    provider: Literal["europe_pmc"] = "europe_pmc"
    provider_source: Literal["MED"] = "MED"
    provider_id: str
    pmid: str
    doi: str | None = None
    title: str
    journal: str | None = None
    publication_types_reported: str | None = None
    publication_year: str | None = None
    first_publication_date_reported: str | None = None
    publication_date_precision_verified: Literal[False] = False
    source_version: str | None = None
    source_version_verified: Literal[False] = False
    citation_url: str
    retraction_status: Literal["flagged", "not_flagged_by_returned_metadata", "not_reported"]
    correction_status: Literal["flagged", "not_flagged_by_returned_metadata", "not_reported"]
    record_payload_sha256: Digest
    status: Literal["draft"] = "draft"
    independent_review_required: Literal[True] = True
    evidence_quality: Literal["unassessed"] = "unassessed"
    access_scope: Literal["bibliographic_metadata_only"] = "bibliographic_metadata_only"
    is_clinical_recommendation: Literal[False] = False

    @field_validator("publication_date_precision_verified", "source_version_verified",
                     "independent_review_required", "is_clinical_recommendation", mode="before")
    @classmethod
    def exact_flags(cls, value, info):
        expected = info.field_name == "independent_review_required"
        if type(value) is not bool or value is not expected:
            raise ValueError("Discovery does not verify or approve medical evidence.")
        return value


class EvidenceWatchResult(Strict):
    schema_id: Literal["4b-mos.orthopedic-evidence-watch"] = "4b-mos.orthopedic-evidence-watch"
    schema_version: Literal["1.0.0"] = "1.0.0"
    request: EvidenceWatchRequest
    request_sha256: Digest
    rules_sha256: Digest
    query: str
    endpoint: str
    acquisition_mode: Literal["online", "provided_response", "not_requested"]
    status: Literal["discovered", "failed", "online_not_requested"]
    fetched_at: datetime | None = None
    provider_api_version: str | None = None
    source_payload_sha256: Digest | None = None
    provider_hit_count: StrictInt | None = None
    candidates: tuple[EvidenceCandidate, ...] = ()
    error_code: Literal["http_error", "endpoint_blocked", "redirect_blocked", "network_error", "timeout", "response_limit",
                        "malformed_response", "invalid_record"] | None = None
    error_detail: str | None = None
    limitations: tuple[str, ...]
    registry_import_performed: Literal[False] = False
    medical_approval_performed: Literal[False] = False
    patient_information_sent: Literal[False] = False
    clinical_logic_changed: Literal[False] = False
    approved_fact_count: Literal[0] = 0
    result_sha256: Digest

    @field_validator("registry_import_performed", "medical_approval_performed",
                     "patient_information_sent", "clinical_logic_changed", mode="before")
    @classmethod
    def exact_false(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("Evidence discovery cannot perform a clinical write or approval.")
        return value

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("Discovery cannot approve facts.")
        return value
