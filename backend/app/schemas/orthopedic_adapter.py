"""Additive orthopedic authoring contract; does not change Integration CoreOutput v1."""
from typing import Literal

from backend.app.schemas.orthopedic_knowledge import (
    DifferentialDefinition, Digest, Identifier, Strict,
)
from backend.app.schemas.orthopedic_questions import (
    InformationGap, QuestionCandidate, StructuredAnswer,
)


class OrthopedicEvidenceReference(Strict):
    fact_key: Identifier
    version: int
    content_sha256: Digest
    content_hash_scope: Literal["registry_fact_content_with_metadata"] = "registry_fact_content_with_metadata"
    statement: str
    population: str
    application_conditions: tuple[str, ...]
    evidence_grade: str
    limitations: tuple[str, ...]
    source_keys: tuple[Identifier, ...]
    governance_status: Literal["draft"] = "draft"
    approved_content_sha256: None = None
    usable_as_approved_knowledge: Literal[False] = False


class OrthopedicSourceReference(Strict):
    source_key: Identifier
    title: str
    url: str
    doi: str | None
    source_version: str | None
    source_sha256: Digest
    hash_scope: Literal["source_reference_metadata"] = "source_reference_metadata"
    access_level: str
    verification_note: str


class DifferentialKnowledgeReference(Strict):
    definition: DifferentialDefinition
    compatibility: Literal["not_assessed"] = "not_assessed"
    is_ranked: Literal[False] = False


class AssessmentRequirement(Strict):
    differential_id: Identifier
    requirements: tuple[str, ...]
    fact_keys: tuple[Identifier, ...]
    governance_status: Literal["draft"] = "draft"
    is_order: Literal[False] = False


class OrthopedicDecisionKnowledge(Strict):
    schema_id: Literal["4b-mos.orthopedic-decision-knowledge"] = "4b-mos.orthopedic-decision-knowledge"
    schema_version: Literal["1.0.0"] = "1.0.0"
    clinical_domain: Literal["orthopedics_knee"] = "orthopedics_knee"
    body_region: Literal["knee", "other", "unknown"]
    context_sha256: Digest
    pack_key: Identifier
    pack_version: int
    pack_manifest_sha256: Digest
    adapter_version: Literal["1.0.0"] = "1.0.0"
    adapter_sha256: Digest
    question_rules_sha256: Digest
    structured_symptoms: tuple[StructuredAnswer, ...]
    examination_findings: tuple[StructuredAnswer, ...]
    imaging_findings: tuple[StructuredAnswer, ...]
    unverified_findings: tuple[StructuredAnswer, ...]
    differential_knowledge_references: tuple[DifferentialKnowledgeReference, ...]
    evidence_references: tuple[OrthopedicEvidenceReference, ...]
    source_references: tuple[OrthopedicSourceReference, ...]
    information_gaps: tuple[InformationGap, ...]
    question_candidates: tuple[QuestionCandidate, ...]
    assessment_requirements: tuple[AssessmentRequirement, ...]
    review_reasons: tuple[str, ...]
    governance_status: Literal["draft"] = "draft"
    approved_fact_count: Literal[0] = 0
    workflow_state: Literal["preview_only"] = "preview_only"
    existing_safety_engine_required: Literal[True] = True
    safety_evaluation: Literal["not_performed"] = "not_performed"
    requires_independent_review: Literal[True] = True
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    result_sha256: Digest
