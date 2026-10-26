"""Source-backed pain/injury review invariants, not clinical validation."""
from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest
from backend.app.services.medical_knowledge import knowledge_content_digest
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_pain_injury import build_knee_pain_injury_review, load_organizing_source_snapshot
from backend.app.services.orthopedic_workbench import build_knee_workbench
from backend.app.services.orthopedic_pain_injury_turn import apply_knee_pain_injury_turn
from backend.app.services.orthopedic_workbench_turn import apply_knee_workbench_turn
from backend.tests.test_orthopedic_assessment import answer, clinical, request
from backend.tests.test_orthopedic_workbench import supplemental


def review(*extras, **kwargs):
    return build_knee_pain_injury_review(KneeWorkbenchRequest(
        interview=request(**kwargs), supplemental_observations=extras,
    ))


def route(result, identifier):
    return next(item for item in result.routes if item.id == identifier)


def test_backbone_preserves_request_and_existing_workbench_without_writes():
    current = KneeWorkbenchRequest(interview=request())
    before = deepcopy(current.model_dump(mode="json"))
    result = build_knee_pain_injury_review(current)
    assert current.model_dump(mode="json") == before
    assert result.workbench == build_knee_workbench(current)
    assert result.organizing_source_role == "primary_organizing_source"
    assert result.organizing_source.source.url == "https://zetamed.org/knee-pain/"
    assert result.organizing_source.source.publication_date.isoformat() == "2025-09-05"
    assert result.approved_fact_count == 0
    assert not result.registry_write_performed and not result.authorizes_treatment
    assert not result.is_diagnosis and not result.is_clinically_validated
    assert result.safety_engine_required and result.safety_evaluation == "not_performed"


def test_article_organizes_every_route_with_independent_clinical_bindings():
    result = review()
    comparisons = {item.id for item in result.workbench.comparisons}
    assert len(result.routes) == 8
    for item in result.routes:
        assert item.article_section_locator
        assert item.source_fact_keys
        assert len(item.source_fact_keys) == len(item.source_content_sha256s)
        assert set(item.differential_comparison_ids) <= comparisons
        assert item.limitations_fa
        assert item.is_excluded is False and item.is_ranked is False
    # The website is the organizing source, not evidence of treatment benefit.
    for proposal in result.new_draft_proposals:
        assert all("zetamed.org" not in (source.url or "") for source in proposal.fact.sources)


def test_unimplemented_domains_remain_explicit_coverage_gaps_and_never_excluded():
    result = review()
    assert {item.id for item in result.coverage_gaps} >= {
        "ligament", "fracture_dislocation", "inflammatory", "periarticular", "biomechanical",
    }
    for item in result.coverage_gaps:
        assert item.status == "not_implemented" and item.is_excluded is False
        assert item.reason_fa and item.label_fa


def test_every_clinical_route_reference_resolves_to_a_real_registry_content_hash():
    result = review()
    expected = {item.fact.fact_key: item.content_sha256 for item in load_knee_pack().facts}
    expected.update({item.fact.fact_key: item.content_sha256 for item in (
        *result.workbench.new_draft_proposals,
        *result.workbench.baseline_review.baseline_assessment.new_draft_proposals,
        *result.new_draft_proposals,
    )})
    for dimension in result.routes:
        for key, digest in zip(dimension.source_fact_keys, dimension.source_content_sha256s, strict=True):
            assert key in expected and digest == expected[key]


def test_sudden_onset_and_long_duration_remain_independent_observations():
    result = review(onset="sudden", duration="years", pain_score_now=0)
    chronology = route(result, "temporal_course")
    actual = {item.field: item for item in chronology.observations if item.usability == "usable"}
    assert actual["onset"].value == "sudden"
    assert actual["duration"].value == "years"
    assert actual["onset"].source_ref == "synthetic:history-a"
    assert actual["duration"].source_ref == "synthetic:history-a"
    pain = next(item for item in result.workbench.baseline_review.problem_representation.history
                if item.field == "pain_score_now")
    assert pain.value == 0
    assert all(not item.is_excluded for item in result.routes)


def test_known_onset_with_missing_duration_remains_partial_without_discarding_known_data():
    result = review(onset="sudden", omit=("duration",))
    chronology = route(result, "temporal_course")
    assert chronology.status == "information_missing"
    assert any(item.field == "onset" and item.value == "sudden" and item.usability == "usable"
               for item in chronology.observations)
    assert not any(item.field == "duration" and item.usability == "usable" for item in chronology.observations)


