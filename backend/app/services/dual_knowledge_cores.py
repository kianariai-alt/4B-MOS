"""Governed-reference inventory for parallel orthopedic and imaging knowledge packs.

This module does not receive images, patient narratives or image URLs. It never
infers findings and never promotes model output into approved medical knowledge.
"""

import hashlib
import json
from datetime import date
from typing import Iterable

from backend.app.schemas.dual_knowledge_cores import (
    DualKnowledgeManifest,
    GovernedFactRef,
    KnowledgePackManifest,
)

# Pack identifiers deliberately map to *exact* governed clinical_domain values.
# New domains need clinical content governance before being made visible here.
CORE_PACKS = (
    ("orthopedics", "knee_clinical", "orthopedics_knee"),
    ("imaging", "knee_xray", "imaging_knee_xray"),
    ("imaging", "knee_mri", "imaging_knee_mri"),
)


def _digest(payload: dict) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def build_pack_manifest(
    *, core: str, pack_key: str, clinical_domain: str, facts: Iterable
) -> KnowledgePackManifest:
    """Fail closed on non-governed content; avoid silently accepting drafts."""
    approved: list[GovernedFactRef] = []
    seen: set[str] = set()
    for fact in facts:
        if fact.status != "approved":
            raise ValueError("Only independently approved knowledge is allowed.")
        if fact.clinical_domain.casefold() != clinical_domain.casefold():
            raise ValueError("A fact belongs to a different knowledge pack.")
        if fact.id in seen:
            raise ValueError("Duplicate knowledge fact identifier.")
        seen.add(fact.id)
        approved.append(
            GovernedFactRef(
                fact_id=fact.id,
                fact_key=fact.fact_key,
                version=fact.version,
                content_sha256=fact.content_sha256,
            )
        )
    approved.sort(key=lambda item: (item.fact_key, item.version, item.fact_id))
    payload = {
        "schema_version": 1,
        "core": core,
        "pack_key": pack_key,
        "clinical_domain": clinical_domain,
        "facts": [item.model_dump(mode="json") for item in approved],
    }
    return KnowledgePackManifest(
        core=core,
        pack_key=pack_key,
        clinical_domain=clinical_domain,
        approved_fact_count=len(approved),
        facts=approved,
        manifest_sha256=_digest(payload),
        readiness="references_available" if approved else "empty",
    )


def build_dual_manifest(*, as_of: date, packs: list[KnowledgePackManifest]) -> DualKnowledgeManifest:
    expected = [(core, name, domain) for core, name, domain in CORE_PACKS]
    actual = [(pack.core, pack.pack_key, pack.clinical_domain) for pack in packs]
    if actual != expected:
        raise ValueError("Knowledge packs must be complete and in canonical order.")
    return DualKnowledgeManifest(
        as_of=as_of,
        packs=packs,
        combined_manifest_sha256=_digest({
            "schema_version": 1,
            "as_of": as_of.isoformat(),
            "packs": [pack.model_dump(mode="json") for pack in packs],
        }),
    )


class DualKnowledgeCoreService:
    @staticmethod
    def get_manifest(db, *, as_of: date) -> DualKnowledgeManifest:
        # Existing MedicalKnowledgeService verifies each fact's content hash and
        # filters by status and validity date before returning approved facts.
        from backend.app.services.medical_knowledge import MedicalKnowledgeService

        packs: list[KnowledgePackManifest] = []
        for core, pack_key, clinical_domain in CORE_PACKS:
            facts = []
            offset = 0
            batch_size = 200
            while True:
                batch = MedicalKnowledgeService.list_approved(
                    db,
                    as_of=as_of,
                    clinical_domain=clinical_domain,
                    skip=offset,
                    limit=batch_size,
                )
                facts.extend(batch)
                if len(batch) < batch_size:
                    break
                offset += batch_size
            packs.append(build_pack_manifest(
                core=core, pack_key=pack_key,
                clinical_domain=clinical_domain, facts=facts,
            ))
        return build_dual_manifest(as_of=as_of, packs=packs)
