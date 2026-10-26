"""Synthetic workbench checks: software invariants, not clinical validation."""
from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest, SupplementalObservation
from backend.app.services.orthopedic_reasoning_review import build_knee_reasoning_review
from backend.app.services.medical_knowledge import knowledge_content_digest
from backend.app.services.orthopedic_workbench import build_knee_workbench
from backend.tests.test_orthopedic_assessment import answer, clinical, request


def supplemental(field, value=None, *, state="confirmed", source="synthetic:extra-a", provenance=None):
    return SupplementalObservation(
        field=field, value=value, state=state, source_ref=source,
        provenance=provenance or ("physician_exam" if field.startswith("exam_") else "patient_report"),
    )


def workbench_request(*observations, **kwargs):
    return KneeWorkbenchRequest(interview=request(**kwargs), supplemental_observations=observations)


def evaluate(*observations, **kwargs):
    return build_knee_workbench(workbench_request(*observations, **kwargs))


def relationships(result, field):
    return tuple(row for comparison in result.comparisons for row in comparison.relationships if row.field == field)


def test_request_and_baseline_are_preserved_without_writing_or_diagnostic_probabilities():
    req = workbench_request(supplemental("age_band", "45_or_over"))
    before = deepcopy(req.model_dump(mode="json"))
    result = build_knee_workbench(req)
    assert req.model_dump(mode="json") == before
    assert result.baseline_review == build_knee_reasoning_review(req.interview)
    assert len(result.comparisons) == 4
    assert all(not row.is_ranked and not row.is_excluded and row.diagnostic_probability is None
               for row in result.comparisons)
    assert result.registry_write_performed is False
    assert result.approved_fact_count == 0
    assert result.safety_engine_required is True and result.safety_evaluation == "not_performed"
    assert not result.is_diagnosis and not result.authorizes_treatment and not result.is_clinically_validated


def test_age_and_stiffness_change_actual_comparison_evidence():
    older_short = evaluate(supplemental("age_band", "45_or_over"),
                           supplemental("morning_stiffness", "up_to_30_min"))
    younger_long = evaluate(supplemental("age_band", "under_45"),
                            supplemental("morning_stiffness", "over_30_min"))
    assert relationships(older_short, "age_band")
    assert relationships(older_short, "morning_stiffness")
    assert relationships(older_short, "age_band") != relationships(younger_long, "age_band")
    assert relationships(older_short, "morning_stiffness") != relationships(younger_long, "morning_stiffness")
    assert older_short.result_sha256 != younger_long.result_sha256
    assert all(not row.is_excluded for row in younger_long.comparisons)


def test_missing_supplement_is_unavailable_without_fabricated_observation():
    result = evaluate()
    age = relationships(result, "age_band")
    assert age and all(row.relation == "unavailable" and row.observations == () for row in age)
    assert not any(row.field == "age_band" for row in result.supplemental_observations)


@pytest.mark.parametrize("state", ["unknown", "declined"])
def test_unknown_or_declined_is_not_reasked_as_an_ordinary_patient_question(state):
    result = evaluate(supplemental("age_band", state=state))
    assert all(row.relation == "unavailable" for row in relationships(result, "age_band"))
    assert not any(item.field == "age_band" and item.category == "patient_question"
                   and item.action == "ask_missing" for item in result.next_items)
    rows = [row for row in result.quarantined_observations if row.field == "age_band"]
    assert rows and all(row.state == state and row.value is None for row in rows)


def test_conflicting_sources_are_retained_and_do_not_become_last_write_wins():
    first = supplemental("age_band", "45_or_over", source="synthetic:first")
    second = supplemental("age_band", "under_45", source="synthetic:second")
    result = evaluate(first, second)
    reversed_result = evaluate(second, first)
    rows = [row for row in result.quarantined_observations if row.field == "age_band"]
    assert {row.value for row in rows} == {"under_45", "45_or_over"}
    assert {row.source_ref for row in rows} == {"synthetic:first", "synthetic:second"}
    assert all(row.relation == "unavailable" for row in relationships(result, "age_band"))
    assert all(row.relation == "unavailable" for row in relationships(reversed_result, "age_band"))


