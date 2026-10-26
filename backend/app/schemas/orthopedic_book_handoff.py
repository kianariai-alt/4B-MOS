"""Authoring-only book provenance; byte integrity is not clinical validation.

These contracts carry metadata and page hashes, never page text, patient data,
approval, or a Registry write command. Bibliographic identity and whether a
source supports a proposed claim remain independent review tasks.
"""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from backend.app.schemas.medical_knowledge import KnowledgeFactCreate

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
PositivePageNumber = Annotated[int, Field(strict=True, gt=0)]
NonnegativeCount = Annotated[int, Field(strict=True, ge=0)]
ProposalOrigin = Literal["human_authored", "ai_assisted_draft"]


class HandoffModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BookHandoffSource(HandoffModel):
    source_file_sha256: Digest
    filename: str = Field(strict=True, min_length=1, max_length=500)
    source_pdf_verified: StrictBool
    pages_artifact_sha256: Digest
    verification_error: str | None = Field(default=None, strict=True, min_length=1, max_length=2000)

    @field_validator("filename")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if (
            not value.strip()
            or value in {".", ".."}
            or PurePosixPath(value).name != value
            or PureWindowsPath(value).name != value
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("Book filename must be a basename without a path or control characters.")
        return value

    @field_validator("verification_error")
    @classmethod
    def meaningful_error(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("A verification error cannot be blank.")
        return value

    @model_validator(mode="after")
    def consistent_verification(self):
        if self.source_pdf_verified and self.verification_error is not None:
            raise ValueError("A verified source cannot also have a verification error.")
        return self


class BookHandoffPage(HandoffModel):
    source_file_sha256: Digest
    pdf_page_number: PositivePageNumber
    text_sha256: Digest
    status: Literal[
        "text_extracted",
        "empty_text_requires_ocr_or_manual_review",
        "page_extraction_error",
    ]


class BookSourceHandoff(HandoffModel):
    """Hash-bound export scope and technical provenance, including omissions.

    verifier_artifact_sha256 hashes canonical compact JSON containing
    handoff_tool_sha256 (the wrapper source hash) and snapshot_verifier_sha256
    (the currently imported local_orthopedic_library.py source hash).
    """

    schema_id: Literal["4b-mos.book-source-handoff"]
    schema_version: Literal["1.0.0"]
    scope: Literal["available_extracted_pages", "selected_extracted_pages"]
    omitted_entry_count: NonnegativeCount
    unresolved_entry_count: NonnegativeCount
    traversal_error_count: NonnegativeCount
    extraction_manifest_sha256: Digest
    verifier_artifact_sha256: Digest
    sources: tuple[BookHandoffSource, ...] = Field(min_length=1, max_length=1000)
    pages: tuple[BookHandoffPage, ...] = Field(max_length=100000)
    uploads_performed: Literal[False]
    is_clinically_validated: Literal[False]
    registry_write_performed: Literal[False]
    handoff_sha256: Digest

    @field_validator("uploads_performed", "is_clinically_validated", "registry_write_performed", mode="before")
    @classmethod
    def false_flags_are_booleans(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("Handoff governance flags must be the JSON boolean false.")
        return value

    @model_validator(mode="after")
    def references_and_duplicates(self):
        sources = {item.source_file_sha256 for item in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("Duplicate source-file hash in handoff.")
        page_keys = [(page.source_file_sha256, page.pdf_page_number) for page in self.pages]
        if len(page_keys) != len(set(page_keys)):
            raise ValueError("Duplicate source/page reference in handoff.")
        if any(page.source_file_sha256 not in sources for page in self.pages):
            raise ValueError("A handoff page references an unknown book source.")
        return self


class BookPageReference(HandoffModel):
    source_file_sha256: Digest
    pdf_page_number: PositivePageNumber


class BookDraftPageProvenance(BookPageReference):
    text_sha256: Digest


class BookDraftProvenance(HandoffModel):
    schema_id: Literal["4b-mos.book-draft-provenance"] = "4b-mos.book-draft-provenance"
    schema_version: Literal["1.0.0"] = "1.0.0"
    extraction_manifest_sha256: Digest
    verifier_artifact_sha256: Digest
    handoff_sha256: Digest
    source_file_sha256: Digest
    filename: str
    pages_artifact_sha256: Digest
    pages: tuple[BookDraftPageProvenance, ...] = Field(min_length=1)
    chapter: str = Field(strict=True, min_length=1, max_length=1000)
    reported_printed_pages: str | None = Field(default=None, strict=True, min_length=1, max_length=1000)
    printed_page_verification: Literal["unverified"] = "unverified"
    proposal_origin: ProposalOrigin
    source_pdf_verification_scope: Literal["technical_bytes_only"] = "technical_bytes_only"
    bibliographic_identity_review: Literal["pending"] = "pending"
    clinical_source_review: Literal["pending"] = "pending"
    source_entailment_review: Literal["pending"] = "pending"
    requires_independent_review: Literal[True] = True

    @field_validator("chapter", "reported_printed_pages")
    @classmethod
    def meaningful_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Chapter and reported printed pages cannot be blank.")
        return value


class BookDraftPreview(HandoffModel):
    """A proposed Registry payload for inspection, never a saved Registry fact."""

    proposal: KnowledgeFactCreate
    provenance: BookDraftProvenance
    version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    content_sha256: Digest
    proposal_origin: ProposalOrigin
    clinical_source_review: Literal["pending"] = "pending"
    requires_independent_review: Literal[True] = True
    registry_write_performed: Literal[False] = False
    is_clinically_validated: Literal[False] = False
