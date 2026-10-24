"""Synthetic book-aware authoring previews; no medical-validation claim."""
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.schemas.orthopedic_book_questions import BookQuestionPreview, BookQuestionPreviewRequest
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext, StructuredAnswer
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError, MedicalKnowledgeService
from backend.app.services import orthopedic_book_questions as bridge_service
from backend.app.services.orthopedic_book_questions import build_book_question_preview
from backend.app.services.orthopedic_book_review import load_knee_book_review_pack
from backend.app.services.orthopedic_knowledge import PACK_PATH, load_knee_pack
from backend.app.services.orthopedic_questions import select_questions


SCOPES = (
    "arthroplasty_review", "meniscus_review", "cartilage_review",
    "ocd_review", "prp_evidence_review",
)


def answer(field, value=None, *, state="confirmed", provenance=None, source="synthetic:intake-v1"):
    if provenance is None:
        provenance = ("physician_exam" if field.startswith("exam_") else
                      "reviewed_imaging" if field.startswith("imaging_") else "patient_report")
    return StructuredAnswer(field=field, state=state, value=value,
                            provenance=provenance, source_ref=source)


def request(*observations, scopes=(), region="knee"):
    return BookQuestionPreviewRequest(
        context=OrthopedicQuestionContext(body_region=region, observations=observations),
        review_scopes=scopes,
    )


def referenced_card_keys(result):
    return {key for card in result.clinician_review_requirements for key in card.candidate_keys}


@pytest.mark.parametrize("scenario,req,expected_field", [
    ("gradual_pain_with_known_function", request(
        answer("chief_complaint", "pain"), answer("onset", "gradual"),
        answer("duration", "years"), answer("functional_limitation", "moderate"),
        scopes=("arthroplasty_review",)), "pain_score"),
    ("sports_trauma_with_mechanical_symptoms", request(
        answer("trauma", True), answer("mechanical_locking", True),
        scopes=("meniscus_review",)), "trauma_mechanism"),
    ("incomplete_history_and_declined_answer", request(
        answer("duration", state="incomplete"), answer("pain_score", state="declined"),
        scopes=("arthroplasty_review",)), "duration"),
    ("contradictory_examination", request(
        answer("exam_effusion", True, source="synthetic:exam-a"),
        answer("exam_effusion", False, source="synthetic:exam-b"),
        scopes=("meniscus_review",)), "chief_complaint"),
    ("hot_swollen_joint_and_fever", request(
        answer("fever", True), answer("acute_swelling", True),
        scopes=("arthroplasty_review",)), "onset"),
    ("unreviewed_cartilage_image", request(
        answer("imaging_cartilage_lesion", True, state="unverified", provenance="unreviewed_imaging"),
        scopes=("cartilage_review", "ocd_review")), "prior_treatment"),
    ("prior_treatment_with_unclear_response", request(
        answer("prior_treatment", True), answer("treatment_response", "unclear"),
        scopes=("prp_evidence_review", "meniscus_review")), "treatment_response"),
    ("outside_knee_scope", request(
        answer("chief_complaint", "pain"), scopes=SCOPES, region="other"), None),
])
def test_eight_synthetic_cases_preserve_existing_selector_and_input(scenario, req, expected_field):
    base = load_knee_pack()
    book = load_knee_book_review_pack()
    before = (req.model_dump(mode="json"), base.model_dump(mode="json"), book.model_dump(mode="json"))
    expected_baseline = select_questions(req.context, base)
    result = build_book_question_preview(req, base_pack=base, book_pack=book)
    assert result.baseline == expected_baseline
    assert before == (req.model_dump(mode="json"), base.model_dump(mode="json"), book.model_dump(mode="json"))
    fields = {candidate.field for candidate in result.baseline.question_candidates}
    if expected_field is None:
        assert not fields
        assert not result.question_annotations
        assert not result.clinician_review_requirements
        assert not result.source_references
    else:
        assert expected_field in fields
    assert result.review_only and result.requires_independent_review and result.safety_engine_required
    assert not result.registry_write_performed and not result.is_clinically_validated
    assert not result.is_diagnosis and not result.is_recommendation
    assert not result.is_clinical_clearance and not result.authorizes_treatment
    assert all(ref.population_applicability == "not_assessed" for ref in result.source_references)
    assert all(card.assessment_state == "not_represented_in_context_v1"
               for card in result.clinician_review_requirements)