@pytest.mark.parametrize("unusable_state", ["unknown", "declined", "unverified"])
def test_a_confirmed_value_does_not_promote_or_get_overwritten_by_uncertain_sources(unusable_state):
    confirmed = supplemental("age_band", "45_or_over", source="synthetic:complete")
    uncertain = supplemental("age_band", "45_or_over" if unusable_state == "unverified" else None,
                             state=unusable_state, source="synthetic:uncertain")
    result = evaluate(confirmed, uncertain)
    rows = [row for row in result.supplemental_observations if row.field == "age_band"]
    assert next(row for row in rows if row.source_ref == "synthetic:complete").usability == "usable"
    assert next(row for row in rows if row.source_ref == "synthetic:uncertain").usability == "quarantined"
    assert all(row.relation == "supports" for row in relationships(result, "age_band"))
    assert "۴۵ سال یا بیشتر" in result.summary_fa


def test_verified_squat_finding_changes_the_comparison_ledger():
    positive = evaluate(supplemental("exam_squat_anterior_pain", True), pain_location="anterior")
    negative = evaluate(supplemental("exam_squat_anterior_pain", False), pain_location="anterior")
    positive_rows = relationships(positive, "exam_squat_anterior_pain")
    negative_rows = relationships(negative, "exam_squat_anterior_pain")
    assert positive_rows and negative_rows and positive_rows != negative_rows
    assert any(row.relation == "supports" for row in positive_rows)
    assert all(observation.provenance == "physician_exam"
               for row in positive_rows for observation in row.observations)


def test_existing_verified_joint_line_finding_is_used_instead_of_ignored():
    before = evaluate()
    after = evaluate(findings=(clinical("exam_joint_line_tenderness", True),))
    rows = relationships(after, "exam_joint_line_tenderness")
    # Chronic symptoms are outside the acute-isolated guideline's scope. The
    # observation is visible without claiming acute-source diagnostic support.
    assert rows and all(row.relation == "neutral" for row in rows)
    assert rows[0].observations[0].value is True
    assert rows[0].observations[0].usability == "usable"
    assert relationships(before, "exam_joint_line_tenderness") != rows


def test_joint_line_finding_can_support_review_in_acute_trauma_context():
    result = evaluate(findings=(clinical("exam_joint_line_tenderness", True),),
                      trauma=True, duration="days", sensory_change=False, weakness=False,
                      foot_coldness=False, foot_color_change=False)
    assert any(row.relation == "supports" for row in relationships(result, "exam_joint_line_tenderness"))
    assert all(not row.is_excluded for row in result.comparisons)


def test_negative_mcmurray_does_not_exclude_meniscal_disease():
    result = evaluate(supplemental("exam_mcmurray", "negative"))
    rows = relationships(result, "exam_mcmurray")
    assert rows and all(not row.is_clinical_exclusion for row in rows)
    assert all(not item.is_excluded and item.diagnostic_probability is None for item in result.comparisons)


def test_reviewed_cartilage_image_is_documented_without_establishing_pain_causation_or_regeneration():
    result = evaluate(findings=(clinical("imaging_cartilage_lesion", True),))
    rows = relationships(result, "imaging_cartilage_lesion")
    assert rows and rows[0].observations[0].provenance == "reviewed_imaging"
    assert rows[0].observations[0].usability == "usable"
    assert "علت درد" in rows[0].explanation_fa
    assert not result.is_diagnosis and not result.authorizes_treatment
    assert not result.management_review.infers_cartilage_regeneration
    assert not result.management_review.infers_treatment_efficacy


def test_unreviewed_cartilage_image_remains_quarantined_and_cannot_support_a_relationship():
    result = evaluate(findings=(clinical("imaging_cartilage_lesion", True, state="unverified",
                                        provenance="unreviewed_imaging"),))
    rows = relationships(result, "imaging_cartilage_lesion")
    assert rows and all(row.relation == "unavailable" for row in rows)
    assert all(observation.usability == "quarantined" for row in rows for observation in row.observations)


