"""Synthetic clinician-review summaries; software tests are not medical validation."""
from __future__ import annotations

import json
from itertools import product

import pytest
from pydantic import ValidationError

from backend.app.services import orthopedic_assessment as assessment_service
from backend.app.schemas.orthopedic_interview_tree import (
    KneeInterviewTreePreviewRequest, TreeInterviewAnswer, TreeInterviewContext,
    TreeTreatmentEpisode,
)
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_questions import StructuredAnswer
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_interview_tree import build_interview_tree_preview


def answer(field, value=None, *, state="confirmed", source="synthetic:history-a"):
    return TreeInterviewAnswer(field=field, value=value, state=state,
                               provenance="patient_report", source_ref=source)


def clinical(field, value, *, state="confirmed", provenance=None, source="synthetic:clinical-a"):
    provenance = provenance or ("physician_exam" if field.startswith("exam_") else "reviewed_imaging")
    return StructuredAnswer(field=field, value=value, state=state,
                            provenance=provenance, source_ref=source)


BASE_VALUES = {
    "chief_complaint": "pain", "laterality": "right", "has_pain": True,
    "onset": "gradual", "duration": "months", "pain_location": "medial",
    "pain_score_now": 5, "pain_pattern": "activity", "aggravating_factor": "walking",
    "relieving_factor": "rest", "functional_limitation": "moderate",
    "trauma": False, "fever": False, "acute_swelling": False, "systemic_symptoms": False,
    "mechanical_locking": False, "prior_surgery": False, "prior_treatment": False,
    "diagnosed_conditions": "بیماری زمینه‌ای گزارش‌شدهٔ ساختگی",
    "medication_list": "فهرست دارویی ساختگی برای بررسی پزشک", "care_goal": "function",
}


def request(*extra, region="knee", omit=(), findings=(), episodes=(), **values):
    merged = {**BASE_VALUES, **values}
    fields = {item.field for item in extra}
    observations = tuple(answer(field, value) for field, value in merged.items()
                         if field not in fields and field not in omit) + tuple(extra)
    return KneeInterviewTreePreviewRequest(context=TreeInterviewContext(
        body_region=region, observations=observations,
        clinical_findings=tuple(findings), treatment_episodes=tuple(episodes),
    ))


