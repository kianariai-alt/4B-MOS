from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


KnowledgeFactStatus = Literal[
    "draft",
    "in_review",
    "approved",
    "rejected",
    "retired",
]

KnowledgeEvidenceGrade = Literal[
    "high",
    "moderate",
    "low",
    "very_low",
    "consensus",
    "ungraded",
]

KnowledgeTherapyType = Literal[
    "PRP",
    "PRGF",
    "ACS",
    "PL",
    "SVF",
    "EXOSOME",
    "MSC",
]

KnowledgeSourceType = Literal[
    "guideline",
    "systematic_review",
    "randomized_trial",
    "observational_study",
    "regulatory",
    "consensus",
    "textbook",
    "other",
]


class KnowledgeSourceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_type: KnowledgeSourceType
    title: str = Field(min_length=3, max_length=500)
    citation: str = Field(min_length=3, max_length=5000)
    publisher: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    doi: str | None = Field(default=None, max_length=255)
    publication_date: date | None = None
    guideline_version: str | None = Field(default=None, max_length=100)
    accessed_at: date = Field(default_factory=date.today)

    @field_validator(
        "publisher",
        "url",
        "doi",
        "guideline_version",
        mode="after",
    )
    @classmethod
    def empty_strings_are_none(cls, value: str | None) -> str | None:
        return value or None


class KnowledgeFactContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=300)
    statement: str = Field(min_length=20, max_length=20000)
    clinical_domain: str = Field(min_length=2, max_length=100)
    therapy_type: KnowledgeTherapyType | None = None
    population: str | None = Field(default=None, max_length=5000)
    indication: str | None = Field(default=None, max_length=5000)
    contraindications: list[str] = Field(
        default_factory=list,
        max_length=50,
    )
    evidence_grade: KnowledgeEvidenceGrade
    valid_from: date | None = None
    valid_to: date | None = None
    sources: list[KnowledgeSourceCreate] = Field(
        min_length=1,
        max_length=20,
    )

    @field_validator("population", "indication", mode="after")
    @classmethod
    def optional_empty_strings_are_none(
        cls,
        value: str | None,
    ) -> str | None:
        return value or None

    @field_validator("contraindications", mode="after")
    @classmethod
    def clean_contraindications(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip()
            if not normalized:
                raise ValueError("Contraindications cannot contain empty values.")
            key = normalized.casefold()
            if key not in seen:
                cleaned.append(normalized)
                seen.add(key)
        return cleaned

    @model_validator(mode="after")
    def validate_validity_window(self):
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to cannot be earlier than valid_from.")
        return self


class KnowledgeFactCreate(KnowledgeFactContent):
    fact_key: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )

    @field_validator("fact_key", mode="after")
    @classmethod
    def normalize_fact_key(cls, value: str) -> str:
        return value.upper()


class KnowledgeFactSupersede(KnowledgeFactContent):
    pass


class KnowledgeFactUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=3, max_length=300)
    statement: str | None = Field(
        default=None,
        min_length=20,
        max_length=20000,
    )
    clinical_domain: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
    )
    therapy_type: KnowledgeTherapyType | None = None
    population: str | None = Field(default=None, max_length=5000)
    indication: str | None = Field(default=None, max_length=5000)
    contraindications: list[str] | None = Field(default=None, max_length=50)
    evidence_grade: KnowledgeEvidenceGrade | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    sources: list[KnowledgeSourceCreate] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_null_for_required_content(self):
        required_fields = {
            "title",
            "statement",
            "clinical_domain",
            "contraindications",
            "evidence_grade",
            "sources",
        }
        null_fields = [
            name
            for name in required_fields & self.model_fields_set
            if getattr(self, name) is None
        ]
        if null_fields:
            raise ValueError(
                "These fields cannot be null: " + ", ".join(sorted(null_fields))
            )
        return self

    @field_validator("contraindications", mode="after")
    @classmethod
    def clean_contraindications(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip()
            if not normalized:
                raise ValueError("Contraindications cannot contain empty values.")
            key = normalized.casefold()
            if key not in seen:
                cleaned.append(normalized)
                seen.add(key)
        return cleaned


class KnowledgeFactReview(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_rejection_comment(self):
        if self.decision == "rejected" and not self.comment:
            raise ValueError("A review comment is required when rejecting a fact.")
        return self


class KnowledgeSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sort_order: int
    source_type: KnowledgeSourceType
    title: str
    citation: str
    publisher: str | None
    url: str | None
    doi: str | None
    publication_date: date | None
    guideline_version: str | None
    accessed_at: date
    created_at: datetime


class KnowledgeFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    status: KnowledgeFactStatus
    content_sha256: str
    supersedes_fact_id: str | None
    created_by_user_id: str
    submitted_at: datetime | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    review_comment: str | None
    valid_from: date | None
    valid_to: date | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    sources: list[KnowledgeSourceRead]