def test_a_single_negative_risk_report_is_not_a_complete_negative_risk_context():
    result = review(fever=False, omit=("acute_swelling", "systemic_symptoms"))
    risk = route(result, "inflammatory_and_risk")
    assert risk.status == "information_missing"
    assert any(item.field == "fever" and item.value is False for item in risk.observations)
    assert result.workbench.routine_evaluation_withheld
    assert not result.is_clinical_clearance


@pytest.mark.parametrize("field", ["onset", "duration", "trauma"])
@pytest.mark.parametrize("state", ["unknown", "declined", "unverified", "contradictory"])
def test_uncertain_reports_do_not_become_negative_or_usable_route_evidence(field, state):
    value = {"onset": "sudden", "duration": "days", "trauma": True}[field] if state == "unverified" else None
    extra = answer(field, value, state=state, source="synthetic:uncertain")
    result = build_knee_pain_injury_review(KneeWorkbenchRequest(interview=request(extra)))
    affected = [item for item in result.routes if any(row.field == field for row in item.observations)]
    observations = [row for item in affected for row in item.observations if row.field == field]
    assert observations
    assert all(row.usability == "quarantined" for row in observations)
    assert all(not item.is_excluded for item in result.routes)
    assert result.workbench.routine_evaluation_withheld


def test_conflicting_duration_sources_are_preserved_without_last_write_wins():
    first = answer("duration", "days", source="synthetic:first")
    second = answer("duration", "years", source="synthetic:second")
    result = build_knee_pain_injury_review(KneeWorkbenchRequest(interview=request(first, second)))
    observations = [row for row in route(result, "temporal_course").observations if row.field == "duration"]
    assert {item.value for item in observations} == {"days", "years"}
    assert {item.source_ref for item in observations} == {"synthetic:first", "synthetic:second"}
    assert all(item.usability == "quarantined" for item in observations)
    assert result.workbench.routine_evaluation_withheld


def test_trauma_with_locking_is_a_review_context_and_preserves_urgent_hold():
    result = review(trauma=True, duration="days", onset="sudden", trauma_mechanism="sport_twist",
                    mechanical_locking=True, pain_limited_motion=False,
                    sensory_change=False, weakness=False, foot_coldness=False, foot_color_change=False)
    assert route(result, "trauma_context").status == "context_present"
    assert route(result, "mechanical_symptoms").status == "context_present"
    assert result.workbench.routine_evaluation_withheld
    assert not result.is_diagnosis and not result.authorizes_treatment
    assert all(not item.is_excluded and not item.is_ranked for item in result.routes)


def test_instability_report_does_not_become_a_confirmed_ligament_tear():
    result = review(chief_complaint="instability", has_pain=False,
                    omit=("pain_location", "pain_score_now", "pain_pattern", "aggravating_factor", "relieving_factor"))
    mechanical = route(result, "mechanical_symptoms")
    assert any(item.field == "chief_complaint" and item.value == "instability" for item in mechanical.observations)
    assert mechanical.status == "context_present"
    assert not result.is_diagnosis
    assert all(not item.is_excluded for item in result.routes)


def test_raw_positive_unverified_risk_is_retained_without_confirming_infection():
    raw = answer("fever", True, state="unverified", source="synthetic:raw-risk")
    result = build_knee_pain_injury_review(KneeWorkbenchRequest(interview=request(raw)))
    rows = [item for item in result.raw_risk_observations if item.source_ref == "synthetic:raw-risk"]
    assert rows and rows[0].value is True and rows[0].state == "unverified"
    assert rows[0].usability == "quarantined"
    assert result.workbench.workflow_status == "prompt_physician_review"
    assert result.workbench.routine_evaluation_withheld
    assert not result.is_diagnosis and result.safety_evaluation == "not_performed"


def test_multi_locations_remain_in_the_anterior_review_without_scalar_collapse():
    result = review(supplemental("pain_locations", ("anterior", "medial")),
                    supplemental("aggravating_activities", ("stairs", "walking")),
                    omit=("pain_location", "aggravating_factor"))
    anterior = route(result, "anterior_loaded_pain")
    values = {row.field: row.value for row in anterior.observations if row.usability == "usable"}
    assert values["pain_locations"] == ("anterior", "medial")
    assert values["aggravating_activities"] == ("stairs", "walking")
    assert anterior.status == "context_present"
    assert not any(row.field == "pain_location" for row in result.workbench.baseline_review.problem_representation.history)


