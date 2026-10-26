"""Draft authoring contracts layered on the existing Medical Knowledge Registry.

A pack is a review artifact, never a second approved knowledge store. Structured
metadata is embedded in each fact's statement before Registry hashing/review.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.medical_knowledge import KnowledgeFactCreate, KnowledgeSourceCreate

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=100)]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceEntry(Strict):
    source_key: Identifier
    source: KnowledgeSourceCreate
    verified_at: date
    access_level: Literal["full_text", "abstract", "bibliographic_metadata", "indexed_recommendations"]
    verification_note: str = Field(min_length=10)


class OrthopedicFact(Strict):
    fact: KnowledgeFactCreate
    version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    body_region: Literal["knee"] = "knee"
    topic: Literal["osteoarthritis", "meniscus", "cartilage_osteochondral", "safety", "orthobiologics", "examination"]
    summary: str = Field(min_length=20)
    application_conditions: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    source_keys: tuple[Identifier, ...] = Field(min_length=1)
    content_sha256: Digest

    def registry_metadata(self) -> dict:
        return {
            "orthopedic_schema_version": "1.0.0", "body_region": self.body_region,
            "topic": self.topic, "application_conditions": list(self.application_conditions),
            "limitations": list(self.limitations), "source_keys": list(self.source_keys),
        }

    def registry_statement(self) -> str:
        return self.summary + "\n\nOrthopedic metadata v1:\n" + canonical_json(self.registry_metadata())

    @model_validator(mode="after")
    def bound_metadata(self):
        if self.fact.clinical_domain != "orthopedics_knee":
            raise ValueError("Knee pack facts require exact orthopedics_knee domain.")
        if not self.fact.population or not self.fact.indication:
            raise ValueError("Each orthopedic proposition needs population and indication.")
        if self.fact.statement != self.registry_statement():
            raise ValueError("Registry statement must bind all structured fact metadata.")
        if len(self.source_keys) != len(set(self.source_keys)):
            raise ValueError("Duplicate source key in fact.")
        return self


class ConceptRef(Strict):
    id: Identifier
    kind: Literal["symptom", "examination", "syndrome", "differential", "evidence", "assessment", "treatment"]
    label: str = Field(min_length=2, max_length=500)


class KnowledgeRelation(Strict):
    id: Identifier
    version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    source: ConceptRef
    target: ConceptRef
    relationship: Literal["may_support", "may_oppose", "assessed_by", "informs_review", "evidence_for", "requires_review"]
    fact_keys: tuple[Identifier, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)


class ExaminationDefinition(Strict):
    id: Identifier
    name: str
    body_region: Literal["knee"] = "knee"
    purpose: str
    method: str
    recordable_findings: tuple[str, ...] = Field(min_length=1)
    result_states: tuple[Literal["positive", "negative", "indeterminate"], ...] = ("positive", "negative", "indeterminate")
    precautions: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    diagnostic_accuracy: None = None
    fact_keys: tuple[Identifier, ...] = Field(min_length=1)
    status: Literal["draft"] = "draft"
    version: Literal[1] = 1


class DifferentialDefinition(Strict):
    id: Identifier
    label: str
    known_presentations: tuple[str, ...] = Field(min_length=1)
    risk_factors: tuple[str, ...] = ()
    supporting_findings: tuple[str, ...] = ()
    opposing_findings: tuple[str, ...] = ()
    examination_ids: tuple[Identifier, ...] = ()
    assessment_requirements: tuple[str, ...] = Field(min_length=1)
    warning_features: tuple[str, ...] = ()
    diagnostic_criteria: tuple[str, ...] = ()
    limitations: tuple[str, ...] = Field(min_length=1)
    fact_keys: tuple[Identifier, ...] = Field(min_length=1)
    status: Literal["draft"] = "draft"
    version: Literal[1] = 1


class TreatmentEvidence(Strict):
    id: Identifier
    treatment_type: Literal["exercise", "NSAID", "corticosteroid", "surgical_referral", "ACS", "PRGF", "PL", "PRP", "HA", "EXOSOME", "SVF", "MSC"]
    proposed_mechanism: str
    studied_indications: tuple[str, ...]
    contraindications_precautions: tuple[str, ...]
    evidence_quality: Literal["ungraded", "not_appraised"] = "not_appraised"
    reported_effect: str | None = None
    study_follow_up: str | None = None
    adverse_effects: tuple[str, ...] = ()
    comparator: str | None = None
    guideline_positions: tuple[str, ...] = ()
    regulatory_status: str
    regulatory_jurisdiction: str
    research_status: str
    internal_observations: Literal["not_used_as_efficacy_evidence"] = "not_used_as_efficacy_evidence"
    uncertainties: tuple[str, ...] = Field(min_length=1)
    fact_keys: tuple[Identifier, ...] = Field(min_length=1)
    status: Literal["draft"] = "draft"
    version: Literal[1] = 1


class KneeKnowledgePack(Strict):
    schema_version: Literal["1.0.0"] = "1.0.0"
    pack_key: Literal["knee_orthopedic_v1"] = "knee_orthopedic_v1"
    pack_version: Literal[1] = 1
    clinical_domain: Literal["orthopedics_knee"] = "orthopedics_knee"
    status: Literal["draft"] = "draft"
    source_review_date: date
    sources: tuple[SourceEntry, ...] = Field(min_length=1)
    facts: tuple[OrthopedicFact, ...] = Field(min_length=1)
    relations: tuple[KnowledgeRelation, ...] = ()
    examinations: tuple[ExaminationDefinition, ...] = ()
    differentials: tuple[DifferentialDefinition, ...] = ()
    treatments: tuple[TreatmentEvidence, ...] = ()
    manifest_sha256: Digest
    is_clinically_validated: Literal[False] = False
    requires_independent_review: Literal[True] = True

    def get_fact(self, key: str) -> OrthopedicFact:
        for entry in self.facts:
            if entry.fact.fact_key == key:
                return entry
        raise KeyError(key)

    @model_validator(mode="after")
    def reference_integrity(self):
        source_map = {s.source_key: s for s in self.sources}
        fact_keys = {f.fact.fact_key for f in self.facts}
        if len(source_map) != len(self.sources) or len(fact_keys) != len(self.facts):
            raise ValueError("Duplicate source or fact key.")
        for fact in self.facts:
            if not set(fact.source_keys) <= source_map.keys():
                raise ValueError("Fact references an unknown source.")
            expected = [source_map[k].source.model_dump(mode="json") for k in fact.source_keys]
            if expected != [s.model_dump(mode="json") for s in fact.fact.sources]:
                raise ValueError("Fact source metadata must match verified source catalog.")
        exam_ids = {x.id for x in self.examinations}
        for name in ("relations", "examinations", "differentials", "treatments"):
            items = getattr(self, name)
            if len({x.id for x in items}) != len(items):
                raise ValueError("Duplicate structured knowledge identifier.")
            for item in items:
                if not set(item.fact_keys) <= fact_keys:
                    raise ValueError("Structured knowledge references an unknown fact.")
        for differential in self.differentials:
            if not set(differential.examination_ids) <= exam_ids:
                raise ValueError("Differential references unknown examination.")
        typed_concepts = {
            "differential": {item.id for item in self.differentials},
            "examination": exam_ids | {finding for exam in self.examinations for finding in exam.recordable_findings},
            "treatment": {item.id for item in self.treatments},
        }
        # Symptoms, syndromes, evidence and assessment identifiers are local
        # vocabulary nodes. Definitions with their own catalogs must resolve.
        for relation in self.relations:
            for concept in (relation.source, relation.target):
                if concept.kind in typed_concepts and concept.id not in typed_concepts[concept.kind]:
                    raise ValueError("Relation references an unknown typed concept.")
        return self