def test_history_of_injury_does_not_become_an_oa_exclusion():
    result = evaluate(
        supplemental("age_band", "45_or_over"), supplemental("morning_stiffness", "none"),
        trauma=True, findings=(),
        sensory_change=False, weakness=False, foot_coldness=False, foot_color_change=False,
    )
    assert any(row.relation == "supports" for row in relationships(result, "age_band"))
    assert all(not item.is_excluded for item in result.comparisons)
    assert all(not row.is_clinical_exclusion for item in result.comparisons for row in item.relationships)


def test_unverified_positive_risk_cannot_be_cleared_by_additional_supplements():
    req = workbench_request(supplemental("age_band", "45_or_over"),
                            supplemental("morning_stiffness", "none"))
    payload = req.model_dump(mode="json")
    payload["interview"]["context"]["observations"] = [item for item in payload["interview"]["context"]["observations"]
                                                          if item["field"] != "fever"]
    payload["interview"]["context"]["observations"].append(
        answer("fever", True, state="unverified", source="synthetic:risk").model_dump(mode="json"))
    result = build_knee_workbench(payload)
    assert result.workflow_status == "prompt_physician_review"
    assert result.routine_evaluation_withheld
    assert all(item.status == "withheld_by_workflow" for item in result.comparisons)


def test_multiple_locations_and_activities_are_preserved_and_all_can_affect_evidence():
    result = evaluate(supplemental("pain_locations", ("medial", "anterior")),
                      supplemental("aggravating_activities", ("walking", "loaded_flexion")))
    rows = {row.field: row for row in result.supplemental_observations if row.usability == "usable"}
    assert rows["pain_locations"].value == ("medial", "anterior")
    assert rows["aggravating_activities"].value == ("walking", "loaded_flexion")
    assert any(row.relation == "supports" for row in relationships(result, "pain_locations"))
    assert any(row.relation == "supports" for row in relationships(result, "aggravating_activities"))


def test_incompatible_single_and_multi_reports_are_quarantined_not_silently_overwritten():
    result = evaluate(supplemental("pain_locations", ("anterior", "lateral")), pain_location="medial")
    rows = [row for row in result.quarantined_observations if row.field in {"pain_location", "pain_locations"}]
    assert {row.field for row in rows} == {"pain_location", "pain_locations"}
    assert all(row.usability == "quarantined" for row in rows)
    assert any(item.action == "physician_clarification" for item in result.next_items
               if item.field in {"pain_location", "pain_locations"})


def test_multichoice_selection_order_does_not_create_a_false_conflict_or_ranking():
    result = evaluate(supplemental("pain_locations", ("medial", "anterior"), source="synthetic:first"),
                      supplemental("pain_locations", ("anterior", "medial"), source="synthetic:second"))
    rows = [row for row in result.supplemental_observations if row.field == "pain_locations"]
    assert len(rows) == 2
    assert all(row.usability == "usable" for row in rows)
    assert {row.value for row in rows} == {("medial", "anterior"), ("anterior", "medial")}
    assert not any(row.field == "pain_locations" for row in result.quarantined_observations)
    assert all(not item.is_ranked for item in result.comparisons)


def test_multichoice_equivalence_cannot_silently_clear_a_conflicting_baseline_field():
    interview = request(answer("pain_location", "anterior", source="synthetic:first"),
                        answer("pain_location", "medial", source="synthetic:second"))
    req = KneeWorkbenchRequest(interview=interview, supplemental_observations=(
        supplemental("pain_locations", ("medial", "anterior")),))
    result = build_knee_workbench(req)
    assert result.routine_evaluation_withheld
    assert result.workflow_status == "insufficient_information"
    assert not any(item.guard_id == "core:pain_location" for item in result.workflow_equivalences)
    assert {row.source_ref for row in result.quarantined_observations if row.field == "pain_location"} == {
        "synthetic:first", "synthetic:second"}


def test_multichoice_management_goals_are_not_reduced_to_a_single_goal_or_a_plan():
    result = evaluate(supplemental("care_goals", ("function", "pain")))
    goals = [row for row in result.management_review.observations if row.field == "care_goals"]
    assert goals and goals[0].value == ("function", "pain")
    assert not result.management_review.is_personalized_plan
    assert not result.management_review.infers_treatment_efficacy
    assert not result.management_review.infers_cartilage_regeneration