@pytest.mark.parametrize("region,expected", [("other", "outside_scope"), ("unknown", "insufficient_information")])
def test_article_context_cannot_clear_existing_body_scope_hold(region, expected):
    result = review(region=region)
    assert result.workbench.workflow_status == expected
    assert result.workbench.routine_evaluation_withheld
    assert all(not item.is_excluded for item in result.routes)


def test_article_context_cannot_clear_prior_surgery_hold():
    result = review(prior_surgery=True, surgery_description="شرح جراحی ساختگی برای بازبینی")
    assert result.workbench.routine_evaluation_withheld
    assert result.workbench.workflow_status == "insufficient_information"


def test_reviewed_image_is_not_promoted_to_pain_cause_or_treatment_effect():
    result = review(findings=(clinical("imaging_cartilage_lesion", True),))
    assert not result.is_diagnosis and not result.authorizes_treatment
    assert not result.workbench.management_review.infers_treatment_efficacy
    assert not result.workbench.management_review.infers_cartilage_regeneration
    assert all(not item.is_excluded for item in result.routes)


def test_new_propositions_use_registry_digest_and_remain_independent_drafts():
    result = review()
    assert len(result.new_draft_proposals) == 2
    for item in result.new_draft_proposals:
        assert item.governance_status == "draft" and item.requires_independent_review
        assert item.content_sha256 == knowledge_content_digest(
            fact_key=item.fact.fact_key, version=item.version, content=item.fact,
        )
        assert item.fact.sources
    assert result.approved_fact_count == 0


def test_all_hashes_are_deterministic_and_result_binds_complete_normalized_output():
    current = KneeWorkbenchRequest(interview=request())
    first = build_knee_pain_injury_review(current)
    second = build_knee_pain_injury_review(current)
    assert first == second
    assert first.request_sha256 == content_digest(current.model_dump(mode="json"))
    payload = first.model_dump(mode="json", exclude={"result_sha256"})
    assert first.result_sha256 == content_digest(payload)
    assert len(first.rules_sha256) == len(first.source_set_sha256) == 64


def test_source_snapshot_is_bound_to_output_without_inventing_a_text_hash():
    snapshot = load_organizing_source_snapshot()
    result = review()
    assert result.source_document_sha256 == snapshot["source_document_sha256"]
    assert result.source_snapshot_metadata_sha256 == snapshot["metadata_sha256"]
    assert snapshot["source_text_retained"] is False
    assert snapshot["is_medical_approval"] is False
    assert snapshot["response_body_byte_count"] > 0
    assert snapshot["metadata_sha256"] == content_digest({
        key: value for key, value in snapshot.items() if key != "metadata_sha256"
    })


def test_an_explicit_synthetic_metadata_revision_changes_source_rule_and_result_hashes():
    current = KneeWorkbenchRequest(interview=request())
    original = build_knee_pain_injury_review(current)
    revised = deepcopy(load_organizing_source_snapshot())
    revised["source_version"] = "Synthetic metadata revision for software hashing test only."
    revised["metadata_sha256"] = content_digest({
        key: value for key, value in revised.items() if key != "metadata_sha256"
    })
    changed = build_knee_pain_injury_review(current, source_snapshot=revised)
    assert changed.request_sha256 == original.request_sha256
    assert changed.source_document_sha256 == original.source_document_sha256
    assert changed.source_snapshot_metadata_sha256 != original.source_snapshot_metadata_sha256
    assert changed.source_set_sha256 != original.source_set_sha256
    assert changed.rules_sha256 != original.rules_sha256 and changed.result_sha256 != original.result_sha256


@pytest.mark.parametrize("key,value", [
    ("retrieved_at", "2000-01-01T00:00:00+00:00"),
    ("source_document_sha256", "0" * 64),
    ("response_body_byte_count", 0),
])
def test_source_snapshot_tampering_is_rejected(key, value):
    snapshot = load_organizing_source_snapshot()
    broken = deepcopy(snapshot)
    broken[key] = value
    with pytest.raises(ValueError):
        load_organizing_source_snapshot(broken)


def test_other_site_cannot_replace_the_requested_backbone_even_with_rehashed_metadata():
    snapshot = deepcopy(load_organizing_source_snapshot())
    snapshot["url"] = snapshot["resolved_url"] = "https://example.org/knee-pain/"
    snapshot["metadata_sha256"] = content_digest({
        key: value for key, value in snapshot.items() if key != "metadata_sha256"
    })
    with pytest.raises(ValueError):
        load_organizing_source_snapshot(snapshot)


