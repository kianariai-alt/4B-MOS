"""Read-only imaging references from the existing Medical Knowledge Registry.

No patient data, medical content, authoring or approval workflow lives here.
The production reader delegates integrity verification to MedicalKnowledgeService.
An injected reader is a trusted testing boundary and must provide equally verified
registry records; a syntactically valid hash alone never verifies their content.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Any


KNOWLEDGE_REFERENCES_VERSION = "1.0.0"
IMAGING_KNOWLEDGE_DOMAINS = ("imaging_knee_xray", "imaging_knee_mri")
MAX_KNOWLEDGE_FACTS = 2000
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid registry reference identifier.")
    return value


@dataclass(frozen=True, slots=True)
class ImagingKnowledgeFactReference:
    fact_id: str
    fact_key: str
    version: int
    content_sha256: str
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id, "fact_key": self.fact_key,
            "version": self.version, "content_sha256": self.content_sha256,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True, slots=True)
class ImagingKnowledgeReferences:
    """One processor's reference snapshot, not the PR #43 pack manifest."""

    as_of: date
    clinical_domain: str
    facts: tuple[ImagingKnowledgeFactReference, ...]
    references_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": KNOWLEDGE_REFERENCES_VERSION,
            "as_of": self.as_of.isoformat(),
            "clinical_domain": self.clinical_domain,
            "readiness": "references_available" if self.facts else "empty",
            "approved_fact_count": len(self.facts),
            "facts": [fact.to_dict() for fact in self.facts],
            "references_sha256": self.references_sha256,
            "patient_applicability": "not_assessed",
            "is_diagnosis": False,
            "is_recommendation": False,
            "is_clinical_validation": False,
        }


def _build_references(
    *, facts: Iterable[Any], domain: str, as_of: date,
) -> ImagingKnowledgeReferences:
    """Minimize already integrity-verified registry records into references.

    This adds conservative envelope checks; it cannot recompute the Registry's
    content digest from references alone. Callers must use verified reads, as
    ImagingKnowledgeRegistryAdapter does by default. Nothing is approved here.
    """
    if type(as_of) is not date:
        raise ValueError("A registry evaluation date is required.")
    if domain not in IMAGING_KNOWLEDGE_DOMAINS:
        raise ValueError("Knowledge must match an exact imaging domain.")
    references: list[ImagingKnowledgeFactReference] = []
    seen_ids: set[str] = set()
    seen_versions: set[tuple[str, int]] = set()
    for index, fact in enumerate(facts):
        if index >= MAX_KNOWLEDGE_FACTS:
            raise ValueError("Imaging knowledge reference limit exceeded.")
        if getattr(fact, "status", None) != "approved":
            raise ValueError("Only approved registry knowledge can be referenced.")
        if getattr(fact, "clinical_domain", None) != domain:
            raise ValueError("Knowledge must match an exact imaging domain.")
        valid_from, valid_to = getattr(fact, "valid_from", None), getattr(fact, "valid_to", None)
        if any(value is not None and type(value) is not date for value in (valid_from, valid_to)):
            raise ValueError("Invalid registry knowledge validity window.")
        if ((valid_from is not None and valid_from > as_of)
                or (valid_to is not None and valid_to < as_of)
                or (valid_from is not None and valid_to is not None and valid_to < valid_from)):
            raise ValueError("Registry knowledge is outside its validity window.")
        reviewer = getattr(fact, "reviewed_by_user_id", None)
        if (not reviewer or not isinstance(getattr(fact, "reviewed_at", None), datetime)
                or reviewer == getattr(fact, "created_by_user_id", None)):
            raise ValueError("Independent registry review attribution is required.")
        fact_id, fact_key = _identifier(getattr(fact, "id", None)), _identifier(getattr(fact, "fact_key", None))
        version = getattr(fact, "version", None)
        content_sha256 = getattr(fact, "content_sha256", None)
        if type(version) is not int or version < 1:
            raise ValueError("Invalid registry knowledge version.")
        if not isinstance(content_sha256, str) or not _DIGEST.fullmatch(content_sha256):
            raise ValueError("Invalid registry content digest.")
        if fact_id in seen_ids or (fact_key, version) in seen_versions:
            raise ValueError("Duplicate registry knowledge reference.")
        source_ids = tuple(sorted(_identifier(getattr(source, "id", None))
                                  for source in getattr(fact, "sources", ())))
        if not source_ids or len(source_ids) > 20 or len(set(source_ids)) != len(source_ids):
            raise ValueError("Invalid registry source references.")
        seen_ids.add(fact_id)
        seen_versions.add((fact_key, version))
        references.append(ImagingKnowledgeFactReference(
            fact_id, fact_key, version, content_sha256, source_ids,
        ))
    references.sort(key=lambda item: (item.fact_key, item.version, item.fact_id))
    references_digest = _digest({
        "schema_version": KNOWLEDGE_REFERENCES_VERSION,
        "as_of": as_of.isoformat(), "clinical_domain": domain,
        "facts": [item.to_dict() for item in references],
    })
    return ImagingKnowledgeReferences(as_of, domain, tuple(references), references_digest)


class ImagingKnowledgeRegistryAdapter:
    """Collect references using a caller-owned session; never opens a database.

    The default callable is imported only during collect(), keeping offline
    readers/tests independent of FastAPI, settings, SQLAlchemy and any database.
    Authorization remains the responsibility of the existing Registry caller.
    No authoring, review, approval, migration or source-content mutation occurs.
    """

    def __init__(self, list_approved: Callable[..., Any] | None = None, *, page_size: int = 200):
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("Registry page size must be between 1 and 200.")
        self._list_approved = list_approved
        self._page_size = page_size

    def collect(self, db: Any, *, domain: str, as_of: date) -> ImagingKnowledgeReferences:
        if type(as_of) is not date:
            raise ValueError("A registry evaluation date is required.")
        if domain not in IMAGING_KNOWLEDGE_DOMAINS:
            raise ValueError("Knowledge must match an exact imaging domain.")
        reader = self._list_approved
        if reader is None:
            from backend.app.services.medical_knowledge import MedicalKnowledgeService
            reader = MedicalKnowledgeService.list_approved
        facts = []
        offset = 0
        while True:
            page = reader(db, as_of=as_of, clinical_domain=domain,
                          skip=offset, limit=self._page_size)
            if not isinstance(page, (list, tuple)) or len(page) > self._page_size:
                raise ValueError("Invalid registry response page.")
            if any(getattr(fact, "clinical_domain", None) != domain for fact in page):
                raise ValueError("Registry response crossed an imaging domain.")
            facts.extend(page)
            if len(facts) > MAX_KNOWLEDGE_FACTS:
                raise ValueError("Imaging knowledge reference limit exceeded.")
            if len(page) < self._page_size:
                break
            offset += self._page_size
        return _build_references(facts=facts, domain=domain, as_of=as_of)
