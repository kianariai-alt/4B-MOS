"""Read-only, non-clinical inventory contract for the two governed knowledge cores."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class GovernedFactRef(BaseModel):
    fact_id: str
    fact_key: str
    version: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgePackManifest(BaseModel):
    core: Literal["orthopedics", "imaging"]
    pack_key: str
    clinical_domain: str
    approved_fact_count: int = Field(ge=0)
    facts: list[GovernedFactRef]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    readiness: Literal["empty", "references_available"]
    is_clinically_validated: Literal[False] = False


class DualKnowledgeManifest(BaseModel):
    as_of: date
    packs: list[KnowledgePackManifest]
    combined_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    requires_independent_review: Literal[True] = True