def test_no_implicit_clinical_scope_or_book_question_binding():
    result = build_book_question_preview(request())
    assert result.baseline.question_candidates
    assert result.question_annotations == ()
    assert result.clinician_review_requirements == ()
    assert result.source_references == ()


def test_book_annotations_only_attach_to_real_returned_candidates_and_preserve_rules():
    result = build_book_question_preview(request(scopes=("arthroplasty_review",)))
    candidates = {candidate.question.id: candidate for candidate in result.baseline.question_candidates}
    annotations = {item.field: item for item in result.question_annotations}
    assert set(annotations) == {"pain_score", "functional_limitation", "relevant_comorbidity"}
    assert annotations["pain_score"].candidate_keys == ("BOOK.KNEE.001",)
    assert annotations["functional_limitation"].candidate_keys == ("BOOK.KNEE.001",)
    assert annotations["relevant_comorbidity"].candidate_keys == ("BOOK.KNEE.002",)
    for annotation in result.question_annotations:
        original = candidates[annotation.question_id]
        assert annotation.field == original.field
        assert annotation.action == original.action
        assert annotation.rule_id == original.rule_id
        assert annotation.rule_version == original.rule_version
        assert annotation.population_applicability == "not_assessed"


@pytest.mark.parametrize("state", ["confirmed", "unknown", "declined"])
def test_answered_unknown_and_declined_fields_do_not_get_repeated_through_book_annotations(state):
    value = 0 if state == "confirmed" else None
    result = build_book_question_preview(request(answer("pain_score", value, state=state),
                                                  scopes=("arthroplasty_review",)))
    assert "pain_score" not in {item.field for item in result.question_annotations}
    assert "pain_score" not in {item.field for item in result.baseline.question_candidates}


def test_conflicting_history_keeps_physician_clarification_action():
    result = build_book_question_preview(request(
        answer("pain_score", 2, source="synthetic:a"),
        answer("pain_score", 8, source="synthetic:b"), scopes=("arthroplasty_review",)))
    annotation = next(item for item in result.question_annotations if item.field == "pain_score")
    assert annotation.action == "physician_clarification"
    assert not result.baseline.structured_symptoms
    assert len(result.baseline.unverified_findings) == 2


@pytest.mark.parametrize("observation", [
    answer("prior_treatment", False),
    answer("prior_treatment", True, state="unverified"),
    answer("prior_treatment", state="unknown"),
    answer("prior_treatment", state="declined"),
    answer("prior_treatment", state="incomplete"),
])
def test_outcome_card_requires_effective_confirmed_treatment_history(observation):
    result = build_book_question_preview(request(observation, scopes=("prp_evidence_review",)))
    assert "BOOK.KNEE.008" not in referenced_card_keys(result)


def test_raw_true_in_contradictory_history_cannot_trigger_post_treatment_card():
    result = build_book_question_preview(request(
        answer("prior_treatment", True, source="synthetic:a"),
        answer("prior_treatment", False, source="synthetic:b"),
        scopes=("prp_evidence_review",)))
    assert "BOOK.KNEE.008" not in referenced_card_keys(result)
    assert len(result.baseline.unverified_findings) == 2


def test_generic_treatment_response_does_not_establish_prp_use_or_structural_outcome():
    result = build_book_question_preview(request(
        answer("prior_treatment", True), answer("treatment_response", "improved"),
        scopes=("prp_evidence_review",)))
    assert "BOOK.KNEE.008" in referenced_card_keys(result)
    card = next(card for card in result.clinician_review_requirements
                if "BOOK.KNEE.008" in card.candidate_keys)
    assert card.assessment_state == "not_represented_in_context_v1"
    assert card.population_applicability == "not_assessed"
    assert result.baseline.reviewed_imaging_findings == ()
    assert not any(annotation.field == "treatment_response" for annotation in result.question_annotations)


