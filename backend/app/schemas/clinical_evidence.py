from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.medical_knowledge import (
    KnowledgeEvidenceGrade,
    KnowledgeSourceType,
    KnowledgeTherapyType,
)


Sha256 = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
]


class EvidenceBriefFactSelection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    fact_id: str = Field(min_length=1, max_length=36)
    expected_content_sha256: Sha256


class ClinicalEvidenceBriefCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    clinical_question: str = Field(min_length=5, max_length=2000)
    expected_clinical_context_sha256: Sha256
    facts: list[EvidenceBriefFactSelection] = Field(
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_facts(self):
        fact_ids = [item.fact_id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Each medical knowledge fact can appear only once.")
        return self


class EvidenceBriefActorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_user_id: str
    actor_username: str
    actor_display_name: str
    actor_role: Literal["physician"]


class EvidenceBriefRecordReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    record_type: Literal["clinical_intake", "paraclinical_report"]
    record_key: str | None
    version: int
    content_sha256: Sha256


class EvidenceBriefContextManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake: EvidenceBriefRecordReference
    reports: list[EvidenceBriefRecordReference]


class EvidenceBriefSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: KnowledgeSourceType
    title: str
    citation: str
    publisher: str | None
    url: str | None
    doi: str | None
    publication_date: date | None
    guideline_version: str | None
    accessed_at: date


class EvidenceBriefFactSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fact_key: str
    version: int
    title: str
    statement: str
    clinical_domain: str
    therapy_type: KnowledgeTherapyType | None
    population: str | None
    indication: str | None
    contraindications: list[str]
    evidence_grade: KnowledgeEvidenceGrade
    content_sha256: Sha256
    valid_from: date | None
    valid_to: date | None
    sources: list[EvidenceBriefSourceSnapshot]


class ClinicalEvidenceBriefPayloadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str
    visit_id: str
    clinical_question: str
    intended_user: Literal["physician"]
    intended_use: Literal["independent_evidence_review"]
    selection_method: Literal["clinician_selected"]
    ordering: Literal["fact_key_then_version"]
    output_type: Literal["evidence_summary"]
    knowledge_as_of: date
    clinical_context_sha256: Sha256
    context_manifest: EvidenceBriefContextManifest
    knowledge_set_sha256: Sha256
    facts: list[EvidenceBriefFactSnapshot]
    known_limitations: list[str]
    actor: EvidenceBriefActorSnapshot
    created_at: str


class ClinicalEvidenceBriefRead(BaseModel):
    id: str
    visit_id: str
    intake_id: str
    report_ids: list[str]
    clinical_context_sha256: Sha256
    knowledge_fact_ids: list[str]
    knowledge_set_sha256: Sha256
    knowledge_as_of: date
    selection_method: Literal["clinician_selected"]
    output_type: Literal["evidence_summary"]
    created_by_user_id: str
    sha256: Sha256
    created_at: datetime
    payload: ClinicalEvidenceBriefPayloadRead
    is_recommendation: Literal[False] = False
    ranks_treatments: Literal[False] = False
    provides_risk_score: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    is_time_critical: Literal[False] = False
    requires_independent_review: Literal[True] = True
