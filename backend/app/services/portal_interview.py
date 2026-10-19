"""Bounded question branching from an explicitly approved physician bank.

No generated clinical advice, probability or diagnostic inference is performed.
Answers are patient statements and never finalize a clinician intake.
"""
import json
from fastapi import HTTPException
from backend.app.core.config import settings
from backend.app.models.patient_portal import PortalInterview, PortalRequest
from backend.app.models.user import User
from backend.app.schemas.physician_questions import BankContent
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
        encrypted_answers=portal.encrypt(portal.encode({}), "interview-answers:" + row.id), version=0)
    db.add(interview)
    portal.audit(db, row, "approved_interview_attached")


def _state(interview):
    snapshot = json.loads(portal.decrypt(interview.encrypted_snapshot, "interview-bank:" + interview.request_id))
    answers = json.loads(portal.decrypt(interview.encrypted_answers, "interview-answers:" + interview.request_id))
    return BankContent.model_validate(snapshot), answers


def _next(bank, answers):
    for question in bank.questions:
        if question.depends_on_id:
            parent = answers.get(question.depends_on_id)
            if not parent or parent["state"] != "answered" or parent["value"] not in question.show_when_answer_in:
                continue
        if question.id not in answers:
            return question
    return None


def view(db, row):
    interview = db.get(PortalInterview, row.id)
    if interview is None:
        return {"available": False, "reason": "گنجینهٔ تأییدشده برای این درخواست تعیین نشده؛ پزشک می‌تواند سؤال تکمیلی بفرستد."}
    bank, answers = _state(interview)
    active = approved_bank(db, interview.physician_id)
    enabled = row.state != "withdrawn" and active is not None and active.sha256 == interview.bank_sha256
    question = _next(bank, answers) if enabled else None
    return {"available": True, "accepting_answers": enabled, "version": interview.version,
        "title": bank.title_fa, "bank_sha256": interview.bank_sha256, "physician_id": interview.physician_id,
        "next_question": question.model_dump(mode="json") if question else None,
        "complete": _next(bank, answers) is None,
        "answers": [{"question_id": q.id, "question": q.text_fa, "state": answers[q.id]["state"],
            "value": answers[q.id]["value"]} for q in bank.questions if q.id in answers]}


def answer(db, row, payload):
    def command():
        portal.lock(db, PortalRequest, row.id)
        interview = db.get(PortalInterview, row.id)
        if interview is None:
            raise HTTPException(404, "پرسش‌نامه‌ای برای این درخواست وجود ندارد.")
        bank, answers = _state(interview)
        active = approved_bank(db, interview.physician_id)
        if row.state == "withdrawn" or active is None or active.sha256 != interview.bank_sha256:
            raise HTTPException(409, "پرسش‌نامه بسته شده یا نسخهٔ آن تغییر کرده است؛ از پزشک پیگیری کنید.")
        data = payload.model_dump(mode="json")
        for previous in answers.values():
            if previous["request_key"] == payload.request_key:
                if previous != data:
                    raise HTTPException(409, "شناسهٔ پاسخ برای محتوای دیگری استفاده شده است.")
                return view(db, row)
        if interview.version != payload.expected_version:
            raise HTTPException(409, "پاسخ‌ها تغییر کرده‌اند؛ پرسش‌نامه را دوباره بارگذاری کنید.")
        question = _next(bank, answers)
        if question is None or question.id != payload.question_id:
            raise HTTPException(409, "فقط پرسش جاری را پاسخ دهید.")
        if payload.state == "answered":
            choices = ["yes", "no"] if question.answer_type == "yes_no" else question.choices if question.answer_type == "single_choice" else None
            if payload.value is None or (choices is not None and payload.value not in choices):
                raise HTTPException(422, "پاسخ با نوع پرسش سازگار نیست.")
        elif payload.value is not None:
            raise HTTPException(422, "برای پاسخ نامشخص یا انصراف، مقدار ارسال نکنید.")
        answers[question.id] = data
        interview.encrypted_answers = portal.encrypt(portal.encode(answers), "interview-answers:" + row.id)
        interview.version += 1
        db.flush()
        portal.audit(db, row, "patient_interview_answer")
        return view(db, row)
    return portal.run_write(db, command)
