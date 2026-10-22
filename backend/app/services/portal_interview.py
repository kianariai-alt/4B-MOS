"""Bounded question branching from an explicitly approved physician bank.

No generated clinical advice, probability or diagnostic inference is performed.
Answers are patient statements and never finalize a clinician intake.
"""
import json
import math
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from backend.app.core.config import settings
from backend.app.models.patient_portal import PortalInterview, PortalRequest
from backend.app.models.user import User
from backend.app.schemas.physician_questions import BankContent, PredicateCondition, AllCondition
from backend.app.schemas.interview_summary import InterviewAssistantSummary
from backend.app.services import patient_portal as portal
from backend.app.services.physician_questions import _rows, _active, _read, QuestionBankConflictError


def approved_bank(db, physician_id):
    physician = db.get(User, physician_id)
    if physician is None or not physician.is_active or physician.role != "physician":
        return None
    try:
        active = _active(_rows(db, physician_id))
        return _read(active) if active else None
    except QuestionBankConflictError as error:
        raise HTTPException(409, "گنجینهٔ پرسش‌ها نیازمند بررسی پزشک است.") from error


def create(db, row, data):
    physician_id = settings.PATIENT_PORTAL_QUESTION_BANKS.get(data.get("body_region"))
    bank = approved_bank(db, physician_id) if physician_id else None
    if bank is None:
        return
    snapshot = bank.content.model_dump(mode="json")
    interview = PortalInterview(request_id=row.id, physician_id=physician_id, bank_sha256=bank.sha256,
        encrypted_snapshot=portal.encrypt(portal.encode(snapshot), "interview-bank:" + row.id),
        encrypted_answers=portal.encrypt(portal.encode({"schema_version": 2, "active_answers": {}, "answer_history": [], "invalidations": []}), "interview-answers:" + row.id), version=0)
    db.add(interview)
    portal.audit(db, row, "approved_interview_attached")


def _state(interview):
    snapshot = json.loads(portal.decrypt(interview.encrypted_snapshot, "interview-bank:" + interview.request_id))
    stored = json.loads(portal.decrypt(interview.encrypted_answers, "interview-answers:" + interview.request_id))
    bank = BankContent.model_validate(snapshot)
    if stored.get("schema_version") == 2:
        return bank, stored
    # Old encrypted question-id dictionaries have no event timestamps. Preserve
    # their original commands and explicitly label missing historical metadata.
    state = {"schema_version": 2, "active_answers": {}, "answer_history": [], "invalidations": []}
    for question in bank.questions:
        if question.id not in stored:
            continue
        command = stored[question.id]
        event = {**command, "answer_event_id": "legacy:" + question.id + ":" + command["request_key"],
            "command": command, "recorded_at": None, "source": "legacy_patient_portal",
            "bank_sha256": interview.bank_sha256, "question_version": question.question_version,
            "provenance": question.provenance.model_dump(mode="json"), "metadata_status": "legacy_timestamp_unavailable"}
        state["active_answers"][question.id] = event
        state["answer_history"].append(event)
    return bank, state


def _condition_result(condition, answers, eligible_ids):
    """Three-valued logic: missing/unknown/declined never imply a negative."""
    if isinstance(condition, PredicateCondition):
        if condition.question_id not in eligible_ids:
            return None
        answer = answers.get(condition.question_id)
        answer_state = answer["state"] if answer else "missing"
        if condition.operator == "state_in":
            return answer_state in condition.states
        if answer_state != "answered":
            return None
        value = answer["value"]
        if condition.operator == "in":
            return value in condition.values
        operand = condition.value
        if condition.operator == "eq":
            return value == operand
        if condition.operator == "ne":
            return value != operand
        # The bank validator checks types; fail closed for malformed old state.
        if type(value) not in (int, float) or type(operand) not in (int, float):
            return None
        if (type(value) is float and not math.isfinite(value)) or (type(operand) is float and not math.isfinite(operand)):
            return None
        return {"gt": value > operand, "gte": value >= operand,
            "lt": value < operand, "lte": value <= operand}[condition.operator]
    children = condition.all if isinstance(condition, AllCondition) else condition.any
    values = [_condition_result(child, answers, eligible_ids) for child in children]
    if isinstance(condition, AllCondition):
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def _eligible(bank, answers):
    eligible_ids = set()
    for question in bank.questions:
        if question.depends_on_id:
            parent = answers.get(question.depends_on_id)
            if question.depends_on_id not in eligible_ids or not parent or parent["state"] != "answered" or parent["value"] not in question.show_when_answer_in:
                continue
        if question.display_condition is not None and _condition_result(question.display_condition, answers, eligible_ids) is not True:
            continue
        eligible_ids.add(question.id)
    return eligible_ids


