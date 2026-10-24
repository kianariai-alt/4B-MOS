"""Additive book authoring metadata; never an approved or runtime knowledge core.

The frozen base knee pack and shared Integration contracts are unchanged. Source
text stays private: this supplement carries manually authored paraphrases,
citations, page hashes and pending-review provenance only.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.medical_knowledge import KnowledgeSourceCreate
from backend.app.schemas.orthopedic_book_handoff import (
    BookDraftPageProvenance,
    BookDraftPreview,
    BookDraftProvenance,
    BookSourceHandoff,
    Digest,
    HandoffModel,
)
from backend.app.schemas.orthopedic_knowledge import canonical_json


Identifier = Annotated[str, Field(strict=True, min_length=3, max_length=100)]
MeaningfulText = Annotated[str, Field(strict=True, min_length=1, max_length=5000)]
AUTHORING_MARKER = "\n\nBook authoring metadata v1:\n"


class BaseFactReference(HandoffModel):
    fact_key: Identifier
    version: Literal[1] = 1
    content_sha256: Digest

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("The base fact version must be the integer one.")
        return value


class BookReviewEntry(HandoffModel):
    candidate_key: Identifier
    action: Literal["new_fact", "support_existing"]
    registry_fact_key: Identifier
    title: str = Field(strict=True, min_length=3, max_length=300)
    summary: str = Field(strict=True, min_length=20, max_length=5000)
    population: MeaningfulText
    indication: MeaningfulText
    topic: Literal["osteoarthritis", "meniscus", "cartilage_osteochondral", "safety", "orthobiologics", "examination"]
    application_conditions: tuple[MeaningfulText, ...] = Field(min_length=1)
    limitations: tuple[MeaningfulText, ...] = Field(min_length=1)
    evidence_scope: Literal[
        "clinical_assessment", "structural_assessment",
        "proposed_mechanism", "historical_evidence_summary",
    ]
    related_facts: tuple[BaseFactReference, ...] = ()
    source: KnowledgeSourceCreate
    provenance: BookDraftProvenance
    page_review_bundle_sha256: Digest
    text_alignment_review_date: date
    text_alignment_observation: Literal["ai_assisted_selected_text_checked"] = "ai_assisted_selected_text_checked"
    printed_page_method: Literal[
        "extracted_header_and_adjacent_pages",
        "reconstructed_split_header_and_adjacent_pages",
    ]
    therapy_type: Literal["PRP"] | None = None
    support_scope: Literal["location_component_only"] | None = None
    draft_preview: BookDraftPreview | None = None

    @field_validator("source", mode="before")
    @classmethod
    def explicit_source_access_date(cls, value):
        if isinstance(value, Mapping):
            explicit = "accessed_at" in value
        else:
            explicit = "accessed_at" in getattr(value, "model_fields_set", set())
        if not explicit:
            raise ValueError("The book source access date must be explicitly supplied.")
        return value

    @field_validator("provenance", "draft_preview", mode="before")
    @classmethod
    def strict_nested_governance(cls, value):
        if value is None:
            return value
        raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        if isinstance(raw, Mapping):
            nested = raw.get("provenance")
            for scope in (raw, nested) if isinstance(nested, Mapping) else (raw,):
                for key, expected in (("requires_independent_review", True),
                                      ("registry_write_performed", False),
                                      ("is_clinically_validated", False)):
                    if key in scope and (type(scope[key]) is not bool or scope[key] is not expected):
                        raise ValueError("Review governance flags must be exact JSON booleans.")
            if "version" in raw and (type(raw["version"]) is not int or raw["version"] != 1):
                raise ValueError("The Draft preview version must be the integer one.")
        return value

    @model_validator(mode="after")
    def entry_boundaries(self):
        values = (self.title, self.summary, self.population, self.indication,
                  *self.application_conditions, *self.limitations)
        if any(not value.strip() for value in values):
            raise ValueError("Book review text cannot be blank.")
        if AUTHORING_MARKER in self.summary or "\n\nBook Draft provenance v1:\n" in self.summary:
            raise ValueError("A summary cannot contain nested authoring or provenance metadata.")
        if self.source.source_type != "textbook":
            raise ValueError("A reviewed book entry requires a textbook citation.")
        if not self.source.doi and not self.source.guideline_version:
            raise ValueError("A book citation needs a DOI or an explicitly identified edition.")
        if self.provenance.proposal_origin != "ai_assisted_draft":
            raise ValueError("This text-alignment review remains AI-assisted Draft authoring.")
        keys = [item.fact_key for item in self.related_facts]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate related base-fact reference.")
        if self.action == "support_existing":
            if self.support_scope != "location_component_only" or self.registry_fact_key not in keys:
                raise ValueError("Supporting evidence must identify the existing location component and target reference.")
            if self.registry_fact_key != "KNEE.CARTILAGE.CLASSIFICATION":
                raise ValueError("The v1 location-component support must target KNEE.CARTILAGE.CLASSIFICATION.")
            if self.draft_preview is not None:
                raise ValueError("Supporting evidence cannot expose a new or replacement Registry payload.")
        elif self.support_scope is not None:
            raise ValueError("A new fact cannot claim an existing-fact supporting scope.")
        if self.draft_preview is not None and self.draft_preview.provenance != self.provenance:
            raise ValueError("Draft and entry provenance must match exactly.")
        return self

    def authoring_metadata(self) -> dict:
        return self.model_dump(mode="json", exclude={"source", "provenance", "draft_preview"})

    def authoring_statement(self) -> str:
        """Bind scope, limitations, hypothesis status and base references first."""
        return self.summary + AUTHORING_MARKER + canonical_json(self.authoring_metadata())


class KneeBookReviewPack(HandoffModel):
    schema_id: Literal["4b-mos.knee-book-review"] = "4b-mos.knee-book-review"
    schema_version: Literal["1.0.0"] = "1.0.0"
    pack_key: Literal["knee_book_review_v1"] = "knee_book_review_v1"
    pack_version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    clinical_domain: Literal["orthopedics_knee"] = "orthopedics_knee"
    base_pack_manifest_sha256: Digest
    page_review_bundle_sha256: Digest
    text_alignment_review_date: date
    source_handoff: BookSourceHandoff
    reviewed_pages: tuple[BookDraftPageProvenance, ...] = Field(min_length=1, max_length=40)
    entries: tuple[BookReviewEntry, ...] = Field(min_length=1, max_length=9)
    manifest_sha256: Digest
    contains_book_text: Literal[False] = False
    registry_write_performed: Literal[False] = False
    is_clinically_validated: Literal[False] = False
    requires_independent_review: Literal[True] = True
    runtime_use: Literal["authoring_only"] = "authoring_only"

    @field_validator("pack_version", mode="before")
    @classmethod
    def exact_pack_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("The review pack version must be the integer one.")
        return value

    @field_validator("contains_book_text", "registry_write_performed", "is_clinically_validated",
                     "requires_independent_review", mode="before")
    @classmethod
    def strict_governance(cls, value, info):
        expected = info.field_name == "requires_independent_review"
        if type(value) is not bool or value is not expected:
            raise ValueError("Review pack governance flags must be exact JSON booleans.")
        return value

    @model_validator(mode="after")
    def pack_references(self):
        candidate_keys = [entry.candidate_key for entry in self.entries]
        registry_keys = [entry.registry_fact_key for entry in self.entries]
        if len(candidate_keys) != len(set(candidate_keys)) or len(registry_keys) != len(set(registry_keys)):
            raise ValueError("Duplicate candidate or Registry fact key in review pack.")
        source_keys = {item.source_file_sha256 for item in self.source_handoff.sources}
        page_keys = [(page.source_file_sha256, page.pdf_page_number) for page in self.reviewed_pages]
        if len(page_keys) != len(set(page_keys)):
            raise ValueError("Duplicate reviewed source/page reference.")
        if any(page.source_file_sha256 not in source_keys for page in self.reviewed_pages):
            raise ValueError("A reviewed page references an unknown source.")
        for entry in self.entries:
            if entry.page_review_bundle_sha256 != self.page_review_bundle_sha256:
                raise ValueError("Entry and pack must bind the same private page review bundle.")
            if entry.text_alignment_review_date != self.text_alignment_review_date:
                raise ValueError("Entry and pack text-alignment review dates differ.")
            if entry.action == "new_fact" and entry.draft_preview is None:
                raise ValueError("Each new-fact entry requires a bound Draft preview.")
        return self
