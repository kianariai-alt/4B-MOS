"""Authoring-only book annotations around the unchanged knee interview contract.

Workflow scopes are a clinician's explicit review choice, not a diagnosis,
confirmed intervention, or determination that a source applies to a patient.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.medical_knowledge import KnowledgeSourceCreate
from backend.app.schemas.orthopedic_book_handoff import BookDraftProvenance, Digest, HandoffModel
from backend.app.schemas.orthopedic_book_review import Identifier, MeaningfulText
from backend.app.schemas.orthopedic_questions import (
    OrthopedicQuestionContext, OrthopedicQuestionResult, QuestionField,
)


ReviewScope = Literal[
    "arthroplasty_review", "meniscus_review", "cartilage_review",
    "ocd_review", "prp_evidence_review",
]


class BookQuestionPreviewRequest(HandoffModel):
    context: OrthopedicQuestionContext
    review_scopes: tuple[ReviewScope, ...] = Field(default=(), max_length=5)

    @field_validator("review_scopes")
    @classmethod
    def unique_scopes(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Each explicitly selected review scope must occur once.")
        return tuple(sorted(values))


class AuthoringReviewItem(HandoffModel):
    governance_status: Literal["draft"] = "draft"
    requires_independent_review: Literal[True] = True
    population_applicability: Literal["not_assessed"] = "not_assessed"

    @field_validator("requires_independent_review", mode="before")
    @classmethod
    def exact_review_flag(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Independent review remains required as a JSON boolean.")
        return value


class BookQuestionAnnotation(AuthoringReviewItem):
    question_id: Identifier
    field: QuestionField
    rule_id: Identifier
    rule_version: Literal["1.0.0"]
    action: Literal["ask_missing", "physician_clarification"]
    candidate_keys: tuple[Identifier, ...] = Field(min_length=1)
    rationale_fa: MeaningfulText


class BookClinicianReviewRequirement(AuthoringReviewItem):
    id: Identifier
    title_fa: MeaningfulText
    reason_fa: MeaningfulText
    candidate_keys: tuple[Identifier, ...] = Field(min_length=1)
    required_information: tuple[MeaningfulText, ...] = Field(min_length=1)
    data_channel: Literal[
        "physician_exam", "reviewed_imaging", "physician_assessment",
        "physician_treatment_record", "physician_outcome_review",
    ]
    assessment_state: Literal["not_represented_in_context_v1"] = "not_represented_in_context_v1"
    requires_physician_review: Literal[True] = True

    @field_validator("requires_physician_review", mode="before")
    @classmethod
    def exact_physician_flag(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("This information requires physician review.")
        return value


class BookQuestionSourceReference(AuthoringReviewItem):
    candidate_key: Identifier
    registry_fact_key: Identifier
    action: Literal["new_fact", "support_existing"]
    title: MeaningfulText
    summary: MeaningfulText
    population: MeaningfulText
    indication: MeaningfulText
    application_conditions: tuple[MeaningfulText, ...] = Field(min_length=1)
    limitations: tuple[MeaningfulText, ...] = Field(min_length=1)
    evidence_scope: Literal[
        "clinical_assessment", "structural_assessment",
        "proposed_mechanism", "historical_evidence_summary",
    ]
    content_sha256: Digest | None = None
    entry_sha256: Digest
    support_scope: Literal["location_component_only"] | None = None
    target_base_fact_content_sha256: Digest | None = None
    source: KnowledgeSourceCreate
    provenance: BookDraftProvenance

    @field_validator("provenance", mode="before")
    @classmethod
    def exact_provenance_review_flag(cls, value):
        raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        if isinstance(raw, Mapping) and "requires_independent_review" in raw:
            cls.exact_review_flag(raw["requires_independent_review"])
        return value

    @model_validator(mode="after")
    def distinguish_supporting_reference(self):
        if self.action == "support_existing":
            if (self.content_sha256 is not None or self.support_scope != "location_component_only"
                    or self.target_base_fact_content_sha256 is None):
                raise ValueError("Location support has no new Registry content hash and must identify its target hash.")
        elif (self.content_sha256 is None or self.support_scope is not None
              or self.target_base_fact_content_sha256 is not None):
            raise ValueError("A new Draft reference must carry its own Registry content hash.")
        return self


class BookQuestionPreview(HandoffModel):
    schema_id: Literal["4b-mos.book-question-preview"] = "4b-mos.book-question-preview"
    schema_version: Literal["1.0.0"] = "1.0.0"
    review_scopes: tuple[ReviewScope, ...]
    request_sha256: Digest
    base_pack_manifest_sha256: Digest
    supplement_manifest_sha256: Digest
    page_review_bundle_sha256: Digest
    rules_sha256: Digest
    baseline: OrthopedicQuestionResult
    question_annotations: tuple[BookQuestionAnnotation, ...] = ()
    clinician_review_requirements: tuple[BookClinicianReviewRequirement, ...] = ()
    source_references: tuple[BookQuestionSourceReference, ...] = ()
    review_reasons: tuple[str, ...]
    result_sha256: Digest
    governance_status: Literal["draft"] = "draft"
    review_only: Literal[True] = True
    requires_independent_review: Literal[True] = True
    registry_write_performed: Literal[False] = False
    is_clinically_validated: Literal[False] = False
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False
    safety_engine_required: Literal[True] = True
    safety_evaluation: Literal["not_performed"] = "not_performed"
    approved_fact_count: Literal[0] = 0

    @field_validator("approved_fact_count", mode="before")
    @classmethod
    def exact_zero_approved(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("The authoring preview has zero approved facts.")
        return value

    @field_validator("review_only", "requires_independent_review", "registry_write_performed",
                     "is_clinically_validated", "is_diagnosis", "is_recommendation",
                     "is_clinical_clearance", "authorizes_treatment", "safety_engine_required", mode="before")
    @classmethod
    def exact_governance_flags(cls, value, info):
        expected = info.field_name in {"review_only", "requires_independent_review", "safety_engine_required"}
        if type(value) is not bool or value is not expected:
            raise ValueError("Book question preview governance flags must be exact JSON booleans.")
        return value

    @model_validator(mode="after")
    def reference_integrity(self):
        sources = {item.candidate_key for item in self.source_references}
        if len(sources) != len(self.source_references):
            raise ValueError("Duplicate book source candidate reference.")
        questions = {item.question.id: item for item in self.baseline.question_candidates}
        annotation_ids = set()
        used = set()
        for annotation in self.question_annotations:
            original = questions.get(annotation.question_id)
            if (original is None or original.field != annotation.field
                    or original.action != annotation.action or original.rule_id != annotation.rule_id
                    or original.rule_version != annotation.rule_version):
                raise ValueError("A book annotation must preserve an existing returned question candidate.")
            if annotation.question_id in annotation_ids:
                raise ValueError("Duplicate annotation for one existing question.")
            annotation_ids.add(annotation.question_id)
            used.update(annotation.candidate_keys)
        card_ids = [item.id for item in self.clinician_review_requirements]
        if len(card_ids) != len(set(card_ids)):
            raise ValueError("Duplicate clinician review requirement.")
        for card in self.clinician_review_requirements:
            used.update(card.candidate_keys)
        if used != sources:
            raise ValueError("Book references must resolve and exactly match used annotations and review cards.")
        if self.baseline.body_region != "knee" and (annotation_ids or card_ids or sources):
            raise ValueError("Book knee content cannot be attached outside the confirmed knee scope.")
        return self
