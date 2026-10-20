"""Prepare Registry creation payloads offline; never creates or approves a record."""

from dataclasses import dataclass
import json
from urllib.parse import urlsplit

from backend.app.schemas.medical_knowledge import KnowledgeFactCreate

from .knowledge import IMAGING_KNOWLEDGE_DOMAINS
from .models import canonical_digest


@dataclass(frozen=True)
class RegistryDraft:
    fact_key: str
    payload_json: str
    payload_sha256: str

    def to_dict(self):
        return {"status": "draft", "method": "POST", "route": "/api/v1/knowledge/facts",
                "payload": json.loads(self.payload_json), "payload_sha256": self.payload_sha256,
                "requires_independent_review": True}


def prepare_registry_drafts(pack: dict) -> tuple[RegistryDraft, ...]:
    if (type(pack) is not dict or set(pack) != {"schema_version", "status", "medical_use_permitted", "candidates", "source_review_queue"}
            or pack["schema_version"] != "imaging-drafts-v1" or pack["status"] != "draft"
            or pack["medical_use_permitted"] is not False or type(pack["candidates"]) is not list
            or not 1 <= len(pack["candidates"]) <= 50):
        raise ValueError("Invalid offline draft pack.")
    drafts, seen = [], set()
    for entry in pack["candidates"]:
        if type(entry) is not dict or set(entry) != {"payload", "review_questions", "limitations", "source_locator"}:
            raise ValueError("Invalid draft candidate envelope.")
        payload = entry["payload"]
        if type(payload) is not dict or set(payload) - set(KnowledgeFactCreate.model_fields):
            raise ValueError("Drafts cannot assert status, identity or review attribution.")
        for field in ("review_questions", "limitations"):
            if (type(entry[field]) is not list or not entry[field]
                    or any(type(x) is not str or not 3 <= len(x) <= 5000 for x in entry[field])):
                raise ValueError("Draft review questions and limitations are required.")
        try:
            model = KnowledgeFactCreate.model_validate(payload)
        except Exception:
            raise ValueError("Draft does not satisfy Registry creation schema.") from None
        if model.clinical_domain not in IMAGING_KNOWLEDGE_DOMAINS or model.fact_key in seen:
            raise ValueError("Draft domain or fact key is invalid.")
        if model.evidence_grade != "ungraded":
            raise ValueError("This technical draft pack cannot assert a clinical evidence grade.")
        for source in model.sources:
            parsed = urlsplit(source.url or "")
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or not source.guideline_version):
                raise ValueError("A version-attributed, noncredentialed HTTPS source is required.")
        if entry["source_locator"] not in {source.url for source in model.sources}:
            raise ValueError("Draft locator does not match a cited source.")
        value = model.model_dump(mode="json")
        drafts.append(RegistryDraft(model.fact_key, json.dumps(value, sort_keys=True), canonical_digest(value)))
        seen.add(model.fact_key)
    return tuple(sorted(drafts, key=lambda x: x.fact_key))