def _next(bank, answers):
    eligible_ids = _eligible(bank, answers)
    for question in bank.questions:
        if question.id in eligible_ids and question.id not in answers:
            return question
    return None


def _question_view(question):
    # Serialization of archived banks omits new defaults to preserve their hash;
    # the public question contract always exposes honest version/source labels.
    return {**question.model_dump(mode="json"), "question_version": question.question_version,
        "provenance": question.provenance.model_dump(mode="json"),
        "display_condition": question.display_condition.model_dump(mode="json") if question.display_condition else None,
        "numeric_unit": question.numeric_unit, "numeric_min": question.numeric_min, "numeric_max": question.numeric_max}


def _answer_view(question, event):
    return {"question_id": question.id, "question": question.text_fa,
        "question_definition": _question_view(question),
        **{key: event.get(key) for key in ("state", "value", "unit", "supplementary_text", "recorded_at", "source", "bank_sha256", "question_version", "provenance", "answer_event_id")}}


def _history_view(state):
    active_ids = {event["answer_event_id"] for event in state["active_answers"].values()}
    invalidations = {item["answer_event_id"]: item for item in state["invalidations"]}
    return [{**event, "active": event["answer_event_id"] in active_ids,
        "invalidation": invalidations.get(event["answer_event_id"])} for event in state["answer_history"]]


def _assistant_summary(bank, state, interview, row):
    answers = state["active_answers"]
    eligible_ids = _eligible(bank, answers)
    items = [_answer_view(question, answers[question.id]) for question in bank.questions if question.id in answers and question.id in eligible_ids]
    lines = []
    for item in items:
        if item["state"] == "unknown":
            value = "نمی‌دانم"
        elif item["state"] == "declined":
            value = "خودداری از پاسخ"
        else:
            value = {"yes": "بله", "no": "خیر"}.get(item["value"], item["value"])
            value = str(value) + (" " + item["unit"] if item["unit"] else "")
        lines.append(item["question"] + ": " + value + ("؛ " + item["supplementary_text"] if item["supplementary_text"] else ""))
    summary = {"schema_version": "1.0.0", "source": "patient_portal", "patient_reported_only": True,
        "requires_clinician_review": True, "bank_sha256": interview.bank_sha256, "physician_id": interview.physician_id,
        "request_id": row.id, "interview_version": interview.version, "items": items,
        "missing_question_ids": [question.id for question in bank.questions if question.id in eligible_ids and question.id not in answers],
        "unknown_question_ids": [item["question_id"] for item in items if item["state"] == "unknown"],
        "declined_question_ids": [item["question_id"] for item in items if item["state"] == "declined"],
        "inactive_question_ids": [question.id for question in bank.questions if question.id not in eligible_ids],
        "summary_fa": "اطلاعات گزارش‌شده توسط بیمار؛ نیازمند بررسی پزشک.\n" + "\n".join(lines)}
    return InterviewAssistantSummary.model_validate(summary).model_dump(mode="json")


def view(db, row):
    interview = db.get(PortalInterview, row.id)
    if interview is None:
        return {"available": False, "reason": "گنجینهٔ تأییدشده برای این درخواست تعیین نشده؛ پزشک می‌تواند سؤال تکمیلی بفرستد."}
    bank, state = _state(interview)
    answers = state["active_answers"]
    active = approved_bank(db, interview.physician_id)
    enabled = row.state != "withdrawn" and active is not None and active.sha256 == interview.bank_sha256
    question = _next(bank, answers) if enabled else None
    return {"available": True, "accepting_answers": enabled, "version": interview.version,
        "title": bank.title_fa, "bank_sha256": interview.bank_sha256, "physician_id": interview.physician_id,
        "contract_version": bank.contract_version,
        "next_question": _question_view(question) if question else None,
        "complete": _next(bank, answers) is None,
        "answers": [_answer_view(q, answers[q.id]) for q in bank.questions if q.id in answers],
        "answer_history": _history_view(state),
        "assistant_summary": _assistant_summary(bank, state, interview, row)}