def test_reviewed_imaging_boolean_and_pain_location_cannot_supply_structural_location_or_maturity():
    result = build_book_question_preview(request(
        answer("pain_location", "medial"), answer("imaging_cartilage_lesion", True),
        scopes=("cartilage_review", "ocd_review")))
    assert {"BOOK.KNEE.004", "BOOK.KNEE.005"} <= referenced_card_keys(result)
    assert not any(annotation.field == "pain_location" for annotation in result.question_annotations)
    assert all(card.assessment_state == "not_represented_in_context_v1"
               for card in result.clinician_review_requirements)


def test_meniscal_prp_and_focal_arthroplasty_cards_require_both_relevant_scopes():
    assert "BOOK.KNEE.007" not in referenced_card_keys(build_book_question_preview(
        request(scopes=("meniscus_review",))))
    assert "BOOK.KNEE.007" not in referenced_card_keys(build_book_question_preview(
        request(scopes=("prp_evidence_review",))))
    combined = build_book_question_preview(request(scopes=SCOPES))
    assert {"BOOK.KNEE.007", "BOOK.KNEE.009"} <= referenced_card_keys(combined)
    for scope in ("arthroplasty_review", "cartilage_review"):
        assert "BOOK.KNEE.009" not in referenced_card_keys(build_book_question_preview(request(scopes=(scope,))))


def test_every_used_reference_is_exactly_source_bound_and_support_entry_is_not_new_fact():
    pack = load_knee_book_review_pack()
    by_id = {entry.candidate_key: entry for entry in pack.entries}
    result = build_book_question_preview(request(answer("prior_treatment", True), scopes=SCOPES), book_pack=pack)
    used = {key for item in (*result.question_annotations, *result.clinician_review_requirements)
            for key in item.candidate_keys}
    assert used == {ref.candidate_key for ref in result.source_references}
    for ref in result.source_references:
        entry = by_id[ref.candidate_key]
        assert ref.entry_sha256 == content_digest(entry.model_dump(mode="json"))
        assert ref.provenance == entry.provenance
        assert ref.source == entry.source
        assert ref.provenance.source_entailment_review == "pending"
        if entry.action == "support_existing":
            assert ref.content_sha256 is None
            assert ref.support_scope == "location_component_only"
            target = next(item for item in entry.related_facts if item.fact_key == entry.registry_fact_key)
            assert ref.target_base_fact_content_sha256 == target.content_sha256
        else:
            assert ref.content_sha256 == entry.draft_preview.content_sha256


def test_risk_review_is_preserved_without_diagnosis_or_safety_clearance():
    result = build_book_question_preview(request(answer("fever", True), answer("acute_swelling", True), scopes=SCOPES))
    assert "draft_hot_joint_information_requires_prompt_physician_review" in result.baseline.review_reasons
    assert result.safety_engine_required and not result.is_clinical_clearance
    assert not result.authorizes_treatment


@pytest.mark.parametrize("region", ["other", "unknown"])
def test_non_knee_context_never_acquires_book_sources_or_cards(region):
    result = build_book_question_preview(request(scopes=SCOPES, region=region))
    assert not result.question_annotations and not result.clinician_review_requirements
    assert not result.source_references


def test_results_are_deterministic_and_context_scopes_and_sources_are_hash_bound():
    req = request(answer("prior_treatment", True), scopes=SCOPES)
    result = build_book_question_preview(req)
    assert result == build_book_question_preview(req)
    assert result.result_sha256 == content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))
    reordered = request(answer("prior_treatment", True), scopes=tuple(reversed(SCOPES)))
    assert build_book_question_preview(reordered) == result
    changed_scope = build_book_question_preview(request(answer("prior_treatment", True), scopes=("meniscus_review",)))
    assert result.request_sha256 != changed_scope.request_sha256
    assert result.result_sha256 != changed_scope.result_sha256
    changed_answer = build_book_question_preview(request(answer("prior_treatment", False), scopes=SCOPES))
    assert result.request_sha256 != changed_answer.request_sha256


