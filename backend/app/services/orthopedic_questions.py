"""Explainable knee interview preview using the existing question-bank schema.

This adds orthopedic content selection, not a second question/answer store or a
general decision engine. It does not write a bank, patient record or safety rule.
Existing approved-bank approval and portal interview execution remain unchanged.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from backend.app.schemas import orthopedic_questions as question_schema

from backend.app.schemas.orthopedic_questions import (
    BOOLEAN_FIELDS,
    CHOICES,
    InformationGap,
    OrthopedicQuestionContext,
    OrthopedicQuestionResult,
    QuestionCandidate,
    StructuredAnswer,
)
from backend.app.schemas.physician_questions import BankContent, InterviewQuestion
from backend.app.services.orthopedic_knowledge import validate_knee_pack


RULE_VERSION = "1.0.0"
OA = "KNEE.OA.PRESENTATION"
MENISCUS = "KNEE.MENISCUS.SCOPE"
CARTILAGE = "KNEE.CARTILAGE.HISTORY_EXAM"
HOT_JOINT = "KNEE.SAFETY.HOT_JOINT"
SEPSIS = "KNEE.SAFETY.SEPSIS"
NEUROVASCULAR = "KNEE.SAFETY.NEUROVASCULAR_TRAUMA"

# These are Draft clinical-content rules. Order is workflow order, never a
# differential-diagnosis or treatment ranking. Only literal controlled answers
# activate a dependency; narrative text and similarity are never consulted.
QUESTION_CONTENT = (
    ("chief_complaint", "شکایت اصلی زانو چیست؟", OA, None),
    ("fever", "آیا همراه مشکل زانو تب داشته‌اید؟", HOT_JOINT, None),
    ("acute_swelling", "آیا زانو به‌تازگی به‌طور واضح متورم شده است؟", HOT_JOINT, None),
    ("systemic_symptoms", "آیا همراه درد زانو احساس بیماری عمومی دارید؟", SEPSIS, None),
    ("onset", "علائم زانو چگونه شروع شد؟", OA, None),
    ("duration", "علائم زانو چه مدتی ادامه داشته است؟", OA, None),
    ("pain_location", "درد بیشتر در کدام قسمت زانو است؟", CARTILAGE, None),
    ("pain_score", "شدت درد زانو از صفر تا ده چقدر است؟", OA, None),
    ("pain_pattern", "درد زانو بیشتر در چه زمانی رخ می‌دهد؟", OA, None),
    ("aggravating_factor", "کدام فعالیت بیشتر علائم زانو را تشدید می‌کند؟", CARTILAGE, None),
    ("relieving_factor", "چه چیزی علائم زانو را کاهش می‌دهد؟", OA, None),
    ("mechanical_locking", "آیا زانو واقعاً قفل می‌شود و باز یا خم کردن آن متوقف می‌شود؟", "KNEE.MENISCUS.MOTION_BLOCK", None),
    ("functional_limitation", "مشکل زانو تا چه حد فعالیت روزمره را محدود کرده است؟", OA, None),
    ("trauma", "آیا علائم زانو با یک آسیب مشخص شروع شد؟", MENISCUS, None),
    ("neurovascular_symptoms", "آیا پس از آسیب، تغییر حس یا ضعف تازه، سردی یا تغییر رنگ پا داشته‌اید؟", NEUROVASCULAR, ("trauma", "yes")),
    ("trauma_mechanism", "آسیب زانو چگونه رخ داد؟", MENISCUS, ("trauma", "yes")),
    ("prior_surgery", "آیا قبلاً روی این زانو جراحی انجام شده است؟", CARTILAGE, None),
    ("prior_treatment", "آیا برای این مشکل زانو قبلاً درمانی دریافت کرده‌اید؟", CARTILAGE, None),
    ("treatment_response", "پاسخ شما به درمان قبلی زانو چگونه بوده است؟", CARTILAGE, ("prior_treatment", "yes")),
    ("relevant_comorbidity", "آیا بیماری زمینه‌ای مرتبطی دارید که پزشک باید بررسی کند؟", OA, None),
    ("current_medication", "آیا دارویی مصرف می‌کنید که پزشک باید پیش از ارزیابی بررسی کند؟", OA, None),
    ("care_goal", "هدف اصلی شما از ارزیابی زانو چیست؟", OA, None),
)


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _question(field, text, condition=None):
    # Existing InterviewQuestion accepts yes/no and controlled single choices.
    # pain_score stays text in the physician-authored bank schema, while the
    # structured boundary requires a strict integer 0..10 before it is usable.
    answer_type = "yes_no" if field in BOOLEAN_FIELDS else "single_choice" if field in CHOICES else "text"
    return InterviewQuestion(
        id="knee." + field,
        text_fa=text,
        purpose_fa="رفع ابهام در شرح‌حال زانو برای بازبینی پزشک؛ محتوای پیش‌نویس نیازمند تأیید مستقل است.",
        answer_type=answer_type,
        choices=list(CHOICES.get(field, ())) if answer_type == "single_choice" else [],
        depends_on_id="knee." + condition[0] if condition else None,
        show_when_answer_in=[condition[1]] if condition else [],
    )


def draft_question_bank() -> BankContent:
    """Exportable content for the EXISTING physician bank draft workflow only."""
    return BankContent(
        title_fa="پیش‌نویس پرسش‌های ساختاریافته زانو",
        scope_fa="پیش‌نمایش پژوهشی برای بازبینی پزشک؛ پیش از استفاده نیازمند بررسی مستقل و تأیید در گنجینه موجود است.",
        questions=[_question(field, text, condition) for field, text, _, condition in QUESTION_CONTENT],
    )


def _effective_answers(context):
    """Retain every source observation, resolving nothing by last-write-wins."""
    grouped = defaultdict(list)
    for item in context.observations:
        grouped[item.field].append(item)
    effective = {}
    reasons = {}
    for field, items in grouped.items():
        confirmed = [item for item in items if item.state == "confirmed"]
        comparable = {json.dumps(item.value, sort_keys=True) for item in items if item.value is not None}
        states = {item.state for item in items}
        if "contradictory" in states or len(comparable) > 1:
            reasons[field] = "contradictory"
        elif "incomplete" in states or any(item.value == "unclear" for item in items):
            reasons[field] = "incomplete"
        elif confirmed:
            effective[field] = confirmed[0]
        elif "unverified" in states:
            reasons[field] = "unverified"
        elif "declined" in states:
            reasons[field] = "declined"
        else:
            reasons[field] = "unknown"
    return grouped, effective, reasons


def _condition_met(condition, effective):
    if condition is None:
        return True
    parent = effective.get(condition[0])
    return parent is not None and parent.value is (condition[1] == "yes")


def select_questions(context: OrthopedicQuestionContext, pack) -> OrthopedicQuestionResult:
    """Return Draft suggestions without altering supplied observations or stores.

    A blocked/uncertain answer remains visible as a gap. Unknown/declined items
    are never automatically asked again; contradictions/incomplete items get a
    physician clarification candidate rather than a repeated patient question.
    The existing Clinical Safety Rule Engine must still evaluate source records.
    """
    # Revalidate callers that bypassed ordinary schema construction.
    context = OrthopedicQuestionContext.model_validate(context.model_dump(mode="json"))
    pack = validate_knee_pack(pack)
    facts = {item.fact.fact_key: item for item in pack.facts}
    needed = {item[2] for item in QUESTION_CONTENT}
    if not needed <= facts.keys():
        raise ValueError("Question rules require all referenced knee knowledge facts.")
    bank = draft_question_bank()
    rules_sha256 = _digest({
        "schema_version": RULE_VERSION,
        "selector_artifact_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "context_schema_artifact_sha256": hashlib.sha256(Path(question_schema.__file__).read_bytes()).hexdigest(),
        "bank": bank.model_dump(mode="json"),
        "bindings": [{"field": field, "fact_key": key, "content_sha256": facts[key].content_sha256}
                     for field, _, key, _ in QUESTION_CONTENT],
        "selection_policy": "missing-only;typed-parent;preserve-unknown-declined;clarify-conflict;no-clearance-v1",
        "review_bindings": [
            {"fields": ["acute_swelling", "fever"], "predicate": "both_true_in_any_source", "fact_keys": [HOT_JOINT]},
            {"fields": ["systemic_symptoms"], "predicate": "true_in_any_source", "fact_keys": [SEPSIS]},
            {"fields": ["trauma", "mechanical_locking"], "predicate": "both_true_in_any_source", "fact_keys": ["KNEE.MENISCUS.MOTION_BLOCK"]},
            {"fields": ["trauma", "neurovascular_symptoms"], "predicate": "both_true_in_any_source", "fact_keys": [NEUROVASCULAR]},
        ],
    })
    grouped, effective, reasons = _effective_answers(context)
    gaps = []
    candidates = []
    review = []

    if context.body_region != "knee":
        review.append("outside_knee_scope" if context.body_region == "other" else "body_region_requires_physician_clarification")
    else:
        for index, (field, _, fact_key, condition) in enumerate(QUESTION_CONTENT):
            if not _condition_met(condition, effective):
                continue
            if field in effective:
                continue
            reason = reasons.get(field, "missing")
            clarify = reason in {"incomplete", "contradictory", "unverified"}
            gaps.append(InformationGap(field=field, reason=reason,
                                       requires_physician_review=reason != "missing"))
            if reason in {"unknown", "declined"}:
                review.append(reason + ":" + field)
                continue
            if clarify:
                review.append(reason + ":" + field)
            candidates.append(QuestionCandidate(
                question=bank.questions[index],
                field=field,
                rule_id="knee.history." + field,
                source_fact_keys=(fact_key,),
                source_content_sha256s=(facts[fact_key].content_sha256,),
                rationale_fa=("پاسخ ثبت‌شده کامل، سازگار یا تأییدشده نیست؛ پزشک باید همان داده را روشن کند."
                              if clarify else "این دادهٔ ساختاریافته ثبت نشده است و برای تکمیل شرح‌حال به بازبینی نیاز دارد."),
                action="physician_clarification" if clarify else "ask_missing",
            ))

    # Findings are never synthesized from history. Conflicting/unverified source
    # items remain available for review and cannot masquerade as usable findings.
    for field, reason in reasons.items():
        if field.startswith(("exam_", "imaging_")):
            gaps.append(InformationGap(field=field, reason=reason, requires_physician_review=True))
            review.append(reason + ":" + field)
    valid = tuple(item for item in context.observations if item.field in effective and item.state == "confirmed")
    unverified = tuple(item for item in context.observations if item.field not in effective or item.state != "confirmed")
    if context.body_region == "knee":
        # These are review prompts from Draft source content, NOT active safety
        # rules and NOT an infection/vascular diagnosis or urgency clearance.
        positive = {item.field for item in context.observations if item.value is True}
        if {"acute_swelling", "fever"} <= positive:
            review.append("draft_hot_joint_information_requires_prompt_physician_review")
        if "systemic_symptoms" in positive:
            review.append("draft_systemic_symptom_information_requires_physician_review")
        if {"trauma", "mechanical_locking"} <= positive:
            review.append("draft_traumatic_motion_block_information_requires_physician_review")
        if {"trauma", "neurovascular_symptoms"} <= positive:
            review.append("draft_neurovascular_trauma_information_requires_prompt_physician_review")
    return OrthopedicQuestionResult(
        body_region=context.body_region,
        context_sha256=_digest(context.model_dump(mode="json")),
        rules_sha256=rules_sha256,
        bank=bank,
        structured_symptoms=tuple(item for item in valid if not item.field.startswith(("exam_", "imaging_"))),
        examination_findings=tuple(item for item in valid if item.field.startswith("exam_")),
        reviewed_imaging_findings=tuple(item for item in valid if item.field.startswith("imaging_")),
        unverified_findings=unverified,
        information_gaps=tuple(gaps),
        question_candidates=tuple(candidates),
        review_reasons=tuple(dict.fromkeys(review)),
    )
