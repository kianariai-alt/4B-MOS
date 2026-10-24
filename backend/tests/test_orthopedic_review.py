"""Adversarial trust-boundary checks; no clinical validation or patient data."""

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext, StructuredAnswer
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError
from backend.app.services.orthopedic_adapter import build_decision_knowledge
from backend.app.services.orthopedic_knowledge import load_knee_pack


def _finding(field, value, *, state="confirmed", source="synthetic:reviewed"):
    return StructuredAnswer(
        field=field, state=state, value=value, source_ref=source,
        provenance="reviewed_imaging" if field.startswith("imaging_") else "physician_exam",
    )


def test_agreement_does_not_promote_an_unverified_source():
    confirmed = _finding("exam_effusion", True)
    uncertain = _finding("exam_effusion", True, state="unverified", source="synthetic:uncertain")
    result = build_decision_knowledge(OrthopedicQuestionContext(
        body_region="knee", observations=(confirmed, uncertain),
    ))

    # A usable independent source may remain usable. Agreement alone must not
    # change the provenance or review state of the other source.
    assert result.examination_findings == (confirmed,)
    assert result.unverified_findings == (uncertain,)
    assert uncertain.state == "unverified"


def test_conflicting_unverified_imaging_quarantines_the_confirmed_source():
    confirmed = _finding("imaging_cartilage_lesion", True)
    uncertain = _finding("imaging_cartilage_lesion", False, state="unverified", source="synthetic:uncertain")
    result = build_decision_knowledge(OrthopedicQuestionContext(
        body_region="knee", observations=(confirmed, uncertain),
    ))

    assert result.imaging_findings == ()
    assert result.unverified_findings == (confirmed, uncertain)
    assert result.structured_symptoms == ()
    assert any(g.field == "imaging_cartilage_lesion" and g.reason == "contradictory"
               for g in result.information_gaps)


@pytest.mark.parametrize("target", ["fact_source", "source_catalog"])
def test_nested_source_mutation_cannot_reuse_a_previously_valid_pack(target):
    pack = load_knee_pack()
    if target == "fact_source":
        pack.facts[0].fact.sources[0].doi = "10.0000/unverified-substitution"
    else:
        pack.sources[0].source.url = "https://example.test/substituted-source"

    with pytest.raises((ValidationError, MedicalKnowledgeIntegrityError)):
        build_decision_knowledge(OrthopedicQuestionContext(body_region="knee"), pack)


def test_constructed_unreviewed_imaging_cannot_bypass_the_schema_boundary():
    # model_construct deliberately bypasses Pydantic validation. The public
    # service boundary must revalidate even trusted in-process callers.
    forged = StructuredAnswer.model_construct(
        field="imaging_kl_grade", state="confirmed", value=4,
        provenance="unreviewed_imaging", source_ref="synthetic:forged",
    )
    context = OrthopedicQuestionContext.model_construct(body_region="knee", observations=(forged,))
    with pytest.raises(ValidationError):
        build_decision_knowledge(context)


def test_source_metadata_hash_is_not_claimed_as_document_bytes_or_approval():
    result = build_decision_knowledge(OrthopedicQuestionContext(body_region="knee"))
    assert result.source_references
    assert all(ref.hash_scope == "source_reference_metadata" for ref in result.source_references)
    assert all(ref.content_hash_scope == "registry_fact_content_with_metadata"
               and ref.approved_content_sha256 is None
               and ref.usable_as_approved_knowledge is False
               for ref in result.evidence_references)
    assert result.approved_fact_count == 0
    assert result.safety_evaluation == "not_performed"
