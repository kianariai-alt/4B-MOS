"""Validated Draft pack and explicit import into the existing Registry.

This module never approves knowledge, activates safety rules, or touches patient
records. Import is an explicit caller action, never an application startup hook.
"""
from pathlib import Path

from backend.app.repositories.medical_knowledge import MedicalKnowledgeRepository
from backend.app.schemas.medical_knowledge import KnowledgeFactContent, KnowledgeFactRead
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack, content_digest
from backend.app.services.medical_knowledge import (
    AUTHOR_ROLES,
    MedicalKnowledgeConflictError,
    MedicalKnowledgeIntegrityError,
    MedicalKnowledgeService,
    knowledge_content_digest,
)

PACK_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "knee_v1.json"


def validate_knee_pack(pack: KneeKnowledgePack) -> KneeKnowledgePack:
    """Recheck mutable nested Registry models as well as immutable pack metadata."""
    pack = KneeKnowledgePack.model_validate(pack.model_dump(mode="json"))
    for entry in pack.facts:
        content = KnowledgeFactContent.model_validate(entry.fact.model_dump(exclude={"fact_key"}))
        expected = knowledge_content_digest(fact_key=entry.fact.fact_key, version=entry.version, content=content)
        if expected != entry.content_sha256:
            raise MedicalKnowledgeIntegrityError("Draft pack fact content hash mismatch.")
    payload = pack.model_dump(mode="json", exclude={"manifest_sha256"})
    if content_digest(payload) != pack.manifest_sha256:
        raise MedicalKnowledgeIntegrityError("Draft pack manifest hash mismatch.")
    return pack


def load_knee_pack() -> KneeKnowledgePack:
    return validate_knee_pack(KneeKnowledgePack.model_validate_json(PACK_PATH.read_text(encoding="utf-8")))


def import_knee_drafts(db, *, actor) -> tuple[KnowledgeFactRead, ...]:
    """Explicit, rerunnable Draft import; reject edits, supersession or approval.

    Existing Registry.create commits each new fact with its audit record. A
    preflight rejects known conflicts before the first creation, but this is not
    an atomic batch: on a concurrent write or failure a safe rerun resumes only
    matching Drafts. Callers must use a clean session with no pending writes.
    """
    if db.new or db.dirty or db.deleted:
        raise MedicalKnowledgeConflictError("Draft import requires a clean session.")
    MedicalKnowledgeService._require_actor(actor, AUTHOR_ROLES)
    pack = load_knee_pack()
    existing = {}
    for entry in pack.facts:
        row = MedicalKnowledgeRepository.get_latest_by_key(db, entry.fact.fact_key)
        if row is not None:
            read = MedicalKnowledgeService.get(db, row.id)
            if read.status != "draft" or read.version != entry.version or read.content_sha256 != entry.content_sha256:
                raise MedicalKnowledgeConflictError("Existing knowledge differs from the exact Draft pack; review and supersede explicitly.")
            existing[entry.fact.fact_key] = read
    result = []
    for entry in pack.facts:
        read = existing.get(entry.fact.fact_key)
        if read is None:
            read = MedicalKnowledgeService.create(db, entry.fact, actor=actor)
        result.append(read)
    return tuple(result)