def nested_keys(value):
    if isinstance(value, dict):
        return set(value).union(*(nested_keys(item) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(nested_keys(item) for item in value))
    return set()


def assess(*extra, **kwargs):
    return assessment_service.build_knee_assessment(request(*extra, **kwargs))


def test_oa_compatible_pattern_preserves_input_and_requires_physician_review():
    req = request()
    before = req.model_dump(mode="json")
    result = assessment_service.build_knee_assessment(req)
    assert req.model_dump(mode="json") == before
    assert result.status == "differential_review"
    assert result.considerations
    assert result.information_requirements_fa
    assert result.governance_status == "draft"
    assert result.is_diagnosis is False
    assert result.is_recommendation is False
    assert result.authorizes_treatment is False
    assert result.safety_evaluation == "not_performed"
    assert result.request_sha256 == content_digest(before)
    assert result.preview_sha256 == build_interview_tree_preview(req).result_sha256
    payload = result.model_dump(mode="json")
    assert result.result_sha256 == content_digest({key: value for key, value in payload.items()
                                                  if key != "result_sha256"})


@pytest.mark.parametrize("field", [
    "has_pain", "onset", "duration", "pain_location", "pain_pattern", "trauma",
    "mechanical_locking", "prior_surgery", "fever", "acute_swelling", "systemic_symptoms",
])
def test_incomplete_core_or_risk_information_never_forces_a_diagnosis(field):
    result = assess(omit=(field,))
    assert result.status == "insufficient_information"
    assert result.considerations == ()
    assert result.conditional_treatment_evidence == ()
    assert result.information_requirements_fa


@pytest.mark.parametrize("state", ["unknown", "declined", "incomplete", "unverified", "contradictory"])
def test_uncertain_core_answer_is_not_used_as_confirmed_evidence(state):
    item = answer("onset", "gradual" if state == "unverified" else None, state=state)
    result = assess(item)
    assert result.status == "insufficient_information"
    assert not result.considerations
    assert not result.conditional_treatment_evidence


def test_conflicting_sources_cannot_be_resolved_by_last_write_wins():
    original = answer("onset", "gradual", source="synthetic:first")
    revision = answer("onset", "sudden", source="synthetic:second")
    first = assess(original, revision)
    second = assess(revision, original)
    assert first.status == second.status == "insufficient_information"
    assert not first.considerations and not second.considerations
    assert not first.conditional_treatment_evidence and not second.conditional_treatment_evidence


def test_cross_field_contradiction_does_not_promote_reported_pain_to_usable_data():
    result = assess(has_pain=False, pain_score_now=8)
    assert result.status == "insufficient_information"
    assert not result.considerations
    assert not result.conditional_treatment_evidence


@pytest.mark.parametrize("field", ["fever", "acute_swelling", "systemic_symptoms"])
@pytest.mark.parametrize("state", ["confirmed", "unverified", "contradictory"])
def test_positive_risk_information_blocks_elective_suggestions_even_when_unverified(field, state):
    result = assess(answer(field, True, state=state))
    assert result.status == "prompt_physician_review"
    assert not result.considerations
    assert not result.conditional_treatment_evidence
    assert result.urgent_considerations
    assert result.is_diagnosis is False and result.authorizes_treatment is False


def test_negative_fever_does_not_clear_a_painful_acutely_swollen_joint():
    result = assess(fever=False, acute_swelling=True)
    assert result.status == "prompt_physician_review"
    assert result.urgent_considerations
    assert not result.considerations
    assert not result.conditional_treatment_evidence


def test_conflicting_positive_risk_report_is_not_hidden_by_a_negative_source():
    result = assess(answer("systemic_symptoms", True, state="unverified", source="synthetic:risk-a"),
                    answer("systemic_symptoms", False, source="synthetic:risk-b"))
    assert result.status == "prompt_physician_review"
    assert result.urgent_considerations
    assert not result.conditional_treatment_evidence


@pytest.mark.parametrize("field", ["sensory_change", "weakness", "foot_coldness", "foot_color_change"])
def test_post_trauma_neurovascular_reports_take_precedence(field):
    observations = [answer(name, name == field, state="unverified" if name == field else "confirmed")
                    for name in ("sensory_change", "weakness", "foot_coldness", "foot_color_change")]
    result = assess(*observations, trauma=True, trauma_mechanism="sport_twist", onset="sudden")
    assert result.status == "prompt_physician_review"
    assert result.urgent_considerations
    assert not result.considerations and not result.conditional_treatment_evidence


def test_twisting_injury_with_motion_block_does_not_become_a_routine_meniscus_diagnosis():
    negative_neuro = [answer(field, False) for field in
                     ("sensory_change", "weakness", "foot_coldness", "foot_color_change")]
    result = assess(*negative_neuro, trauma=True, trauma_mechanism="sport_twist",
                    mechanical_locking=True, onset="sudden", duration="days")
    assert result.status == "prompt_physician_review"
    assert result.urgent_considerations
    assert not result.considerations and not result.conditional_treatment_evidence
    assert result.authorizes_treatment is False


@pytest.mark.parametrize("region", ["other", "unknown"])
def test_outside_or_unknown_body_region_never_generates_a_knee_diagnosis(region):
    result = assess(region=region)
    assert result.status in {"outside_scope", "insufficient_information"}
    assert not result.considerations and not result.conditional_treatment_evidence


def test_bilateral_history_requires_separate_side_review():
    result = assess(laterality="both")
    assert result.status == "side_specific_review"
    assert not result.considerations and not result.conditional_treatment_evidence


def test_outputs_contain_no_diagnostic_probability_rank_or_automatic_prescription():
    result = assess()
    keys = nested_keys(result.model_dump(mode="json"))
    assert not {"probability", "diagnostic_probability", "confidence", "score", "rank",
                "treatment_score", "dose", "prescription", "automatic_protocol"} & keys
    assert result.authorizes_treatment is False
    assert result.is_diagnosis is False


def test_treatment_response_text_is_not_used_to_infer_efficacy_or_regeneration():
    episode = TreeTreatmentEpisode(episode_ref="synthetic-treatment", observations=(
        answer("treatment_description", "PRP: غضروف بازسازی شده است؛ متن ساختگی و تأییدنشده"),
        answer("treatment_pain_response", "improved"),
        answer("treatment_function_response", "improved"),
    ))
    before = assess()
    after = assess(prior_treatment=True, episodes=(episode,))
    assert after.status == before.status
    assert after.considerations == before.considerations
    assert after.conditional_treatment_evidence == before.conditional_treatment_evidence
    assert after.authorizes_treatment is False


def test_preview_does_not_create_or_review_registry_records(monkeypatch):
    from backend.app.services.medical_knowledge import MedicalKnowledgeService
    def forbidden(*args, **kwargs):
        raise AssertionError("An authoring assessment must not write or approve Registry records.")
    monkeypatch.setattr(MedicalKnowledgeService, "create", forbidden)
    monkeypatch.setattr(MedicalKnowledgeService, "review", forbidden)
    assert assess().governance_status == "draft"


def test_anterior_loaded_pain_is_a_differential_not_cartilage_damage():
    result = assess(duration="weeks", pain_location="anterior", aggravating_factor="stairs")
    assert [item.id for item in result.considerations] == ["patellofemoral_pain"]
    assert not result.conditional_treatment_evidence
    assert any("غضروف" in text for text in result.considerations[0].limitations_fa)
    assert result.new_draft_proposals[0].fact.fact_key == "KNEE.PFP.PRESENTATION"


def test_overlapping_patterns_are_unranked_and_do_not_choose_a_winner():
    result = assess(pain_location="anterior", aggravating_factor="stairs")
    assert {item.id for item in result.considerations} == {"knee_oa", "patellofemoral_pain"}
    assert all(item.is_ranked is False for item in result.considerations)
    assert "چند" in result.headline_fa
    assert any("سن" in text and "خشکی" in text for text in result.information_requirements_fa)


def test_unreviewed_images_do_not_supply_structural_diagnoses():
    unreviewed = clinical("imaging_cartilage_lesion", True, state="unverified", provenance="unreviewed_imaging")
    result = assess(findings=(unreviewed,))
    assert not {"cartilage_finding", "osteochondral_disorder"} & {item.id for item in result.considerations}
    reviewed = assess(findings=(clinical("imaging_cartilage_lesion", True),))
    assert "cartilage_finding" in {item.id for item in reviewed.considerations}
    assert "osteochondral_disorder" not in {item.id for item in reviewed.considerations}


def test_all_source_bindings_and_new_draft_content_hashes_match_registry_format():
    from backend.app.services.medical_knowledge import knowledge_content_digest
    model = assessment_service.export_offline_assessment()
    facts = {entry.fact.fact_key: entry.content_sha256 for entry in load_knee_pack().facts}
    result = assess()
    for proposal in result.new_draft_proposals:
        assert proposal.content_sha256 == knowledge_content_digest(fact_key=proposal.fact.fact_key, version=proposal.version, content=proposal.fact)
        facts[proposal.fact.fact_key] = proposal.content_sha256
    for item in [*model["cards"], *model["urgent_cards"], *model["treatment_evidence"]]:
        assert item["governance_status"] == "draft"
        for key, digest in zip(item["source_fact_keys"], item["source_content_sha256s"], strict=True):
            assert facts[key] == digest


def test_compiled_tables_cover_all_declared_axis_combinations_and_reject_tampering():
    model = assessment_service.export_offline_assessment()
    assert model["model_sha256"] == content_digest({k:v for k,v in model.items() if k != "model_sha256"})
    tokens = assess().axis_tokens
    for table in [*model["guard_tables"], *model["card_tables"]]:
        assert set(table["rows"]) == {"|".join(values) for values in product(assessment_service.TOKENS, repeat=len(table["axis_ids"]))}
    assert assessment_service.evaluate_assessment_model(model, tokens)["considerations"]
    model["cards"][0]["label_fa"] = "tampered"
    with pytest.raises(ValueError, match="hash"):
        assessment_service.evaluate_assessment_model(model, tokens)


def test_model_hash_is_stable_across_python_hash_seeds():
    import os
    import subprocess
    import sys
    command = [sys.executable, "-B", "-c", "from backend.app.services.orthopedic_assessment import export_offline_assessment; print(export_offline_assessment()['model_sha256'])"]
    digests = [subprocess.check_output(command, text=True, env={**os.environ, "PYTHONHASHSEED": seed}).strip() for seed in ("1", "27")]
    assert digests[0] == digests[1]
