"""Patient-grounded reasoning review checks; not clinical validation."""
from __future__ import annotations

import json

import pytest

from backend.app.schemas.orthopedic_interview_tree import TreeTreatmentEpisode
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.services.orthopedic_assessment import build_knee_assessment, export_offline_assessment
from backend.app.services.orthopedic_interview_tree import build_interview_tree_preview
from backend.app.services.orthopedic_reasoning_review import build_knee_reasoning_review
from backend.tests.test_orthopedic_assessment import answer, clinical, request


HYPOTHESES = {"knee_oa", "patellofemoral_pain", "meniscal_finding", "cartilage_finding"}


def review(*extra, **kwargs):
    return build_knee_reasoning_review(request(*extra, **kwargs))


def hypothesis(result, key):
    return next(item for item in result.hypothesis_reviews if item.hypothesis_id == key)


def criterion(result, key, field):
    return next(row for row in hypothesis(result, key).criteria if row.field == field)


def observation_rows(value):
    """Find observed evidence rows without confusing authored source facts."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        if {"field", "source_ref", "provenance", "value", "usability"} <= value.keys():
            yield value
        for item in value.values():
            yield from observation_rows(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from observation_rows(item)


def test_review_preserves_the_original_request_and_assessment_without_new_matching():
    req = request()
    before = req.model_dump(mode="json")
    baseline = build_knee_assessment(req)
    result = build_knee_reasoning_review(req)
    assert req.model_dump(mode="json") == before
    assert result.baseline_assessment == baseline
    assert result.request_sha256 == content_digest(before)
    assert result == build_knee_reasoning_review(req)
    payload = result.model_dump(mode="json")
    assert result.result_sha256 == content_digest({key: value for key, value in payload.items()
                                                  if key != "result_sha256"})
    assert {item.hypothesis_id for item in result.hypothesis_reviews} == HYPOTHESES
    assert all(item.is_excluded is False for item in result.hypothesis_reviews)


def test_problem_representation_contains_actual_typed_answers_and_sources():
    result = review(pain_score_now=0, functional_limitation="none", care_goal="pain")
    facts = {row.field: row for row in result.problem_representation.history}
    assert facts["pain_score_now"].value == 0
    assert type(facts["pain_score_now"].value) is int
    assert facts["trauma"].value is False
    assert type(facts["trauma"].value) is bool
    assert facts["functional_limitation"].value == "none"
    assert facts["care_goal"].value == "pain"
    assert all(row.usability == "usable" and row.provenance == "patient_report"
               and row.source_ref == "synthetic:history-a" for row in facts.values())
    assert "pain_score" not in facts  # This question measures pain NOW only.
    assert not {"age", "date_of_birth", "morning_stiffness"} & facts.keys()
    assert result.problem_representation.summary_fa


def test_report_changes_when_function_or_goal_changes_even_if_matching_does_not():
    original = review(functional_limitation="severe", care_goal="function")
    changed = review(functional_limitation="none", care_goal="pain")
    assert original.baseline_assessment.considerations == changed.baseline_assessment.considerations
    assert original.problem_representation != changed.problem_representation
    assert original.result_sha256 != changed.result_sha256


@pytest.mark.parametrize("state", ["unknown", "declined", "incomplete", "unverified", "contradictory"])
def test_uncertain_observation_keeps_its_source_but_cannot_be_used_as_support(state):
    item = answer("onset", "gradual" if state == "unverified" else None,
                  state=state, source="synthetic:uncertain-onset")
    result = review(item)
    assert not any(row.field == "onset" for row in result.problem_representation.history)
    raw = next(row for row in result.quarantined_observations if row.field == "onset")
    assert raw.state == state and raw.source_ref == "synthetic:uncertain-onset"
    assert raw.value == item.value and raw.usability == "quarantined"
    row = criterion(result, "knee_oa", "onset")
    assert row.relation == "unresolved"
    assert all(observation.usability != "usable" for observation in row.observations)
    assert hypothesis(result, "knee_oa").is_excluded is False


def test_missing_answer_has_no_fabricated_observation_or_source():
    result = review(omit=("onset",))
    row = criterion(result, "knee_oa", "onset")
    assert row.relation == "unresolved" and row.observations == ()
    assert not any(observation.field == "onset" for observation in result.quarantined_observations)
    assert any(item.field == "onset" for item in result.next_data_requirements)


def test_a_negative_report_and_an_unknown_report_have_distinct_evidence_states():
    negative = criterion(review(), "knee_oa", "trauma")
    unknown = criterion(review(answer("trauma", state="unknown")), "knee_oa", "trauma")
    assert negative.relation == "matched"
    assert negative.observations[0].value is False
    assert unknown.relation == "unresolved"
    assert unknown.observations[0].value is None
    assert unknown.observations[0].state == "unknown"


def test_conflicting_sources_are_both_preserved_and_are_not_last_write_wins():
    first = answer("onset", "gradual", source="synthetic:source-a")
    second = answer("onset", "sudden", source="synthetic:source-b")
    result = review(first, second)
    rows = [row for row in result.quarantined_observations if row.field == "onset"]
    assert {row.source_ref for row in rows} == {"synthetic:source-a", "synthetic:source-b"}
    assert {row.value for row in rows} == {"gradual", "sudden"}
    assert all(row.state == "confirmed" and row.usability == "quarantined" for row in rows)
    assert criterion(result, "knee_oa", "onset").relation == "unresolved"


def test_cross_field_conflict_is_visible_without_promoting_numeric_pain():
    result = review(has_pain=False, pain_score_now=8)
    usable = {row.field for row in result.problem_representation.history}
    quarantined = {row.field for row in result.quarantined_observations}
    assert not {"has_pain", "pain_score_now"} & usable
    assert {"has_pain", "pain_score_now"} <= quarantined
    assert result.baseline_assessment.considerations == ()
    assert all(item.is_excluded is False for item in result.hypothesis_reviews)


def test_verified_examination_is_preserved_even_when_legacy_matching_ignores_it():
    findings = (
        clinical("exam_range_of_motion", "restricted", source="synthetic:exam-rom"),
        clinical("exam_joint_line_tenderness", True, source="synthetic:exam-line"),
    )
    result = review(findings=findings)
    rows = {row.field: row for row in result.problem_representation.examination}
    assert set(rows) == {"exam_range_of_motion", "exam_joint_line_tenderness"}
    assert rows["exam_range_of_motion"].value == "restricted"
    assert rows["exam_joint_line_tenderness"].value is True
    assert all(row.provenance == "physician_exam" and row.usability == "usable" for row in rows.values())
    unused = {row.field for row in result.clinical_findings_not_used_by_current_model}
    assert set(rows) <= unused
    assert result.baseline_assessment.considerations == build_knee_assessment(request()).considerations


def test_unreviewed_imaging_is_neither_a_structural_match_nor_usable_evidence():
    image = clinical("imaging_cartilage_lesion", True, state="unverified",
                     provenance="unreviewed_imaging", source="synthetic:image-unreviewed")
    result = review(findings=(image,))
    assert not result.problem_representation.imaging
    row = criterion(result, "cartilage_finding", "imaging_cartilage_lesion")
    assert row.relation == "unresolved"
    assert row.observations[0].provenance == "unreviewed_imaging"
    assert row.observations[0].usability == "quarantined"
    assert hypothesis(result, "cartilage_finding").is_excluded is False


def test_reviewed_image_is_a_documented_finding_not_proof_of_pain_causation():
    image = clinical("imaging_meniscal_lesion", True, source="synthetic:image-reviewed")
    result = review(findings=(image,))
    row = criterion(result, "meniscal_finding", "imaging_meniscal_lesion")
    assert row.relation == "matched"
    assert row.observations[0].source_ref == "synthetic:image-reviewed"
    assert row.observations[0].provenance == "reviewed_imaging"
    assert row.observations[0].value is True
    assert hypothesis(result, "meniscal_finding").is_excluded is False


def test_workflow_hold_does_not_erase_a_matched_pattern_or_call_it_excluded():
    result = review(answer("fever", state="unknown"))
    oa = hypothesis(result, "knee_oa")
    assert oa.status == "withheld_by_workflow"
    assert oa.pattern_status == "matched_pattern"
    assert all(row.relation == "matched" for row in oa.criteria)
    assert oa.patient_grounded_support_fa
    assert oa.is_excluded is False
    assert result.baseline_assessment.conditional_treatment_evidence == ()


def test_trauma_counterexample_exposes_pattern_limit_not_a_medical_exclusion():
    negatives = tuple(answer(field, False) for field in
                      ("sensory_change", "weakness", "foot_coldness", "foot_color_change"))
    result = review(*negatives, trauma=True, trauma_mechanism="sport_twist")
    oa = hypothesis(result, "knee_oa")
    assert result.baseline_assessment.considerations == ()
    assert oa.pattern_status == "pattern_not_matched"
    row = criterion(result, "knee_oa", "trauma")
    assert row.relation == "mismatched"
    assert row.observations[0].value is True
    assert oa.pattern_mismatches_fa and oa.is_excluded is False
    assert result.structural_limitations_fa


def test_surgical_history_counterexample_keeps_description_despite_global_hold():
    result = review(prior_surgery=True, surgery_description="عمل ساختگی روی زانو")
    assert result.baseline_assessment.status == "insufficient_information"
    facts = {row.field: row for row in result.problem_representation.history}
    assert facts["prior_surgery"].value is True
    assert facts["surgery_description"].value == "عمل ساختگی روی زانو"
    assert hypothesis(result, "knee_oa").status == "withheld_by_workflow"
    assert hypothesis(result, "knee_oa").pattern_status == "matched_pattern"


def test_treatment_histories_remain_episode_scoped_without_an_efficacy_inference():
    episodes = tuple(TreeTreatmentEpisode(episode_ref=ref, observations=(
        answer("treatment_description", label),
        answer("treatment_pain_response", response),
        answer("treatment_function_response", "unchanged"),
    )) for ref, label, response in (
        ("treatment-a", "درمان ساختگی الف", "improved"),
        ("treatment-b", "درمان ساختگی ب", "worse"),
    ))
    result = review(prior_treatment=True, episodes=episodes)
    rows = list(observation_rows(result.problem_representation.treatment_episodes))
    responses = {(row["episode_ref"], row["value"]) for row in rows
                 if row["field"] == "treatment_pain_response"}
    assert responses == {("treatment-a", "improved"), ("treatment-b", "worse")}
    assert result.baseline_assessment.considerations == review().baseline_assessment.considerations


def test_uncertainty_and_schema_coverage_gaps_are_separate_from_patient_facts():
    result = review(omit=("onset",))
    assert any(item.category == "missing_current_field" and item.field == "onset"
               for item in result.next_data_requirements)
    schema_gaps = [item for item in result.next_data_requirements if item.category == "schema_coverage_gap"]
    assert schema_gaps
    known_fields = {row["field"] for row in observation_rows(result.problem_representation)}
    assert not {item.field for item in schema_gaps} & known_fields
    assert any(item.existing_question_id is not None and item.field == "onset"
               for item in result.next_data_requirements)


def test_sources_in_criterion_ledger_are_bound_to_existing_knowledge_hashes():
    result = review()
    model = export_offline_assessment()
    cards = {item["id"]: item for item in model["cards"]}
    for item in result.hypothesis_reviews:
        expected = dict(zip(cards[item.hypothesis_id]["source_fact_keys"],
                            cards[item.hypothesis_id]["source_content_sha256s"], strict=True))
        for row in item.criteria:
            for key, digest in zip(row.source_fact_keys, row.source_content_sha256s, strict=True):
                assert expected[key] == digest
    assert result.structural_limitations_fa


def test_new_review_does_not_write_or_approve_medical_knowledge(monkeypatch):
    from backend.app.services.medical_knowledge import MedicalKnowledgeService
    def forbidden(*args, **kwargs):
        raise AssertionError("A reasoning review must not write or approve Registry data.")
    monkeypatch.setattr(MedicalKnowledgeService, "create", forbidden)
    monkeypatch.setattr(MedicalKnowledgeService, "review", forbidden)
    result = review()
    assert result.governance_status == "draft" and result.requires_independent_review
    assert result.baseline_assessment.approved_fact_count == 0
    assert result.baseline_assessment.safety_evaluation == "not_performed"
    assert result.baseline_assessment.authorizes_treatment is False


def test_no_new_probabilities_or_diagnostic_winner_are_added():
    result = review(pain_location="anterior", aggravating_factor="stairs")
    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()
    assert not {"probability", "confidence", "diagnostic_probability", "rank", "score"} & keys(result.model_dump(mode="json"))
    assert len(result.baseline_assessment.considerations) == 2
    assert all(item.is_excluded is False for item in result.hypothesis_reviews)


@pytest.mark.parametrize("region", ["other", "unknown"])
def test_outside_scope_keeps_legacy_hold_and_does_not_turn_review_into_a_knee_diagnosis(region):
    result = review(region=region)
    assert result.baseline_assessment.status in {"outside_scope", "insufficient_information"}
    assert result.baseline_assessment.considerations == ()
    assert result.baseline_assessment.conditional_treatment_evidence == ()
    assert all(item.is_excluded is False for item in result.hypothesis_reviews)


def test_literal_free_text_is_not_reinterpreted_as_controlled_choices():
    result = review(medication_list="none", diagnosed_conditions="pain")
    rows = {row.field: row for row in result.problem_representation.history}
    assert rows["medication_list"].value_fa == "none"
    assert rows["diagnosed_conditions"].value_fa == "pain"


def test_absent_imaging_does_not_get_a_label_asserting_a_documented_lesion():
    result = review()
    images = [h for h in result.hypothesis_reviews if h.hypothesis_id.endswith("finding")]
    assert all(h.pattern_status == "information_missing" for h in images)
    assert all("بررسی زمینه" in h.label_fa for h in images)
    assert all(not h.is_excluded for h in images)