def _same_command(previous, current):
    # Optional fields added in v2 must not break a retry of a legacy command.
    return {**{"unit": None, "supplementary_text": None}, **previous} == {**{"unit": None, "supplementary_text": None}, **current}


def _validate_answer(question, payload):
    if payload.state != "answered":
        if payload.value is not None or payload.unit is not None:
            raise HTTPException(422, "برای پاسخ نامشخص یا انصراف، مقدار یا واحد ارسال نکنید.")
        return
    if question.answer_type == "number":
        if type(payload.value) not in (int, float) or (type(payload.value) is float and not math.isfinite(payload.value)):
            raise HTTPException(422, "پاسخ عددی باید یک عدد معتبر باشد.")
        if payload.unit != question.numeric_unit or not question.numeric_min <= payload.value <= question.numeric_max:
            raise HTTPException(422, "واحد یا محدودهٔ پاسخ عددی با پرسش سازگار نیست.")
    else:
        choices = ["yes", "no"] if question.answer_type == "yes_no" else question.choices if question.answer_type == "single_choice" else None
        if not isinstance(payload.value, str) or not payload.value.strip() or (choices is not None and payload.value not in choices) or payload.unit is not None:
            raise HTTPException(422, "پاسخ با نوع پرسش سازگار نیست.")


def answer(db, row, payload):
    def command():
        portal.lock(db, PortalRequest, row.id)
        interview = db.get(PortalInterview, row.id)
        if interview is None:
            raise HTTPException(404, "پرسش‌نامه‌ای برای این درخواست وجود ندارد.")
        bank, state = _state(interview)
        answers = state["active_answers"]
        active = approved_bank(db, interview.physician_id)
        if row.state == "withdrawn" or active is None or active.sha256 != interview.bank_sha256:
            raise HTTPException(409, "پرسش‌نامه بسته شده یا نسخهٔ آن تغییر کرده است؛ از پزشک پیگیری کنید.")
        data = payload.model_dump(mode="json")
        for previous in state["answer_history"]:
            if previous["command"]["request_key"] == payload.request_key:
                if not _same_command(previous["command"], data):
                    raise HTTPException(409, "شناسهٔ پاسخ برای محتوای دیگری استفاده شده است.")
                return view(db, row)
        if interview.version != payload.expected_version:
            raise HTTPException(409, "پاسخ‌ها تغییر کرده‌اند؛ پرسش‌نامه را دوباره بارگذاری کنید.")
        question = _next(bank, answers)
        if payload.question_id in answers:
            question = next(q for q in bank.questions if q.id == payload.question_id)
        elif question is None or question.id != payload.question_id:
            raise HTTPException(409, "فقط پرسش جاری یا پاسخ فعال قبلی را ویرایش کنید.")
        _validate_answer(question, payload)
        now = datetime.now(timezone.utc).isoformat()
        new_version = interview.version + 1
        if question.id in answers:
            state["invalidations"].append({"answer_event_id": answers[question.id]["answer_event_id"],
                "reason": "answer_replaced", "at_version": new_version, "recorded_at": now})
        event = {**data, "command": data, "answer_event_id": str(uuid4()), "recorded_at": now,
            "source": "patient_portal", "bank_sha256": interview.bank_sha256,
            "question_version": question.question_version, "provenance": question.provenance.model_dump(mode="json")}
        answers[question.id] = event
        state["answer_history"].append(event)
        eligible_ids = _eligible(bank, answers)
        for question_id in list(answers):
            if question_id not in eligible_ids:
                removed = answers.pop(question_id)
                state["invalidations"].append({"answer_event_id": removed["answer_event_id"],
                    "reason": "condition_no_longer_satisfied", "at_version": new_version, "recorded_at": now})
        interview.encrypted_answers = portal.encrypt(portal.encode(state), "interview-answers:" + row.id)
        interview.version += 1
        db.flush()
        portal.audit(db, row, "patient_interview_answer")
        return view(db, row)
    return portal.run_write(db, command)