def test_rules_hash_tracks_bridge_artifact_without_changing_existing_selection(monkeypatch):
    req = request(scopes=("arthroplasty_review",))
    before = build_book_question_preview(req)
    original_read = Path.read_bytes
    bridge_path = Path(bridge_service.__file__)

    def changed_bridge_bytes(path):
        return b"Synthetic changed bridge policy artifact" if path == bridge_path else original_read(path)

    monkeypatch.setattr(Path, "read_bytes", changed_bridge_bytes)
    after = build_book_question_preview(req)
    assert before.baseline == after.baseline
    assert before.request_sha256 == after.request_sha256
    assert before.rules_sha256 != after.rules_sha256
    assert before.result_sha256 != after.result_sha256


def test_mutated_base_or_supplement_is_rejected_before_preview():
    base = load_knee_pack()
    base.facts[0].fact.title = "Synthetic change without a source-bound content hash"
    with pytest.raises(MedicalKnowledgeIntegrityError):
        build_book_question_preview(request(scopes=SCOPES), base_pack=base)
    book = load_knee_book_review_pack()
    next(entry for entry in book.entries if entry.draft_preview).draft_preview.proposal.title = (
        "Synthetic changed unvalidated book proposal"
    )
    with pytest.raises(MedicalKnowledgeIntegrityError):
        build_book_question_preview(request(scopes=SCOPES), book_pack=book)


def test_preview_does_not_write_registry_or_change_base_file(db_session, monkeypatch):
    before = PACK_PATH.read_bytes()
    rows = list(db_session.scalars(select(MedicalKnowledgeFact)))

    def forbidden_write(*args, **kwargs):
        raise AssertionError("Book question preview must never create Registry knowledge.")

    monkeypatch.setattr(MedicalKnowledgeService, "create", forbidden_write)
    build_book_question_preview(request(answer("prior_treatment", True), scopes=SCOPES))
    assert PACK_PATH.read_bytes() == before
    assert list(db_session.scalars(select(MedicalKnowledgeFact))) == rows


@pytest.mark.parametrize("extra", ["patient_id", "name", "date_of_birth", "narrative", "sex"])
def test_minimum_necessary_request_rejects_identifiers(extra):
    with pytest.raises(ValidationError):
        BookQuestionPreviewRequest.model_validate({"context": {"body_region": "knee"}, extra: "not accepted"})


def test_scope_is_explicit_unique_and_not_a_diagnosis_input():
    with pytest.raises(ValidationError):
        request(scopes=("meniscus_review", "meniscus_review"))
    with pytest.raises(ValidationError):
        request(scopes=("confirmed_meniscal_tear",))


@pytest.mark.parametrize("flag", ["registry_write_performed", "is_clinically_validated", "is_diagnosis",
                                 "is_recommendation", "is_clinical_clearance", "authorizes_treatment"])
def test_false_governance_flags_cannot_be_coerced_from_integer_zero(flag):
    payload = build_book_question_preview(request()).model_dump(mode="json")
    payload[flag] = 0
    with pytest.raises(ValidationError):
        BookQuestionPreview.model_validate(payload)


def test_checked_in_eight_case_demo_checks_all_expected_source_bindings():
    from backend.tools.orthopedic_book_questions_demo import run_synthetic_cases

    result = run_synthetic_cases()
    assert result["case_count"] == result["passed_cases"] == 8
    assert result["synthetic_only"] is True and result["approved_fact_count"] == 0
    assert result["registry_write_performed"] is False and result["is_clinically_validated"] is False


def test_preview_explicitly_reports_unevaluated_safety_and_no_approved_facts():
    result = build_book_question_preview(BookQuestionPreviewRequest(context={"body_region": "knee"}))
    assert result.safety_evaluation == "not_performed" and result.approved_fact_count == 0

