"""Synthetic contract/branching tests; these are not clinical rules."""
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas.interview_summary import InterviewAssistantSummary
from backend.app.schemas.physician_questions import (
    BankContent, DisplayCondition, DraftCreate, FiniteNumber, InterviewQuestion,
)
from backend.app.services.portal_interview import _condition_result, _eligible, _next


def question(identifier, **changes):
    return dict(id=identifier, text_fa="پرسش ساختگی " + identifier,
                purpose_fa="آزمون نرم‌افزار", **changes)


def bank(*questions, **changes):
    return BankContent.model_validate(dict(title_fa="گنجینه ساختگی",
        scope_fa="فقط آزمون نرم‌افزار", questions=list(questions), **changes))


def condition(value):
    return TypeAdapter(DisplayCondition).validate_python(value)


@pytest.mark.parametrize("state", ["unknown", "declined", "missing"])
@pytest.mark.parametrize("operator,operand", [("eq", "yes"), ("eq", "no"), ("ne", "yes"), ("in", ["no"])])
def test_nonanswer_is_unresolved_for_every_value_predicate(state, operator, operand):
    predicate = condition(dict(question_id="root", operator=operator,
        **({"values": operand} if operator == "in" else {"value": operand})))
    answers = {} if state == "missing" else {"root": {"state": state, "value": None}}
    assert _condition_result(predicate, answers, {"root"}) is None
    explicit = condition(dict(question_id="root", operator="state_in", states=[state]))
    assert _condition_result(explicit, answers, {"root"}) is True
    # A hidden predecessor is not a missing response eligible for routing.
    assert _condition_result(explicit, answers, set()) is None


@pytest.mark.parametrize("group,values,expected", [
    ("all", [True, True], True), ("all", [True, None], None),
    ("all", [False, None], False), ("all", [None, None], None),
    ("any", [True, None], True), ("any", [False, None], None),
    ("any", [False, False], False), ("any", [None, None], None),
])
def test_compound_three_valued_logic(group, values, expected):
    expression = condition({group: [dict(question_id=str(index), operator="eq", value="yes") for index in range(len(values))]})
    answers = {str(index): dict(state="unknown" if value is None else "answered", value=None if value is None else "yes" if value else "no") for index, value in enumerate(values)}
    assert _condition_result(expression, answers, set(answers)) is expected


def test_unknown_numeric_and_zero_differ_and_routes_can_coexist():
    content = bank(
        question("root", answer_type="number", numeric_unit="test_point", numeric_min=0, numeric_max=10),
        question("zero", display_condition=dict(question_id="root", operator="eq", value=0)),
        question("low", display_condition=dict(question_id="root", operator="lte", value=5)),
        question("unknown_route", display_condition=dict(question_id="root", operator="state_in", states=["unknown"])),
        question("declined_route", display_condition=dict(question_id="root", operator="state_in", states=["declined"])),
    )
    assert _next(content, {}).id == "root"
    assert _eligible(content, {"root": {"state": "answered", "value": 0}}) == {"root", "zero", "low"}
    assert _eligible(content, {"root": {"state": "unknown", "value": None}}) == {"root", "unknown_route"}
    assert _eligible(content, {"root": {"state": "declined", "value": None}}) == {"root", "declined_route"}


def test_hidden_ancestor_does_not_activate_its_missing_or_unknown_followups():
    content = bank(
        question("root", answer_type="yes_no"),
        question("child", depends_on_id="root", show_when_answer_in=["yes"]),
        question("missing_route", display_condition=dict(question_id="child", operator="state_in", states=["missing"])),
        question("unknown_route", display_condition=dict(question_id="child", operator="state_in", states=["unknown"])),
        question("grandchild", depends_on_id="child", show_when_answer_in=["test"]),
    )
    # The stale answers deliberately simulate state before a correction prunes
    # it. Neither their values nor their absence may activate descendants.
    for answers in (
        {"root": dict(state="answered", value="no")},
        {"root": dict(state="answered", value="no"), "child": dict(state="unknown", value=None)},
        {"root": dict(state="answered", value="no"), "child": dict(state="answered", value="test")},
    ):
        assert _eligible(content, answers) == {"root"}


@pytest.mark.parametrize("changes", [
    {"numeric_min": None}, {"numeric_max": None}, {"numeric_unit": None},
    {"numeric_min": 11}, {"numeric_max": float("nan")},
    {"numeric_min": float("-inf")}, {"numeric_max": float("inf")},
    {"numeric_min": True}, {"numeric_max": "10"},
])
def test_numeric_schema_requires_finite_typed_bounds_and_unit(changes):
    data = question("score", answer_type="number", numeric_unit="test_point", numeric_min=0, numeric_max=10)
    with pytest.raises(ValidationError):
        InterviewQuestion.model_validate({**data, **changes})


