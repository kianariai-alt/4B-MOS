"""Read-only source-linked authoring preview for the Clinical Integration team.

Draft propositions are deliberately separate from Integration's approved-only
KnowledgeReference. Nothing here constructs CoreFinding or invokes a model.
"""
import hashlib
from pathlib import Path

from backend.app.schemas.orthopedic_adapter import (
    AssessmentRequirement, DifferentialKnowledgeReference, OrthopedicDecisionKnowledge,
    OrthopedicEvidenceReference, OrthopedicSourceReference,
)
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack, content_digest
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext
from backend.app.services.orthopedic_knowledge import load_knee_pack, validate_knee_pack
from backend.app.services.orthopedic_questions import select_questions


def build_decision_knowledge(
    context: OrthopedicQuestionContext, pack: KneeKnowledgePack | None = None,
) -> OrthopedicDecisionKnowledge:
    pack = load_knee_pack() if pack is None else validate_knee_pack(pack)
    questions = select_questions(context, pack)
    in_scope = context.body_region == "knee"
    # Canonical lexical order is an inventory order, never a diagnostic rank.
    definitions = sorted(pack.differentials, key=lambda item: item.id) if in_scope else []
    facts = sorted(pack.facts, key=lambda item: item.fact.fact_key) if in_scope else []
    evidence = tuple(OrthopedicEvidenceReference(
        fact_key=item.fact.fact_key, version=item.version,
        content_sha256=item.content_sha256, statement=item.summary,
        population=item.fact.population, application_conditions=item.application_conditions,
        evidence_grade=item.fact.evidence_grade, limitations=item.limitations,
        source_keys=item.source_keys,
    ) for item in facts)
    source_keys = {key for item in evidence for key in item.source_keys}
    sources = tuple(OrthopedicSourceReference(
        source_key=item.source_key, title=item.source.title, url=item.source.url,
        doi=item.source.doi, source_version=item.source.guideline_version,
        source_sha256=content_digest(item.model_dump(mode="json")),
        access_level=item.access_level, verification_note=item.verification_note,
    ) for item in sorted(pack.sources, key=lambda item: item.source_key)
        if item.source_key in source_keys)
    payload = dict(
        body_region=context.body_region, context_sha256=questions.context_sha256,
        pack_key=pack.pack_key, pack_version=pack.pack_version,
        pack_manifest_sha256=pack.manifest_sha256,
        adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        question_rules_sha256=questions.rules_sha256,
        structured_symptoms=questions.structured_symptoms,
        examination_findings=questions.examination_findings,
        imaging_findings=questions.reviewed_imaging_findings,
        unverified_findings=questions.unverified_findings,
        differential_knowledge_references=tuple(DifferentialKnowledgeReference(definition=item)
                                                 for item in definitions),
        evidence_references=evidence, source_references=sources,
        information_gaps=questions.information_gaps,
        question_candidates=questions.question_candidates,
        assessment_requirements=tuple(AssessmentRequirement(
            differential_id=item.id, requirements=item.assessment_requirements,
            fact_keys=item.fact_keys,
        ) for item in definitions),
        review_reasons=tuple(dict.fromkeys((
            "draft_knowledge_requires_independent_review",
            "existing_safety_engine_not_evaluated_by_preview",
            *questions.review_reasons,
        ))),
        result_sha256="0" * 64,
    )
    result = OrthopedicDecisionKnowledge(**payload)
    return result.model_copy(update={"result_sha256": content_digest(
        result.model_dump(mode="json", exclude={"result_sha256"})
    )})
