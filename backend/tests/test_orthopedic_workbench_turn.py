"""Synthetic turn-protocol checks; these do not validate diagnostic accuracy."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest
from backend.app.schemas.orthopedic_workbench_turn import (
    KneeWorkbenchTurnRequest, WorkbenchResponseEvent,
)
from backend.app.services.orthopedic_workbench import build_knee_workbench
from backend.app.services.orthopedic_workbench_turn import apply_knee_workbench_turn
from backend.tests.test_orthopedic_assessment import answer, request


def state(*extra, **kwargs):
    return KneeWorkbenchRequest(interview=request(*extra, **kwargs))


def event(field, value=None, *, respondent="patient", provenance="patient_report",
          source="synthetic:turn", answer_state="confirmed", episode_ref=None):
    return {
        "respondent": respondent,
        "observation": {"field": field, "value": value, "state": answer_state,
                        "provenance": provenance, "source_ref": source},
        "episode_ref": episode_ref,
    }


def apply(current, field, value=None, **kwargs):
    return apply_knee_workbench_turn({"state": current.model_dump(mode="json"),
                                      "answer": event(field, value, **kwargs)})


def patient_fields(workbench):
    return {item.field for item in workbench.next_items
            if item.category == "patient_question" and item.action == "ask_missing"}


def test_response_opens_a_follow_up_branch_and_preserves_prior_answers():
    current = state(omit=("mechanical_locking",))
    before = current.model_dump(mode="json")
    assert "pain_limited_motion" not in patient_fields(build_knee_workbench(current))
    result = apply(current, "mechanical_locking", True)
    assert "pain_limited_motion" in patient_fields(result.workbench)
    assert current.model_dump(mode="json") == before
    original = result.state.interview.context.observations[:-1]
    assert original == current.interview.context.observations
    assert result.state.interview.context.observations[-1].value is True
    assert result.next_patient_question is not None
    assert result.next_patient_question in result.workbench.next_items
    assert result.next_patient_question.question.channel == "patient_report"


def test_negative_answer_keeps_the_conditional_branch_closed():
    result = apply(state(omit=("mechanical_locking",)), "mechanical_locking", False)
    assert "pain_limited_motion" not in patient_fields(result.workbench)
    assert result.state.interview.context.observations[-1].value is False


def test_multi_select_preserves_every_location_without_a_fabricated_scalar():
    current = state(omit=("pain_location",))
    assert "pain_locations" in patient_fields(build_knee_workbench(current))
    result = apply(current, "pain_locations", ["anterior", "medial"])
    supplied = result.state.supplemental_observations[-1]
    assert supplied.field == "pain_locations"
    assert supplied.value == ("anterior", "medial")
    assert not any(row.field == "pain_location" for row in result.state.interview.context.observations)
    assert "pain_locations" not in patient_fields(result.workbench)
    assert result.workbench == build_knee_workbench(result.state)


def test_more_than_one_aggravating_activity_remains_one_multi_answer():
    result = apply(state(omit=("aggravating_factor",)), "aggravating_activities",
                   ["stairs", "loaded_flexion"])
    assert result.state.supplemental_observations[-1].value == ("stairs", "loaded_flexion")
    assert not any(row.field == "aggravating_factor"
                   for row in result.state.interview.context.observations)


@pytest.mark.parametrize("answer_state", ["unknown", "declined"])
def test_uncertain_multi_location_is_not_reoffered_after_response(answer_state):
    result = apply(state(omit=("pain_location",)), "pain_locations", answer_state=answer_state)
    assert "pain_locations" not in patient_fields(result.workbench)
    assert result.workbench.routine_evaluation_withheld
    assert result.next_patient_question is None or result.next_patient_question.field != "pain_locations"


@pytest.mark.parametrize("answer_state", ["unknown", "declined"])
def test_unknown_or_declined_answer_is_retained_without_automatic_repeat(answer_state):
    result = apply(state(), "age_band", answer_state=answer_state)
    row = result.state.supplemental_observations[-1]
    assert row.field == "age_band" and row.state == answer_state and row.value is None
    assert "age_band" not in patient_fields(result.workbench)
    assert any(item.field == "age_band" for item in result.workbench.quarantined_observations)


@pytest.mark.parametrize("field,value,provenance", [
    ("exam_squat_anterior_pain", True, "physician_exam"),
    ("exam_mcmurray", "positive", "physician_exam"),
    ("exam_joint_line_tenderness", True, "physician_exam"),
    ("imaging_cartilage_lesion", True, "reviewed_imaging"),
])
def test_patient_response_cannot_record_examination_or_reviewed_imaging(field, value, provenance):
    with pytest.raises(ValidationError):
        WorkbenchResponseEvent.model_validate(event(field, value, provenance=provenance))


def test_offered_physician_examination_changes_the_actual_evidence_ledger():
    current = state(pain_location="anterior", aggravating_factor="stairs")
    baseline = build_knee_workbench(current)
    pfp_before = next(item for item in baseline.comparisons if item.id == "pfp")
    assert next(row for row in pfp_before.relationships if row.field == "exam_squat_anterior_pain").relation == "unavailable"
    result = apply(current, "exam_squat_anterior_pain", True, respondent="physician",
                   provenance="physician_exam", source="synthetic:exam-turn")
    pfp_after = next(item for item in result.workbench.comparisons if item.id == "pfp")
    finding = next(row for row in pfp_after.relationships if row.field == "exam_squat_anterior_pain")
    assert finding.relation == "supports"
    assert finding.observations[0].provenance == "physician_exam"
    assert finding.observations[0].source_ref == "synthetic:exam-turn"
    assert result.workbench.is_diagnosis is False


@pytest.mark.parametrize("value", [["none", "stairs"], ["stairs", "stairs"], [], ["internet_invented"]])
def test_multi_select_rejects_incompatible_duplicate_empty_or_unknown_options(value):
    with pytest.raises(ValidationError):
        WorkbenchResponseEvent.model_validate(event("aggravating_activities", value))


def test_answer_to_a_closed_or_unoffered_branch_is_rejected():
    with pytest.raises(ValueError, match="offered"):
        apply(state(trauma=False), "trauma_mechanism", "sport_twist")
    with pytest.raises(ValueError, match="offered"):
        apply(state(), "prior_surgery", True)


def test_outside_knee_scope_cannot_start_a_routine_knee_interview():
    with pytest.raises(ValueError, match="offered"):
        apply(state(region="other"), "age_band", "45_or_over")


def test_unknown_answer_cannot_be_used_to_send_hidden_selected_values():
    with pytest.raises(ValidationError):
        WorkbenchResponseEvent.model_validate(event("pain_locations", ["anterior"], answer_state="unknown"))


def test_each_treatment_response_is_scoped_and_next_fields_are_recomputed():
    current = state(prior_treatment=True)
    assert "treatment_description" in patient_fields(build_knee_workbench(current))
    result = apply(current, "treatment_description", "درمان ساختگی برای آزمون",
                   episode_ref="synthetic-treatment-a")
    episode = result.state.interview.context.treatment_episodes[0]
    assert episode.episode_ref == "synthetic-treatment-a"
    assert episode.observations[0].value == "درمان ساختگی برای آزمون"
    assert {"treatment_pain_response", "treatment_function_response"} <= patient_fields(result.workbench)
    followup = apply(result.state, "treatment_pain_response", "improved",
                     source="synthetic:outcome", episode_ref="synthetic-treatment-a")
    assert len(followup.state.interview.context.treatment_episodes) == 1
    assert len(followup.state.interview.context.treatment_episodes[0].observations) == 2
    assert "treatment_function_response" in patient_fields(followup.workbench)
    assert followup.workbench.management_review.infers_treatment_efficacy is False
    assert followup.workbench.management_review.infers_cartilage_regeneration is False


@pytest.mark.parametrize("field,episode_ref", [
    ("age_band", "unrelated-episode"), ("treatment_pain_response", None),
])
def test_only_treatment_answers_require_episode_reference(field, episode_ref):
    value = "45_or_over" if field == "age_band" else "improved"
    with pytest.raises(ValidationError):
        WorkbenchResponseEvent.model_validate(event(field, value, episode_ref=episode_ref))


def test_risk_information_retains_hold_after_a_response():
    current = state(omit=("fever",))
    result = apply(current, "fever", True)
    assert result.workbench.workflow_status == "prompt_physician_review"
    assert result.workbench.routine_evaluation_withheld is True
    assert result.workbench.baseline_review.baseline_assessment.conditional_treatment_evidence == ()
    assert result.next_patient_question is None


def test_a_prior_surgery_hold_is_not_cleared_by_answering_age():
    result = apply(state(prior_surgery=True, surgery_description="عمل ساختگی"),
                   "age_band", "45_or_over")
    assert result.workbench.routine_evaluation_withheld is True
    assert result.workbench.baseline_review.baseline_assessment.conditional_treatment_evidence == ()


def test_turn_and_updated_workbench_have_reproducible_bound_hashes():
    current = state()
    payload = {"state": current.model_dump(mode="json"), "answer": event("age_band", "45_or_over")}
    result = apply_knee_workbench_turn(payload)
    assert result == apply_knee_workbench_turn(payload)
    assert result.prior_state_sha256 == content_digest(payload["state"])
    canonical_request = KneeWorkbenchTurnRequest.model_validate(payload).model_dump(mode="json")
    assert result.request_sha256 == content_digest(canonical_request)
    assert result.result_sha256 == content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))
    assert result.workbench.request_sha256 == content_digest(result.state.model_dump(mode="json"))
    assert result.registry_write_performed is False
    assert result.authenticated_provenance is False
    assert result.is_diagnosis is False


def test_request_rejects_undeclared_patient_identifiers():
    payload = {"state": state().model_dump(mode="json"), "answer": event("age_band", "45_or_over")}
    payload["patient_name"] = "synthetic-identifying-field"
    with pytest.raises(ValidationError):
        KneeWorkbenchTurnRequest.model_validate(payload)


def test_legacy_patient_field_cannot_be_smuggled_into_clinical_union():
    with pytest.raises(ValidationError):
        WorkbenchResponseEvent.model_validate(event("pain_score", 5))


def test_conflicting_existing_reports_are_never_overwritten_by_a_turn():
    current = state(answer("onset", "gradual", source="synthetic:a"),
                    answer("onset", "sudden", source="synthetic:b"))
    before = current.model_dump(mode="json")
    result = apply(current, "onset", "gradual", respondent="physician", source="synthetic:c")
    rows = [row for row in result.state.interview.context.observations if row.field == "onset"]
    assert len(rows) == 3
    assert {row.source_ref for row in rows} == {"synthetic:a", "synthetic:b", "synthetic:c"}
    assert current.model_dump(mode="json") == before
    assert result.workbench.routine_evaluation_withheld is True


def test_duplicate_field_source_cannot_overwrite_a_conflicting_record():
    current = state(answer("onset", "gradual", source="synthetic:a"),
                    answer("onset", "sudden", source="synthetic:b"))
    with pytest.raises(ValueError, match="immutable"):
        apply(current, "onset", "gradual", respondent="physician", source="synthetic:a")