def test_hashes_bind_request_sources_rules_and_complete_result_and_are_reproducible():
    req = workbench_request(supplemental("age_band", "45_or_over"))
    result = build_knee_workbench(req)
    assert result == build_knee_workbench(req)
    assert result.request_sha256 == content_digest(req.model_dump(mode="json"))
    payload = result.model_dump(mode="json")
    assert result.result_sha256 == content_digest({key: value for key, value in payload.items() if key != "result_sha256"})
    assert all(len(row.source_fact_keys) == len(row.source_content_sha256s) and row.source_fact_keys
               for item in result.comparisons for row in item.relationships)
    assert all(proposal.governance_status == "draft" for proposal in result.new_draft_proposals)
    for proposal in result.new_draft_proposals:
        assert proposal.content_sha256 == knowledge_content_digest(
            fact_key=proposal.fact.fact_key, version=proposal.version, content=proposal.fact)
        assert proposal.fact.sources


@pytest.mark.parametrize("region,expected_status", [("other", "outside_scope"), ("unknown", "insufficient_information")])
def test_extra_knowledge_does_not_silently_clear_body_region_scope(region, expected_status):
    result = evaluate(supplemental("age_band", "45_or_over"),
                      supplemental("morning_stiffness", "none"), region=region)
    assert result.workflow_status == expected_status
    assert result.routine_evaluation_withheld


def test_extra_knowledge_does_not_clear_prior_surgery_hold():
    result = evaluate(supplemental("age_band", "45_or_over"),
                      supplemental("morning_stiffness", "none"),
                      prior_surgery=True, surgery_description="شرح جراحی ساختگی برای بازبینی")
    assert result.routine_evaluation_withheld
    assert result.workflow_status == result.baseline_workflow_status == "insufficient_information"


@pytest.mark.parametrize("field,value,provenance", [
    ("exam_mcmurray", "positive", "patient_report"),
    ("exam_squat_anterior_pain", True, "patient_report"),
    ("age_band", "45_or_over", "physician_exam"),
    ("pain_locations", ("anterior",), "physician_exam"),
])
def test_patient_and_physician_provenance_channels_cannot_be_swapped(field, value, provenance):
    with pytest.raises(ValidationError):
        supplemental(field, value, provenance=provenance)


@pytest.mark.parametrize("field,value", [
    ("aggravating_activities", ("none", "stairs")),
    ("aggravating_activities", ("stairs", "stairs")),
    ("pain_locations", ()), ("pain_locations", ("invented",)),
    ("care_goals", "pain"), ("exam_squat_anterior_pain", "true"),
    ("age_band", True), ("morning_stiffness", "30"),
])
def test_invalid_multichoice_and_coerced_scalar_answers_are_rejected(field, value):
    with pytest.raises(ValidationError):
        supplemental(field, value)


def test_unknown_multichoice_cannot_secretly_retain_selections():
    with pytest.raises(ValidationError):
        supplemental("pain_locations", ("anterior",), state="unknown")


def test_duplicate_field_source_pair_is_rejected_without_overwriting_prior_report():
    item = supplemental("age_band", "45_or_over")
    with pytest.raises(ValidationError):
        workbench_request(item, item)


@pytest.mark.parametrize("answer_state", ["unknown", "declined", "unverified", "contradictory"])
def test_missing_legacy_location_never_reasks_an_uncertain_multichoice(answer_state):
    item = supplemental("pain_locations", ("anterior",) if answer_state == "unverified" else None,
                        state=answer_state)
    result = evaluate(item, omit=("pain_location",))
    offered = [row for row in result.next_items if row.field == "pain_locations"]
    assert offered and all(row.category == "physician_review" for row in offered)
    assert not result.workflow_equivalences
    assert all(row.relation == "unavailable" for row in relationships(result, "pain_locations"))


def test_empty_interview_uses_agreed_opening_and_screening_order():
    result = build_knee_workbench({"interview": {"context": {"body_region": "knee"}}})
    fields = [row.field for row in result.next_items if row.category == "patient_question"]
    assert fields[:6] == ["chief_complaint", "laterality", "trauma", "fever", "acute_swelling", "systemic_symptoms"]
    assert fields.index("has_pain") < fields.index("onset")