@pytest.mark.parametrize("key", ["source_text_retained", "is_medical_approval"])
def test_rehashing_does_not_turn_source_snapshot_into_retained_text_or_approval(key):
    snapshot = deepcopy(load_organizing_source_snapshot())
    snapshot[key] = True
    snapshot["metadata_sha256"] = content_digest({
        field: value for field, value in snapshot.items() if field != "metadata_sha256"
    })
    with pytest.raises(ValueError):
        load_organizing_source_snapshot(snapshot)


def test_new_question_links_are_existing_offered_items_and_keep_channels():
    result = review(omit=("trauma", "onset", "duration"))
    offered = {item.id: item for item in result.workbench.next_items}
    linked = [item for dimension in result.routes for item in dimension.question_links]
    assert linked
    for item in linked:
        assert item.id in offered and item == offered[item.id]
        if item.category == "patient_question":
            assert item.question and item.question.channel == "patient_report"
        if item.category == "clinician_exam":
            assert item.question and item.question.channel == "physician_exam"


@pytest.mark.parametrize("field,value", [("is_diagnosis", True), ("authorizes_treatment", True),
                                        ("registry_write_performed", True), ("approved_fact_count", 1)])
def test_review_governance_cannot_be_overridden_in_serialized_output(field, value):
    result = review()
    payload = result.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        type(result).model_validate(payload)


def response_event(field, value, *, state="confirmed"):
    return {"respondent": "patient", "observation": {
        "field": field, "value": value, "state": state,
        "provenance": "patient_report", "source_ref": "synthetic:pain-injury-turn",
    }}


def test_new_turn_preserves_existing_state_next_question_and_hash_reference():
    event = {
        "state": KneeWorkbenchRequest(interview=request(omit=("trauma",))).model_dump(mode="json"),
        "answer": response_event("trauma", True),
    }
    before = deepcopy(event)
    original = apply_knee_workbench_turn(event)
    result = apply_knee_pain_injury_turn(event)
    assert event == before
    assert result.state == original.state
    assert result.review.workbench == original.workbench
    assert result.next_patient_question == original.next_patient_question
    assert result.turn_result_sha256 == original.result_sha256
    assert route(result.review, "trauma_context").status == "context_present"
    if result.next_patient_question:
        expected = tuple(item.id for item in result.review.routes
                         if any(link.id == result.next_patient_question.id for link in item.question_links))
        assert result.next_question_route_ids == expected
    assert result.result_sha256 == content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))


def test_multiselect_turn_preserves_all_choices_and_updates_anterior_route():
    event = {
        "state": KneeWorkbenchRequest(interview=request(omit=("pain_location",))).model_dump(mode="json"),
        "answer": response_event("pain_locations", ["anterior", "medial"]),
    }
    result = apply_knee_pain_injury_turn(event)
    selected = result.state.supplemental_observations[-1]
    assert selected.value == ("anterior", "medial")
    actual = [item for item in route(result.review, "anterior_loaded_pain").observations
              if item.field == "pain_locations"]
    assert actual and actual[0].value == ("anterior", "medial")
    assert not any(row.field == "pain_location" for row in result.state.interview.context.observations)


def test_raw_risk_in_new_turn_stops_routine_questioning_and_is_not_a_diagnosis():
    event = {
        "state": KneeWorkbenchRequest(interview=request(omit=("fever",))).model_dump(mode="json"),
        "answer": response_event("fever", True, state="unverified"),
    }
    result = apply_knee_pain_injury_turn(event)
    assert result.next_patient_question is None and result.next_question_route_ids == ()
    assert result.review.workbench.workflow_status == "prompt_physician_review"
    assert any(item.field == "fever" and item.value is True and item.state == "unverified"
               for item in result.review.raw_risk_observations)
    assert result.review.is_diagnosis is False and result.registry_write_performed is False


def test_unknown_multichoice_turn_does_not_repeat_the_question_or_invent_a_location():
    event = {
        "state": KneeWorkbenchRequest(interview=request(omit=("pain_location",))).model_dump(mode="json"),
        "answer": response_event("pain_locations", None, state="unknown"),
    }
    result = apply_knee_pain_injury_turn(event)
    assert result.state.supplemental_observations[-1].state == "unknown"
    assert result.next_patient_question is None or result.next_patient_question.field != "pain_locations"
    assert result.review.workbench.routine_evaluation_withheld