def test_arbitrary_size_integer_is_finite_without_float_conversion_overflow():
    assert TypeAdapter(FiniteNumber).validate_python(10**1000) == 10**1000


@pytest.mark.parametrize("predicate", [
    {"question_id": "later", "operator": "eq", "value": "yes"},
    {"question_id": "root", "operator": "gt", "value": "yes"},
    {"question_id": "root", "operator": "eq", "value": "invalid"},
    {"question_id": "root", "operator": "eq", "value": False},
    {"question_id": "root", "operator": "state_in", "states": []},
    {"question_id": "root", "operator": "state_in", "states": ["unknown", "unknown"]},
    {"question_id": "root", "operator": "state_in", "states": ["unknown"], "value": "yes"},
    {"question_id": "root", "operator": "in", "values": []},
    {"all": []}, {"any": []},
])
def test_invalid_conditions_fail_authoring_validation(predicate):
    with pytest.raises(ValidationError):
        bank(question("root", answer_type="yes_no"), question("child", display_condition=predicate))


def test_numeric_predicates_require_numbers_and_legacy_condition_stays_typed():
    numeric = question("score", answer_type="number", numeric_unit="test_point", numeric_min=0, numeric_max=10)
    with pytest.raises(ValidationError):
        bank(numeric, question("child", display_condition=dict(question_id="score", operator="eq", value="0")))
    with pytest.raises(ValidationError):
        bank(numeric, question("child", depends_on_id="score", show_when_answer_in=["0"]))
    with pytest.raises(ValidationError):
        bank(question("root", answer_type="yes_no"), question("child", depends_on_id="root", show_when_answer_in=["yes"],
            display_condition=dict(question_id="root", operator="eq", value="yes")))


def test_nested_condition_limits():
    predicate = dict(question_id="root", operator="eq", value="yes")
    for _ in range(9):
        predicate = {"all": [predicate]}
    with pytest.raises(ValidationError, match="nest at most"):
        bank(question("root", answer_type="yes_no"), question("child", display_condition=predicate))


def test_legacy_serialization_has_exact_original_shape_for_hashes_and_retries():
    original_question = dict(id="first", text_fa="سؤال ساختگی؟", purpose_fa="شرح حال ساختگی", answer_type="text", choices=[],
        depends_on_id=None, show_when_answer_in=[], allow_unknown=True, allow_decline=True)
    original_content = dict(title_fa="گنجینه ساختگی", scope_fa="مصاحبه ساختگی", summary_preferences_fa=None, questions=[original_question])
    parsed = BankContent.model_validate(original_content)
    assert parsed.questions[0].question_version == "legacy-unspecified"
    assert parsed.questions[0].provenance.kind == "unspecified"
    assert parsed.model_dump(mode="json") == original_content
    command = dict(**original_content, expected_version=0, request_key="legacy-draft")
    assert DraftCreate.model_validate(command).model_dump(mode="json") == command
    assert json.loads(parsed.model_dump_json()) == original_content


def test_explicit_versioned_contract_requires_per_question_version_and_source():
    with pytest.raises(ValidationError, match="versions and provenance"):
        bank(question("root"), contract_version="1.0.0")
    content = bank(question("root", question_version="synthetic-v1", provenance=dict(kind="design_draft", reference="synthetic software test")), contract_version="1.0.0")
    serialized = content.model_dump(mode="json")
    assert serialized["contract_version"] == "1.0.0"
    assert serialized["questions"][0]["question_version"] == "synthetic-v1"
    assert serialized["questions"][0]["provenance"]["kind"] == "design_draft"
    assert BankContent.model_validate(serialized) == content


def test_assistant_summary_contract_forbids_clinical_claims():
    base = dict(bank_sha256="a"*64, physician_id="synthetic-physician", request_id="synthetic-request", interview_version=0,
        items=[], missing_question_ids=[], unknown_question_ids=[], declined_question_ids=[], inactive_question_ids=[], summary_fa="هنوز پاسخی ثبت نشده است.")
    summary = InterviewAssistantSummary.model_validate(base)
    assert summary.patient_reported_only is True and summary.requires_clinician_review is True
    for changes in ({"diagnosis": "invented"}, {"probability": 0.9}, {"treatment": "invented"}, {"patient_reported_only": False}, {"requires_clinician_review": False}):
        with pytest.raises(ValidationError):
            InterviewAssistantSummary.model_validate({**base, **changes})
