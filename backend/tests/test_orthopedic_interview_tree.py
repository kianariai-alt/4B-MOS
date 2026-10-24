"""Synthetic tests for the agreed authoring tree, not clinical validation."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_interview_tree import (
    InterviewTreePreviewRequest,
    TreeInterviewAnswer,
    TreeInterviewContext,
    TreeTreatmentEpisode,
)
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext, StructuredAnswer
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.services import orthopedic_interview_tree as tree_service
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError
from backend.app.services.orthopedic_book_questions import build_book_question_preview
from backend.app.services.orthopedic_book_review import load_knee_book_review_pack
from backend.app.schemas.orthopedic_book_questions import BookQuestionPreviewRequest
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_questions import draft_question_bank, select_questions
from backend.app.services.orthopedic_interview_tree import (
    build_interview_tree,
    build_interview_tree_preview,
)


PAIN_FIELDS = {
    "pain_location", "pain_score_now", "pain_pattern", "aggravating_factor", "relieving_factor",
}
TRAUMA_FIELDS = {
    "sensory_change", "weakness", "foot_coldness", "foot_color_change", "trauma_mechanism",
}
OUTCOME_FIELDS = {"treatment_pain_response", "treatment_function_response"}


def answer(field, value=None, *, state="confirmed", source="synthetic:intake-a"):
    return TreeInterviewAnswer(field=field, state=state, value=value,
                               provenance="patient_report", source_ref=source)


def episode(ref, *observations):
    return TreeTreatmentEpisode(episode_ref=ref, observations=observations)


def request(*observations, region="knee", episodes=(), findings=(), scopes=()):
    return InterviewTreePreviewRequest(
        context=TreeInterviewContext(body_region=region, observations=observations,
                                     treatment_episodes=episodes, clinical_findings=findings),
        review_scopes=scopes,
    )


def preview(*observations, **kwargs):
    return build_interview_tree_preview(request(*observations, **kwargs))


def fields(result):
    return {item.field for item in result.question_candidates}


def candidate(result, field, episode_ref=None):
    return next(item for item in result.question_candidates
                if item.field == field and item.episode_ref == episode_ref)


def test_agreed_question_numbers_single_purpose_fields_and_sources_are_preserved():
    tree = build_interview_tree()
    expected = {
        1: "chief_complaint", 2: "laterality", 3: "trauma", 4: "fever", 5: "acute_swelling",
        6: "systemic_symptoms", 7: "sensory_change", 8: "weakness", 9: "foot_coldness",
        10: "foot_color_change", 11: "onset", 12: "duration", 13: "pain_location",
        14: "pain_score_now", 15: "pain_pattern", 16: "aggravating_factor",
        17: "relieving_factor", 18: "mechanical_locking", 19: "pain_limited_motion",
        20: "functional_limitation", 21: "trauma_mechanism", 22: "prior_surgery",
        23: "surgery_description", 24: "prior_treatment", 25: "treatment_description",
        26: "treatment_pain_response", 27: "treatment_function_response",
        28: "diagnosed_conditions", 29: "medication_list", 30: "care_goal",
    }
    assert {node.number: node.field for node in tree.nodes} == expected
    assert len({node.question.id for node in tree.nodes}) == 30
    assert tree.supplemental_routing_fields == ("has_pain",)
    assert tree.bank_export_purpose == "authoring_only"
    assert tree.bank_export_is_executable_tree is False
    assert [node.question for node in tree.nodes] == tree.bank.questions
    assert all(node.governance_status == "draft" and node.requires_independent_review
               and node.source_binding_status == "draft_authored" for node in tree.nodes)
    assert all(node.question.allow_unknown and node.question.allow_decline for node in tree.nodes)
    facts = {fact.fact.fact_key: fact for fact in load_knee_pack().facts}
    for node in tree.nodes:
        assert len(node.source_fact_keys) == len(node.source_content_sha256s)
        for key, digest in zip(node.source_fact_keys, node.source_content_sha256s, strict=True):
            assert facts[key].content_sha256 == digest
    assert "همین حالا" in next(node.question.text_fa for node in tree.nodes if node.number == 14)
    assert tree.tree_sha256 == content_digest(tree.model_dump(mode="json", exclude={"tree_sha256"}))


@pytest.mark.parametrize("scenario,req,expected", [
    ("gradual_pain_with_functional_limitation", request(
        answer("chief_complaint", "pain"), answer("has_pain", True),
        answer("onset", "gradual"), answer("functional_limitation", "moderate")), "pain_score_now"),
    ("sports_trauma_with_mechanical_symptoms", request(
        answer("trauma", True), answer("mechanical_locking", True)), "trauma_mechanism"),
    ("incomplete_history", request(answer("duration", state="incomplete")), "duration"),
    ("contradictory_history", request(
        answer("onset", "sudden", source="synthetic:a"),
        answer("onset", "gradual", source="synthetic:b")), "onset"),
    ("hot_swollen_joint_with_fever", request(
        answer("fever", True), answer("acute_swelling", True)), "onset"),
    ("unverified_imaging", request(findings=(StructuredAnswer(
        field="imaging_meniscal_lesion", value=True, state="unverified",
        provenance="unreviewed_imaging", source_ref="synthetic:image"),)), "trauma"),
    ("prior_treatment_unclear_response", request(
        answer("prior_treatment", True), episodes=(episode("treatment-a",
            answer("treatment_description", "درمان گزارش‌شدهٔ ساختگی"),
            answer("treatment_pain_response", state="unknown")),)), "treatment_function_response"),
    ("outside_knee_domain", request(answer("chief_complaint", "pain"), region="other"), None),
])
def test_eight_synthetic_scenarios_preserve_input_and_governance(scenario, req, expected):
    before = req.model_dump(mode="json")
    result = build_interview_tree_preview(req)
    assert req.model_dump(mode="json") == before
    assert result.context == req.context
    assert expected in fields(result) if expected is not None else not result.question_candidates
    assert result.review_only and result.requires_independent_review and result.safety_engine_required
    assert result.governance_status == "draft"
    assert result.safety_evaluation == "not_performed"
    assert not result.is_clinically_validated and not result.registry_write_performed
    assert not result.is_diagnosis and not result.is_recommendation
    assert not result.is_clinical_clearance and not result.authorizes_treatment
    assert result.approved_fact_count == 0
    assert all(item.governance_status == "draft" for item in result.question_candidates)
    assert '"probability"' not in json.dumps(result.model_dump(mode="json"))


def test_confirmed_answers_including_false_zero_and_both_sides_are_not_repeated():
    result = preview(answer("trauma", False), answer("has_pain", True),
                     answer("pain_score_now", 0), answer("prior_treatment", False),
                     answer("laterality", "both"))
    assert not ({"trauma", "pain_score_now", "prior_treatment", "laterality"}
                | TRAUMA_FIELDS | OUTCOME_FIELDS | {"treatment_description"}) & fields(result)
    assert {item.field for item in result.structured_answers} >= {
        "trauma", "has_pain", "pain_score_now", "prior_treatment", "laterality",
    }


def test_pain_questions_require_an_explicit_valid_pain_presence_answer():
    no_answer = preview(answer("chief_complaint", "pain"))
    assert not PAIN_FIELDS & fields(no_answer)
    assert "needs_pain_presence_clarification" in no_answer.review_reasons
    assert PAIN_FIELDS <= fields(preview(answer("has_pain", True)))
    assert not PAIN_FIELDS & fields(preview(answer("has_pain", False)))


@pytest.mark.parametrize("field,dependent", [
    ("trauma", TRAUMA_FIELDS),
    ("has_pain", PAIN_FIELDS),
    ("mechanical_locking", {"pain_limited_motion"}),
    ("prior_surgery", {"surgery_description"}),
    ("prior_treatment", {"treatment_description", *OUTCOME_FIELDS}),
])
@pytest.mark.parametrize("state", ["unknown", "declined", "incomplete", "contradictory", "unverified"])
def test_uncertain_parent_answers_do_not_open_child_branches(field, dependent, state):
    value = True if state == "unverified" else None
    result = preview(answer(field, value, state=state))
    assert not dependent & fields(result)


@pytest.mark.parametrize("state", ["unknown", "declined"])
def test_unknown_and_declined_are_preserved_without_automatic_reasking(state):
    item = answer("fever", state=state)
    result = preview(item)
    assert "fever" not in fields(result)
    assert item in result.unverified_answers
    gap = next(gap for gap in result.information_gaps if gap.field == "fever")
    assert gap.reason == state and gap.requires_physician_review


@pytest.mark.parametrize("state", ["incomplete", "contradictory", "unverified"])
def test_uncertain_answer_requires_physician_clarification_instead_of_valid_data(state):
    item = answer("onset", "sudden" if state == "unverified" else None, state=state)
    result = preview(item)
    assert item in result.unverified_answers
    assert item not in result.structured_answers
    assert candidate(result, "onset").action == "physician_clarification"


def test_conflicting_sources_are_kept_and_not_resolved_by_last_write_wins():
    first = answer("onset", "sudden", source="synthetic:a")
    second = answer("onset", "gradual", source="synthetic:b")
    result = preview(first, second)
    assert first in result.unverified_answers and second in result.unverified_answers
    assert not any(item.field == "onset" for item in result.structured_answers)
    assert candidate(result, "onset").action == "physician_clarification"


@pytest.mark.parametrize("parent,child", [
    (answer("has_pain", False), answer("pain_score_now", 8)),
    (answer("prior_surgery", False), answer("surgery_description", "جراحی گزارش‌شدهٔ ساختگی")),
])
def test_cross_field_conflicts_are_quarantined_without_losing_either_source(parent, child):
    result = preview(parent, child)
    assert result.context.observations == (parent, child)
    assert parent not in result.structured_answers and child not in result.structured_answers
    assert parent in result.unverified_answers and child in result.unverified_answers
    assert any(gap.field == parent.field and gap.requires_physician_review
               for gap in result.information_gaps)
    assert any(gap.field == child.field and gap.requires_physician_review
               for gap in result.information_gaps)
    assert not result.is_clinical_clearance


@pytest.mark.parametrize("state", ["unknown", "declined", "incomplete", "contradictory", "unverified"])
def test_blocked_child_answer_cannot_be_usable_when_parent_is_uncertain(state):
    parent = answer("prior_surgery", True if state == "unverified" else None, state=state)
    child = answer("surgery_description", "جراحی گزارش‌شدهٔ ساختگی")
    result = preview(parent, child)
    assert result.context.observations == (parent, child)
    assert child not in result.structured_answers
    assert child in result.unverified_answers
    assert any(gap.field == "surgery_description" and gap.requires_physician_review
               for gap in result.information_gaps)
    assert "surgery_description" not in fields(result)


def test_per_treatment_outcomes_do_not_leak_between_episodes():
    a = episode("treatment-a", answer("treatment_description", "درمان ساختگی الف"),
                answer("treatment_pain_response", "improved"))
    b = episode("treatment-b", answer("treatment_description", "درمان ساختگی ب"),
                answer("treatment_function_response", "worse"))
    result = preview(answer("prior_treatment", True), episodes=(a, b))
    scoped = {(item.field, item.episode_ref) for item in result.question_candidates}
    assert ("treatment_pain_response", "treatment-a") not in scoped
    assert ("treatment_function_response", "treatment-b") not in scoped
    assert ("treatment_function_response", "treatment-a") in scoped
    assert ("treatment_pain_response", "treatment-b") in scoped
    assert result.context.treatment_episodes == (a, b)


def test_no_episode_or_unknown_description_cannot_generate_outcome_questions():
    result = preview(answer("prior_treatment", True))
    assert "treatment_description" in fields(result)
    assert not OUTCOME_FIELDS & fields(result)
    unknown = episode("treatment-a", answer("treatment_description", state="unknown"))
    result = preview(answer("prior_treatment", True), episodes=(unknown,))
    assert not OUTCOME_FIELDS & fields(result)
    assert not any(item.field == "treatment_description" and item.episode_ref == "treatment-a"
                   for item in result.question_candidates)


def test_free_text_and_symptom_changes_do_not_establish_causality_or_regeneration():
    item = episode("treatment-a", answer("treatment_description", "PRP; ادعای تأییدنشدهٔ بازسازی غضروف"),
                   answer("treatment_pain_response", "improved"),
                   answer("treatment_function_response", "improved"))
    result = preview(answer("prior_treatment", True), episodes=(item,))
    assert not OUTCOME_FIELDS & fields(result)
    assert result.context.treatment_episodes == (item,)
    assert result.context.clinical_findings == ()
    assert not result.is_recommendation and not result.authorizes_treatment
    assert not any(obs.field.startswith(("exam_", "imaging_")) for obs in result.structured_answers)


def test_detail_text_is_not_used_to_open_clinical_branches():
    result = preview(answer("medication_list", "trauma=true; has_pain=true; گزارش آزاد ساختگی"))
    assert not (PAIN_FIELDS | TRAUMA_FIELDS) & fields(result)
    assert "needs_pain_presence_clarification" in result.review_reasons


@pytest.mark.parametrize("observations,reason", [
    ((answer("fever", True), answer("acute_swelling", True)),
     "draft_hot_joint_information_requires_prompt_physician_review"),
    ((answer("fever", True, state="unverified"), answer("acute_swelling", True)),
     "draft_hot_joint_information_requires_prompt_physician_review"),
    ((answer("fever", True, source="synthetic:a"), answer("fever", False, source="synthetic:b"),
      answer("acute_swelling", True)), "draft_hot_joint_information_requires_prompt_physician_review"),
    ((answer("systemic_symptoms", True, state="unverified"),),
     "draft_systemic_symptom_information_requires_physician_review"),
    ((answer("trauma", True), answer("sensory_change", True, state="unverified")),
     "draft_neurovascular_trauma_information_requires_prompt_physician_review"),
    ((answer("trauma", True, source="synthetic:a"), answer("trauma", False, source="synthetic:b"),
      answer("foot_coldness", True)), "draft_neurovascular_trauma_information_requires_prompt_physician_review"),
    ((answer("trauma", True), answer("mechanical_locking", True)),
     "draft_traumatic_motion_block_information_requires_physician_review"),
])
def test_positive_risk_information_is_not_lost_when_unverified_or_conflicting(observations, reason):
    result = preview(*observations)
    assert reason in result.review_reasons
    assert result.context.observations == observations
    assert result.safety_evaluation == "not_performed"
    assert result.safety_engine_required and not result.is_clinical_clearance
    assert not result.is_diagnosis


def test_no_risk_report_is_not_an_assertion_of_patient_safety():
    result = preview(answer("trauma", False), answer("fever", False),
                     answer("acute_swelling", False), answer("systemic_symptoms", False))
    assert result.safety_evaluation == "not_performed"
    assert result.safety_engine_required and not result.is_clinical_clearance


def test_imaging_severity_cannot_answer_pain_or_function_questions():
    image = StructuredAnswer(field="imaging_kl_grade", value=4, state="confirmed",
                             provenance="reviewed_imaging", source_ref="synthetic:film")
    result = preview(findings=(image,))
    assert result.clinical_findings == result.usable_clinical_findings == (image,)
    assert result.structured_answers == ()
    assert "functional_limitation" in fields(result)
    assert not PAIN_FIELDS & fields(result)
    assert "needs_pain_presence_clarification" in result.review_reasons


def test_conflicting_exam_findings_are_preserved_without_becoming_usable():
    a = StructuredAnswer(field="exam_effusion", value=True, state="confirmed",
                         provenance="physician_exam", source_ref="synthetic:exam-a")
    b = StructuredAnswer(field="exam_effusion", value=False, state="confirmed",
                         provenance="physician_exam", source_ref="synthetic:exam-b")
    result = preview(findings=(a, b))
    assert result.clinical_findings == (a, b)
    assert result.usable_clinical_findings == ()
    assert any(gap.field == "exam_effusion" and gap.reason == "contradictory"
               and gap.requires_physician_review for gap in result.information_gaps)


def test_current_baseline_and_book_preview_contracts_are_unchanged_by_tree():
    baseline_context = OrthopedicQuestionContext(body_region="knee")
    baseline_before = select_questions(baseline_context, load_knee_pack())
    book_request = BookQuestionPreviewRequest(context=baseline_context)
    book_before = build_book_question_preview(book_request)
    preview(answer("laterality", "both"), answer("has_pain", True))
    assert len(draft_question_bank().questions) == 22
    assert select_questions(baseline_context, load_knee_pack()) == baseline_before
    assert build_book_question_preview(book_request) == book_before
    with pytest.raises(ValidationError):
        StructuredAnswer(field="pain_score_now", value=5, state="confirmed",
                         provenance="patient_report", source_ref="synthetic:a")


@pytest.mark.parametrize("field,value", [
    ("pain_score_now", True), ("pain_score_now", "6"), ("pain_score_now", 11),
    ("trauma", "yes"), ("laterality", "unilateral"), ("has_pain", 1),
])
def test_wrong_or_coerced_values_cannot_be_valid_answers(field, value):
    with pytest.raises(ValidationError):
        answer(field, value)


@pytest.mark.parametrize("extra", ["patient_id", "name", "date_of_birth", "national_id", "narrative"])
def test_unneeded_sensitive_context_fields_are_rejected(extra):
    with pytest.raises(ValidationError):
        TreeInterviewContext.model_validate({"body_region": "knee", extra: "not accepted"})


def test_history_and_clinical_findings_channels_cannot_be_interchanged():
    with pytest.raises(ValidationError):
        TreeInterviewAnswer(field="exam_effusion", value=True, state="confirmed",
                            provenance="patient_report", source_ref="synthetic:a")
    with pytest.raises(ValidationError):
        TreeInterviewAnswer(field="trauma", value=True, state="confirmed",
                            provenance="physician_exam", source_ref="synthetic:a")
    with pytest.raises(ValidationError):
        TreeInterviewContext(clinical_findings=(StructuredAnswer(
            field="trauma", value=True, state="confirmed", provenance="patient_report",
            source_ref="synthetic:a"),))


def test_duplicate_source_and_episode_identifiers_are_rejected():
    with pytest.raises(ValidationError):
        request(answer("onset", "sudden"), answer("onset", "gradual"))
    with pytest.raises(ValidationError):
        request(episodes=(episode("treatment-a"), episode("treatment-a")))


def test_treatment_fields_cannot_masquerade_as_unscoped_answers():
    with pytest.raises(ValidationError):
        request(answer("treatment_pain_response", "improved"))
    with pytest.raises(ValidationError):
        episode("treatment-a", answer("trauma", True))


@pytest.mark.parametrize("region", ["other", "unknown"])
def test_non_knee_context_does_not_get_knee_question_candidates(region):
    result = preview(answer("trauma", True), answer("has_pain", True), region=region)
    assert not result.question_candidates
    assert result.review_reasons


def test_result_and_rule_hashes_are_deterministic_and_bind_request_changes():
    req = request(answer("has_pain", True))
    first = build_interview_tree_preview(req)
    second = build_interview_tree_preview(req)
    assert first == second
    assert first.result_sha256 == content_digest(first.model_dump(mode="json", exclude={"result_sha256"}))
    different = preview(answer("has_pain", False))
    assert first.request_sha256 != different.request_sha256
    assert first.result_sha256 != different.result_sha256


def test_changed_selector_artifact_changes_rule_hash_not_input(monkeypatch):
    req = request()
    before = build_interview_tree_preview(req)
    original = Path.read_bytes
    service_path = Path(tree_service.__file__)

    def altered_bytes(path):
        return b"Synthetic changed authoring tree selector" if path == service_path else original(path)

    monkeypatch.setattr(Path, "read_bytes", altered_bytes)
    after = build_interview_tree_preview(req)
    assert after.request_sha256 == before.request_sha256
    assert after.rules_sha256 != before.rules_sha256
    assert after.result_sha256 != before.result_sha256


def test_tampered_base_knowledge_is_rejected_before_question_selection():
    pack = load_knee_pack()
    pack.facts[0].fact.title = "Synthetic unreviewed change"
    with pytest.raises(MedicalKnowledgeIntegrityError):
        build_interview_tree_preview(request(), base_pack=pack)


def test_tampered_book_supplement_is_rejected_before_use():
    pack = load_knee_book_review_pack()
    pack.entries[0].draft_preview.proposal.title = "Synthetic unreviewed source change"
    with pytest.raises((MedicalKnowledgeIntegrityError, ValueError)):
        build_interview_tree_preview(request(), book_pack=pack)


def test_context_models_constructed_without_validation_are_revalidated():
    invalid = TreeInterviewAnswer.model_construct(field="trauma", value="yes", state="confirmed",
                                                 provenance="patient_report", source_ref="synthetic:a")
    invalid_context = TreeInterviewContext.model_construct(body_region="knee", observations=(invalid,))
    invalid_request = InterviewTreePreviewRequest.model_construct(context=invalid_context)
    with pytest.raises(ValidationError):
        build_interview_tree_preview(invalid_request)


def test_book_support_is_explicit_scope_bound_and_not_claimed_for_all_questions():
    no_scope = preview(answer("has_pain", True))
    assert not any(item.book_candidate_keys for item in no_scope.question_candidates)
    assert not no_scope.book_source_references
    with_scope = preview(answer("has_pain", True), scopes=("arthroplasty_review",))
    annotated = {item.field: item.book_candidate_keys for item in with_scope.question_candidates
                 if item.book_candidate_keys}
    assert annotated == {
        "pain_score_now": ("BOOK.KNEE.001",),
        "functional_limitation": ("BOOK.KNEE.001",),
        "diagnosed_conditions": ("BOOK.KNEE.002",),
    }
    assert all(ref.population_applicability == "not_assessed" for ref in with_scope.book_source_references)


@pytest.mark.parametrize("field,value", [
    ("review_only", False), ("review_only", 1),
    ("requires_independent_review", False), ("requires_independent_review", "true"),
    ("registry_write_performed", True), ("is_clinically_validated", True),
    ("is_diagnosis", True), ("is_recommendation", True),
    ("is_clinical_clearance", True), ("authorizes_treatment", True),
    ("safety_engine_required", False), ("approved_fact_count", 1),
    ("approved_fact_count", False),
])
def test_governance_flags_cannot_be_weakened_or_coerced(field, value):
    result = preview()
    raw = result.model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        type(result).model_validate(raw)


def test_documented_ten_case_fixture_runs_against_real_tree_preview():
    from backend.tools.orthopedic_interview_tree_demo import run_synthetic_cases

    summary = run_synthetic_cases()
    assert summary["case_count"] == summary["passed_cases"] == 10
    assert all(case["passed"] for case in summary["cases"])
    assert summary["synthetic_only"] is True
    assert summary["is_clinically_validated"] is summary["registry_write_performed"] is False
