"""Explain the current model with supplied observations, without new medicine.

All pattern results are delegated unchanged to the existing assessment. This
wrapper reveals data provenance, unassessed coverage and the actual criteria of
every limited pattern, including those not emitted by the baseline workflow.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from backend.app.schemas import orthopedic_reasoning_review as review_schema
from backend.app.schemas.orthopedic_interview_tree import KneeInterviewTreePreviewRequest, TEXT_FIELDS
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_reasoning_review import (
    ClinicalProblemRepresentation, KneeReasoningReview, ReasoningCriterion,
    ReasoningDataRequirement, ReasoningHypothesisReview, ReasoningObservation,
    ReasoningTreatmentEpisode,
)
from backend.app.services.orthopedic_assessment import build_knee_assessment, export_offline_assessment
from backend.app.services.orthopedic_interview_tree import build_interview_tree_preview


VERSION = "1.0.0"
VALUE_LABELS = {
    "right": "راست", "left": "چپ", "both": "هر دو", "pain": "درد", "swelling": "تورم",
    "locking": "گیرکردن حرکت", "instability": "احساس ناپایداری", "other": "سایر",
    "sudden": "ناگهانی", "gradual": "تدریجی", "unclear": "نامشخص",
    "days": "روزها", "weeks": "هفته‌ها", "months": "ماه‌ها", "years": "سال‌ها",
    "anterior": "جلوی زانو", "medial": "سمت داخلی", "lateral": "سمت خارجی",
    "posterior": "پشت زانو", "diffuse": "پراکنده", "activity": "هنگام فعالیت",
    "rest": "هنگام استراحت", "night": "شب", "mixed": "ترکیبی",
    "walking": "راه‌رفتن", "stairs": "پله", "loaded_flexion": "خم‌کردن زیر بار",
    "none": "هیچ‌کدام", "mild": "کم", "moderate": "متوسط", "severe": "زیاد",
    "sport_twist": "چرخش هنگام ورزش", "fall": "زمین‌خوردن", "direct_impact": "ضربهٔ مستقیم",
    "improved": "بهتر شده", "unchanged": "بدون تغییر", "worse": "بدتر شده",
    "function": "بهبود عملکرد", "decision_support": "کمک به تصمیم‌گیری",
    "full": "کامل", "restricted": "محدود",
}
SPECIAL_LABELS = {
    "has_pain": "وجود درد در دورهٔ مشکل زانو", "exam_joint_line_tenderness": "حساسیت خط مفصلی در معاینه",
    "exam_effusion": "افیوژن در معاینه", "exam_range_of_motion": "دامنهٔ حرکت در معاینه",
    "imaging_kl_grade": "درجهٔ رادیوگرافیک Kellgren–Lawrence",
    "imaging_meniscal_lesion": "ضایعهٔ منیسک در گزارش تصویر",
    "imaging_cartilage_lesion": "ضایعهٔ غضروفی در گزارش تصویر",
}
STORY_LABELS = (
    ("laterality", "سمت"), ("chief_complaint", "شکایت اصلی"), ("has_pain", "وجود درد"),
    ("onset", "شروع"), ("duration", "مدت"), ("pain_location", "محل درد"),
    ("pain_pattern", "الگوی درد"), ("pain_score_now", "شدت درد همین حالا از ۱۰"),
    ("functional_limitation", "محدودیت عملکرد"), ("trauma", "آسیب مشخص"),
    ("trauma_mechanism", "مکانیسم گزارش‌شدهٔ آسیب"), ("prior_surgery", "جراحی قبلی"),
)
REVIEW_LABELS = {
    "knee_oa": "بررسی الگوی آرتروز زانو",
    "patellofemoral_pain": "بررسی الگوی درد پاتلوفمورال",
    "meniscal_finding": "بررسی زمینهٔ یافتهٔ منیسک در تصویربرداری",
    "cartilage_finding": "بررسی زمینهٔ یافتهٔ غضروفی در تصویربرداری",
}
# These describe gaps in the current input contract, not missing facts inferred
# about an actual patient and not additional approved diagnostic requirements.
COVERAGE_GAPS = {
    "knee_oa": (
        ("age_band", "گروه سنی در این قرارداد قابل‌ثبت نیست؛ تناسب جمعیت و معیارهای وابسته به سن بررسی نشده‌اند."),
        ("morning_stiffness_duration", "مدت خشکی صبحگاهی در این قرارداد قابل‌ثبت نیست؛ معیار تشخیصی رسمی کامل ارزیابی نشده است."),
    ),
    "patellofemoral_pain": (
        ("patellofemoral_provocation_exam", "بازآفرینی اختصاصی علائم قدامی و کنارگذاشتن علل دیگر در معاینه، در فیلدهای فعلی کامل قابل‌ثبت نیست."),
    ),
    "meniscal_finding": (
        ("meniscal_lesion_characterization", "نوع و زمینهٔ ساختاری ضایعهٔ منیسک در پرچم عمومی تصویر قابل‌ثبت نیست؛ تطبیق پزشک لازم است."),
    ),
    "cartilage_finding": (
        ("cartilage_lesion_location_grade", "محل و درجهٔ ساختاری ضایعه در پرچم عمومی تصویر قابل‌ثبت نیست."),
        ("ocd_specific_context", "زمینهٔ اختصاصی OCD، پایداری و بلوغ اسکلتی در این پرچم قابل‌ثبت نیستند؛ از آن‌ها نتیجه‌گیری نمی‌شود."),
    ),
}


def _display(item):
    if item.state == "unknown":
        return "نمی‌دانم"
    if item.state == "declined":
        return "مایل به پاسخ نیستم"
    if item.value is None:
        return "مقدار کامل ثبت نشده"
    if item.field in TEXT_FIELDS:
        return item.value
    if type(item.value) is bool:
        return "بله" if item.value else "خیر"
    if type(item.value) is int:
        return str(item.value)
    if item.field == "care_goal":
        return {"pain": "کاهش درد", "function": "بهبود عملکرد", "activity": "فعالیت", "decision_support": "کمک به تصمیم‌گیری"}.get(item.value, item.value)
    return VALUE_LABELS.get(item.value, item.value)


def build_knee_reasoning_review(request: KneeInterviewTreePreviewRequest | dict) -> KneeReasoningReview:
    """Return a faithful audit of this model, not a broader diagnosis engine."""
    request = KneeInterviewTreePreviewRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, KneeInterviewTreePreviewRequest) else request
    )
    preview = build_interview_tree_preview(request)
    assessment = build_knee_assessment(request)
    model = export_offline_assessment()
    if assessment.lookup_model_sha256 != model["model_sha256"]:
        raise ValueError("Assessment and reasoning review must use the same immutable lookup model.")
    nodes = {node.field: node for node in preview.tree.nodes}
    labels = {field: node.question.text_fa for field, node in nodes.items()}
    labels.update(SPECIAL_LABELS)
    usable_history = {(item.field, item.source_ref) for item in preview.structured_answers}
    usable_clinical = {(item.field, item.source_ref) for item in preview.usable_clinical_findings}
    gaps = {(item.field, item.episode_ref): item for item in preview.information_gaps}

    def observation(item, usable, episode_ref=None):
        gap = gaps.get((item.field, episode_ref))
        return ReasoningObservation(
            field=item.field, label_fa=labels.get(item.field, item.field), value=item.value,
            value_fa=_display(item), state=item.state, provenance=item.provenance, source_ref=item.source_ref,
            episode_ref=episode_ref, usability="usable" if usable else "quarantined",
            reason=None if usable else gap.reason if gap else item.state,
        )

    history_rows = tuple(observation(item, (item.field, item.source_ref) in usable_history)
                         for item in request.context.observations)
    clinical_rows = tuple(observation(item, (item.field, item.source_ref) in usable_clinical)
                          for item in request.context.clinical_findings)
    episode_rows = []
    prior_treatment = any(row.field == "prior_treatment" and row.value is True and row.usability == "usable" for row in history_rows)
    for episode in request.context.treatment_episodes:
        rows = tuple(observation(item, prior_treatment and item.state == "confirmed"
                                 and (item.field, episode.episode_ref) not in gaps, episode.episode_ref)
                     for item in episode.observations)
        episode_rows.append(ReasoningTreatmentEpisode(episode_ref=episode.episode_ref, observations=rows))
    raw_by_field = {}
    for row in (*history_rows, *clinical_rows):
        raw_by_field.setdefault(row.field, []).append(row)
    usable_by_field = {}
    for row in history_rows:
        if row.usability == "usable":
            usable_by_field.setdefault(row.field, row)
    story = [f"{label}: {usable_by_field[field].value_fa}" for field, label in STORY_LABELS if field in usable_by_field]
    region = {"knee": "زانو", "other": "خارج از زانو", "unknown": "نامشخص"}[request.context.body_region]
    summary = "ناحیهٔ ثبت‌شده: " + region + ("؛ " + "؛ ".join(story) if story else "؛ شرح‌حال قابل‌استفاده هنوز ثبت نشده است")
    problem = ClinicalProblemRepresentation(
        body_region=request.context.body_region, summary_fa=summary,
        history=tuple(row for row in history_rows if row.usability == "usable"),
        examination=tuple(row for row in clinical_rows if row.usability == "usable" and row.field.startswith("exam_")),
        imaging=tuple(row for row in clinical_rows if row.usability == "usable" and row.field.startswith("imaging_")),
        treatment_episodes=tuple(episode_rows),
    )
    quarantined = tuple(row for row in (*history_rows, *clinical_rows,
                                        *(row for episode in episode_rows for row in episode.observations))
                        if row.usability == "quarantined")
    axes = {axis["id"]: axis for axis in model["axes"]}
    cards = {card["id"]: card for card in model["cards"]}
    candidates = {(item.field, item.episode_ref): item for item in preview.question_candidates}
    requirements = []

    def requirement(id, category, field, hypothesis_ids, reason, keys=(), hashes=(), current_reason=None):
        candidate = candidates.get((field, None))
        gap = gaps.get((field, None))
        if category == "schema_coverage_gap":
            action = "schema_extension_review"
        elif gap and gap.reason in {"unknown", "declined"}:
            action = "not_automatically_reask"
        elif candidate:
            action = candidate.action
        else:
            action = "physician_review"
        return ReasoningDataRequirement(
            id=id, category=category, field=field, hypothesis_ids=tuple(hypothesis_ids), reason_fa=reason,
            current_reason=current_reason or (gap.reason if gap else None),
            existing_question_id=candidate.question.id if candidate else None,
            existing_question_number=candidate.number if candidate else None,
            question_action=action, supported_by_current_context=category != "schema_coverage_gap",
            source_fact_keys=tuple(keys), source_content_sha256s=tuple(hashes),
        )

    blocked = False
    for guard in model["guard_tables"]:
        outcome = guard["rows"]["|".join(assessment.axis_tokens[id] for id in guard["axis_ids"])]
        if outcome["status"] == "ready":
            continue
        blocked = True
        fields = tuple(dict.fromkeys(axes[id]["field"] for id in guard["axis_ids"]))
        # A gate may depend on several fields; do not ask a known answer again.
        unresolved = [field for field in fields if (field, None) in gaps]
        field = unresolved[0] if unresolved else fields[0] if len(fields) == 1 else None
        keys = outcome["source_fact_keys"]
        hashes_by_fact = {key: digest for card in (*model["cards"], *model["urgent_cards"])
                          for key, digest in zip(card["source_fact_keys"], card["source_content_sha256s"], strict=True)}
        requirements.append(requirement(
            "workflow:" + guard["id"], "workflow_prerequisite", field, (), outcome["reason_fa"],
            keys, (hashes_by_fact[key] for key in keys), current_reason=outcome["status"],
        ))
    reviews = []
    for table in model["card_tables"]:
        card = cards[table["id"]]
        positive_rows = [key.split("|") for key, matches in table["rows"].items() if matches]
        criteria = []
        for index, axis_id in enumerate(table["axis_ids"]):
            axis = axes[axis_id]
            field = axis["field"]
            expected = tuple(sorted({values[index] for values in positive_rows}))
            token = assessment.axis_tokens[axis_id]
            relation = "unresolved" if token == "u" else "matched" if token in expected else "mismatched"
            observations = tuple(raw_by_field.get(field, ()))
            values = "؛ ".join(dict.fromkeys(row.value_fa for row in observations if row.usability == "usable"))
            if relation == "unresolved":
                explanation = labels.get(field, field) + ": دادهٔ قابل‌استفاده برای این شرط موجود نیست؛ فقدان داده پاسخ منفی نیست."
            elif relation == "matched":
                explanation = labels.get(field, field) + ": " + values + "؛ این پاسخ با شرط الگوی تألیفی فعلی تطبیق دارد و به‌تنهایی اثبات تشخیص نیست."
            else:
                explanation = labels.get(field, field) + ": " + values + "؛ با شرط الگوی فعلی تطبیق ندارد؛ این ناسازگاریِ الگویی بیماری را رد نمی‌کند."
            criteria.append(ReasoningCriterion(
                axis_id=axis_id, field=field, input_channel=axis["input"], observed_token=token,
                expected_tokens=expected, relation=relation, explanation_fa=explanation,
                observations=observations, source_fact_keys=card["source_fact_keys"],
                source_content_sha256s=card["source_content_sha256s"],
            ))
            if relation == "unresolved":
                note = explanation
                if axis["input"] == "usable_clinical":
                    note += " نبود این داده سفارش یا ضرورت تصویربرداری ایجاد نمی‌کند."
                requirements.append(requirement(
                    "missing:" + table["id"] + ":" + field, "missing_current_field", field, (table["id"],), note,
                    card["source_fact_keys"], card["source_content_sha256s"],
                ))
        token_key = "|".join(assessment.axis_tokens[id] for id in table["axis_ids"])
        pattern_status = ("information_missing" if any(row.relation == "unresolved" for row in criteria) else
                          "matched_pattern" if table["rows"][token_key] else "pattern_not_matched")
        coverage = tuple(requirement(
            "coverage:" + table["id"] + ":" + field, "schema_coverage_gap", field, (table["id"],), note,
            card["source_fact_keys"], card["source_content_sha256s"], current_reason="not_represented_in_context_v1",
        ) for field, note in COVERAGE_GAPS[table["id"]])
        requirements.extend(coverage)
        reviews.append(ReasoningHypothesisReview(
            hypothesis_id=table["id"], label_fa=REVIEW_LABELS[table["id"]],
            status="withheld_by_workflow" if blocked else pattern_status, pattern_status=pattern_status,
            criteria=tuple(criteria), patient_grounded_support_fa=tuple(row.explanation_fa for row in criteria if row.relation == "matched"),
            pattern_mismatches_fa=tuple(row.explanation_fa for row in criteria if row.relation == "mismatched"),
            schema_coverage_gaps=coverage, limitations_fa=tuple(card["limitations_fa"]) + (
                "این دفتر شواهد شرایط الگوی نرم‌افزاری را توضیح می‌دهد؛ میزان اختصاصی‌بودن، احتمال یا معیار تشخیصی معتبر ایجاد نمی‌کند.",
            ), source_fact_keys=card["source_fact_keys"], source_content_sha256s=card["source_content_sha256s"],
        ))
    used_clinical_fields = {axis["field"] for axis in model["axes"] if axis["input"] == "usable_clinical"}
    unused_clinical = tuple(row.model_copy(update={"reason": "not_used_by_current_model"}) for row in clinical_rows
                            if row.usability == "usable" and row.field not in used_clinical_fields)
    limitations = (
        "پوشش فعلی فقط دو الگوی علائمی و دو کارت یافتهٔ تصویری است؛ فهرست جامع تشخیص‌های افتراقی زانو نیست.",
        "تطبیق‌نداشتن یا منتشرنشدن یک کارت به معنی رد بیماری نیست؛ علت توقف و فقدان اطلاعات جدا نشان داده می‌شود.",
        "شرایط تطبیق و توقف همان نسخهٔ قبلی‌اند؛ این لایه سنجش منشأ و توضیح است، نه الگوریتم تشخیصی تازه.",
        "ملاحظات بالینی و درمانی نیازمند بررسی مستقل پزشک‌اند؛ سابقهٔ جراحی یا آسیب می‌تواند محدودیت مدل فعلی را آشکار کند، نه رد یک بیماری.",
        "یافته‌های معاینه حفظ می‌شوند؛ مدل فعلی از آن‌ها برای انتخاب الگوها استفاده نمی‌کند و این محدودیت صریح باقی می‌ماند.",
    )
    result = KneeReasoningReview(
        baseline_assessment=assessment, problem_representation=problem,
        quarantined_observations=quarantined, hypothesis_reviews=tuple(reviews),
        next_data_requirements=tuple(requirements), clinical_findings_not_used_by_current_model=unused_clinical,
        structural_limitations_fa=limitations, request_sha256=assessment.request_sha256,
        preview_sha256=preview.result_sha256, assessment_sha256=assessment.result_sha256,
        lookup_model_sha256=model["model_sha256"],
        rules_sha256=content_digest({"version": VERSION, "model_sha256": model["model_sha256"],
                                    "service_artifact_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                    "schema_artifact_sha256": hashlib.sha256(Path(review_schema.__file__).read_bytes()).hexdigest()}),
        result_sha256="0" * 64,
    )
    return result.model_copy(update={"result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))})
