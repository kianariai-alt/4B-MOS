"""Synthetic preview cases; passing software tests is not clinical validation."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext, StructuredAnswer
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_questions import draft_question_bank, select_questions


def answer(field, value=None, *, state="confirmed", provenance=None, source="synthetic:intake-v1"):
    if provenance is None:
        provenance = "physician_exam" if field.startswith("exam_") else "reviewed_imaging" if field.startswith("imaging_") else "patient_report"
    return StructuredAnswer(field=field, state=state, value=value, provenance=provenance, source_ref=source)


def context(*observations, region="knee"):
    return OrthopedicQuestionContext(body_region=region, observations=observations)


def selected(ctx):
    return select_questions(ctx, load_knee_pack())


def candidate_fields(result):
    return {item.field for item in result.question_candidates}


@pytest.mark.parametrize("scenario,ctx,expected", [
    ("gradual_pain_with_functional_limitation", context(
        answer("chief_complaint", "pain"), answer("onset", "gradual"),
        answer("duration", "years"), answer("functional_limitation", "moderate")), "pain_score"),
    ("sports_trauma_with_mechanical_symptoms", context(
        answer("trauma", True), answer("mechanical_locking", True)), "trauma_mechanism"),
    ("incomplete_history", context(answer("duration", state="incomplete")), "duration"),
    ("contradictory_examination", context(
        answer("exam_effusion", True, source="synthetic:exam-a"),
        answer("exam_effusion", False, source="synthetic:exam-b")), "chief_complaint"),
    ("hot_swollen_joint_with_fever", context(answer("fever", True), answer("acute_swelling", True)), "onset"),
    ("unverified_imaging", context(answer("imaging_meniscal_lesion", True,
        state="unverified", provenance="unreviewed_imaging")), "trauma"),
    ("prior_treatments_unclear_response", context(answer("prior_treatment", True),
        answer("treatment_response", "unclear")), "treatment_response"),
    ("outside_knee_domain", context(answer("chief_complaint", "pain"), region="other"), None),
])
def test_eight_synthetic_scenarios(scenario, ctx, expected):
    before = ctx.model_dump(mode="json")
    result = selected(ctx)
    if expected is None:
        assert result.question_candidates == ()
        assert "outside_knee_scope" in result.review_reasons
    else:
        assert expected in candidate_fields(result)
    assert ctx.model_dump(mode="json") == before
    assert result.review_only is True
    assert result.governance_status == "draft"
    assert result.is_diagnosis is result.is_recommendation is result.is_clinical_clearance is False
    assert result.authorizes_treatment is False
    assert result.safety_engine_required is True
    assert all(item.governance_status == "draft" for item in result.question_candidates)
    assert "probability" not in json.dumps(result.model_dump(mode="json"))


def test_valid_answers_including_zero_and_false_are_not_repeated():
    result = selected(context(answer("pain_score", 0), answer("trauma", False), answer("prior_treatment", False)))
    assert not {"pain_score", "trauma", "trauma_mechanism", "prior_treatment", "treatment_response"} & candidate_fields(result)
    assert {item.field for item in result.structured_symptoms} == {"pain_score", "trauma", "prior_treatment"}


@pytest.mark.parametrize("state", ["unknown", "declined"])
def test_unknown_and_declined_remain_gaps_without_automatic_reasking(state):
    result = selected(context(answer("fever", state=state)))
    assert "fever" not in candidate_fields(result)
    assert any(item.field == "fever" and item.reason == state for item in result.information_gaps)
    assert result.unverified_findings[0].state == state


def test_typed_parent_dependency_requires_complete_valid_yes_answer():
    for state in ("unknown", "declined", "incomplete", "contradictory"):
        result = selected(context(answer("trauma", state=state)))
        assert "trauma_mechanism" not in candidate_fields(result)
        assert "neurovascular_symptoms" not in candidate_fields(result)
    assert {"trauma_mechanism", "neurovascular_symptoms"} <= candidate_fields(selected(context(answer("trauma", True))))


@pytest.mark.parametrize("field", ["onset", "pain_location", "treatment_response", "exam_range_of_motion"])
def test_unclear_values_are_quarantined_as_incomplete(field):
    observations = [answer(field, "unclear")]
    if field == "treatment_response":
        observations.append(answer("prior_treatment", True))
    result = selected(context(*observations))
    assert field not in {item.field for item in result.structured_symptoms + result.examination_findings}
    assert any(gap.field == field and gap.reason == "incomplete" for gap in result.information_gaps)
    assert any(item.field == field for item in result.unverified_findings)
    if not field.startswith("exam_"):
        candidate = next(item for item in result.question_candidates if item.field == field)
        assert candidate.action == "physician_clarification"


def test_conflicting_sources_are_preserved_and_excluded_from_usable_findings():
    observations = (answer("exam_effusion", True, source="synthetic:a"),
                    answer("exam_effusion", False, source="synthetic:b"))
    result = selected(context(*observations))
    assert result.examination_findings == ()
    assert result.unverified_findings == observations
    assert "contradictory:exam_effusion" in result.review_reasons
    assert any(gap.field == "exam_effusion" and gap.reason == "contradictory" for gap in result.information_gaps)


def test_conflicting_history_gets_clarification_instead_of_last_write_wins():
    result = selected(context(answer("onset", "sudden", source="synthetic:a"), answer("onset", "gradual", source="synthetic:b")))
    candidate = next(item for item in result.question_candidates if item.field == "onset")
    assert candidate.action == "physician_clarification"
    assert not result.structured_symptoms
    assert len(result.unverified_findings) == 2


def test_reviewed_and_unreviewed_imaging_are_separate_and_do_not_generate_symptoms():
    unverified = answer("imaging_meniscal_lesion", True, state="unverified", provenance="unreviewed_imaging")
    reviewed = answer("imaging_kl_grade", 3)
    result = selected(context(unverified, reviewed))
    assert result.structured_symptoms == result.examination_findings == ()
    assert result.reviewed_imaging_findings == (reviewed,)
    assert result.unverified_findings == (unverified,)
    assert "unverified:imaging_meniscal_lesion" in result.review_reasons
    assert "pain_score" in candidate_fields(result)  # KL never supplies symptom severity.


@pytest.mark.parametrize("observations,reason", [
    ((answer("fever", True), answer("acute_swelling", True)), "draft_hot_joint_information_requires_prompt_physician_review"),
    ((answer("systemic_symptoms", True),), "draft_systemic_symptom_information_requires_physician_review"),
    ((answer("trauma", True), answer("neurovascular_symptoms", True)), "draft_neurovascular_trauma_information_requires_prompt_physician_review"),
    ((answer("trauma", True), answer("mechanical_locking", True)), "draft_traumatic_motion_block_information_requires_physician_review"),
])
def test_risk_information_prompts_review_without_diagnosis_or_safety_clearance(observations, reason):
    result = selected(context(*observations))
    assert reason in result.review_reasons
    assert result.safety_engine_required
    assert result.is_clinical_clearance is False


def test_unverified_positive_risk_information_is_not_silently_suppressed():
    result = selected(context(answer("fever", True, state="unverified"), answer("acute_swelling", True)))
    assert "draft_hot_joint_information_requires_prompt_physician_review" in result.review_reasons
    assert "unverified:fever" in result.review_reasons
    assert "fever" not in {item.field for item in result.structured_symptoms}


def test_no_warning_is_not_safety_clearance():
    result = selected(context(answer("fever", False), answer("acute_swelling", False), answer("systemic_symptoms", False)))
    assert not any(reason.startswith("draft_hot_joint") for reason in result.review_reasons)
    assert result.safety_engine_required and not result.is_clinical_clearance


def test_sources_rules_and_context_are_deterministic_and_traceable():
    ctx = context(answer("onset", "gradual"))
    pack = load_knee_pack()
    first = select_questions(ctx, pack)
    second = select_questions(ctx, pack)
    assert first == second
    assert first.rules_sha256 != first.context_sha256
    assert len(first.rules_sha256) == len(first.context_sha256) == 64
    assert selected(context(answer("onset", "sudden"))).context_sha256 != first.context_sha256
    for candidate in first.question_candidates:
        assert candidate.rule_version == "1.0.0"
        for key, digest in zip(candidate.source_fact_keys, candidate.source_content_sha256s, strict=True):
            assert pack.get_fact(key).content_sha256 == digest


def test_rules_hash_tracks_actual_selector_artifact(monkeypatch):
    pack = load_knee_pack()
    ctx = context()
    before = select_questions(ctx, pack).rules_sha256
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"different-selector-artifact")
    assert select_questions(ctx, pack).rules_sha256 != before


def test_mutated_pack_is_rejected_before_selection():
    pack = load_knee_pack()
    pack.facts[0].fact.title = "Modified without updating source bound digest"
    with pytest.raises(MedicalKnowledgeIntegrityError):
        select_questions(context(), pack)


def test_existing_bank_contract_is_reused_without_creating_an_approved_bank():
    bank = draft_question_bank()
    assert bank.questions[0].id == "knee.chief_complaint"
    follow_up = next(item for item in bank.questions if item.id == "knee.trauma_mechanism")
    assert follow_up.depends_on_id == "knee.trauma"
    assert follow_up.show_when_answer_in == ["yes"]
    assert not hasattr(bank, "status")  # Saving/approval remains an existing separate workflow.


@pytest.mark.parametrize("extra", ["patient_id", "name", "date_of_birth", "narrative", "sex", "occupation"])
def test_minimum_necessary_context_rejects_identifiers_and_unneeded_sensitive_fields(extra):
    with pytest.raises(ValidationError):
        OrthopedicQuestionContext.model_validate({"body_region": "knee", extra: "not accepted"})


@pytest.mark.parametrize("field,value", [("pain_score", True), ("pain_score", "6"), ("pain_score", 11),
    ("trauma", "yes"), ("imaging_kl_grade", 5), ("duration", "a long narrative")])
def test_invalid_or_coerced_values_cannot_be_accepted_as_valid_answers(field, value):
    with pytest.raises(ValidationError):
        answer(field, value)


def test_incomplete_answer_remains_available_for_physician_clarification():
    result = selected(context(answer("pain_score", state="incomplete")))
    candidate = next(item for item in result.question_candidates if item.field == "pain_score")
    assert candidate.action == "physician_clarification"
    assert result.structured_symptoms == ()


def test_source_provenance_cannot_be_upgraded_or_duplicated():
    with pytest.raises(ValidationError):
        answer("exam_effusion", True, provenance="patient_report")
    with pytest.raises(ValidationError):
        answer("imaging_kl_grade", 2, provenance="unreviewed_imaging")
    with pytest.raises(ValidationError):
        context(answer("onset", "sudden"), answer("onset", "gradual"))
    with pytest.raises(ValidationError):
        answer("fever", True, state="declined")


def test_unknown_region_defers_to_physician_without_assuming_knee():
    result = selected(context(region="unknown"))
    assert result.question_candidates == ()
    assert "body_region_requires_physician_clarification" in result.review_reasons
