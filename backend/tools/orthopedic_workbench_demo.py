"""Run a synthetic adaptive interview through the real stateless turn service.

The default prints a short Persian review report. Writing is explicit; no
patient, Registry, source approval, network call or Windows package is involved.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest
from backend.app.services.orthopedic_workbench import build_knee_workbench
from backend.app.services.orthopedic_workbench_turn import apply_knee_workbench_turn


# Controlled responses for one entirely fictional case, not a clinician's
# reference diagnosis. The service, rather than this dict's order, selects each
# next question and activates or closes its follow-up branches.
SYNTHETIC_RESPONSES = {
    "chief_complaint": "pain", "laterality": "right", "trauma": False,
    "fever": False, "acute_swelling": False, "systemic_symptoms": False,
    "has_pain": True, "onset": "gradual", "duration": "years",
    "pain_locations": ["anterior", "medial"], "pain_score_now": 6,
    "pain_pattern": "activity", "aggravating_activities": ["walking", "stairs"],
    "relieving_factor": "rest", "mechanical_locking": False,
    "functional_limitation": "moderate", "prior_surgery": False,
    "prior_treatment": False, "age_band": "45_or_over",
    "morning_stiffness": "up_to_30_min", "care_goals": ["pain", "function"],
    "diagnosed_conditions": "در این پروندهٔ ساختگی بیماری تشخیص‌داده‌شده‌ای گزارش نشده است.",
    "medication_list": "در این پروندهٔ ساختگی دارویی گزارش نشده است.",
}


def synthetic_walkthrough():
    state = KneeWorkbenchRequest(interview={"context": {"body_region": "knee"}})
    workbench = build_knee_workbench(state)
    turns = []
    for _ in range(50):
        if workbench.workflow_status in {"prompt_physician_review", "outside_scope", "side_specific_review"}:
            break
        next_item = next((item for item in workbench.next_items
                          if item.category == "patient_question" and item.action == "ask_missing"
                          and item.question is not None), None)
        if next_item is None:
            break
        field = next_item.field
        if any(row["field"] == field for row in turns):
            raise RuntimeError("The synthetic interview repeated an answered field.")
        if field not in SYNTHETIC_RESPONSES:
            raise RuntimeError("The fixture does not declare a response to " + field)
        answer = {"respondent": "patient", "observation": {
            "field": field, "state": "confirmed", "value": SYNTHETIC_RESPONSES[field],
            "provenance": "patient_report", "source_ref": "synthetic:adaptive:" + str(len(turns) + 1),
        }}
        result = apply_knee_workbench_turn({"state": state, "answer": answer})
        rows = (*result.state.interview.context.observations, *result.state.supplemental_observations)
        response = next(row for row in rows if row.field == field)
        display = next((row.value_fa for row in result.workbench.supplemental_observations
                        if row.field == field and row.usability == "usable"), None)
        if display is None:
            display = next(row.value_fa for row in result.workbench.baseline_review.problem_representation.history
                           if row.field == field)
        turns.append({"field": field, "question": next_item.question.text_fa,
                      "answer_fa": display, "value": response.value,
                      "next_field": result.next_patient_question.field if result.next_patient_question else None,
                      "result_sha256": result.result_sha256})
        state, workbench = result.state, result.workbench
    else:
        raise RuntimeError("The synthetic adaptive walkthrough did not terminate.")
    # A physician finding is deliberately separate from patient interviewing.
    prior = next(row for item in workbench.comparisons for row in item.relationships
                 if row.field == "exam_squat_anterior_pain")
    exam = apply_knee_workbench_turn({"state": state, "answer": {
        "respondent": "physician", "observation": {
            "field": "exam_squat_anterior_pain", "state": "confirmed", "value": True,
            "provenance": "physician_exam", "source_ref": "synthetic:physician:squat",
        },
    }})
    after = next(row for item in exam.workbench.comparisons for row in item.relationships
                 if row.field == "exam_squat_anterior_pain")
    return turns, exam, (prior.relation, after.relation)


def render_report() -> str:
    turns, final, exam_change = synthetic_walkthrough()
    result = final.workbench
    lines = [
        "# نمونهٔ اجرایی گفتگوی پویا و چندانتخابی زانو",
        "", "این گزارش از اجرای واقعی سرویس روی یک پروندهٔ کاملاً ساختگی تولید شده است. "
        "همهٔ روابط جدید Draft و نیازمند بررسی مستقل‌اند. پاسخ مرجع مستقل پزشک هنوز ثبت نشده است؛ "
        "این گزارش آزمون دقت تشخیص یا تأیید استفادهٔ بالینی نیست.",
        "", "ترتیب سؤال‌ها را سرویس پس از هر پاسخ محاسبه کرده است؛ "
        "گزینه‌های چندانتخابی به یک گزینه فروکاسته نشده‌اند.",
        "", "| نوبت | سؤال عرضه‌شده | پاسخ ساختگی | فیلد سؤال بعدی |",
        "|---|---|---|---|",
    ]
    for index, turn in enumerate(turns, 1):
        cells = [str(index), turn["question"], turn["answer_fa"], turn["next_field"] or "پرسش معمول باقی نمانده"]
        lines.append("| " + " | ".join(cell.replace("|", " / ").replace("\n", " ") for cell in cells) + " |")
    lines += ["", "## معاینهٔ جداگانهٔ پزشک", "",
              "پس از شرح‌حال، یافتهٔ ساختگی معاینهٔ اسکوات در کانال پزشک ثبت شد. "
              f"رابطهٔ مربوط از `{exam_change[0]}` به `{exam_change[1]}` تغییر کرد؛ "
              "این تغییر سازگاری شواهد است، نه اثبات تشخیص.",
              "", "## جمع‌بندی قابل بازبینی", "", result.summary_fa]
    for comparison in result.comparisons:
        lines += ["", "### " + comparison.label_fa, "", comparison.summary_fa, ""]
        for row in comparison.relationships:
            observations = "; ".join(f"{item.value_fa} [{item.source_ref}]" for item in row.observations
                                     if item.usability == "usable") or "دادهٔ قابل‌استفاده ندارد"
            lines.append(f"- `{row.field}` / `{row.relation}`: {observations}. {row.explanation_fa}")
        lines += ["", "محدودیت: " + " ".join(comparison.limitations_fa)]
    lines += ["", "## منشأ و حدود", "",
              f"- تعداد نوبت‌های بیمار: {len(turns)}؛ یک نوبت معاینهٔ جداگانه.",
              f"- وضعیت نمای پایه: `{result.baseline_workflow_status}`؛ وضعیت نمای چندانتخابی: `{result.workflow_status}`.",
              "- تنها هم‌ارزی ثبت‌شده: چند محل درد، شکاف فیلد تک‌محلیِ ثبت‌نشده را پوشش می‌دهد؛ هیچ شرط خطر، تعارض یا جراحی قبلی حذف نشده است.",
              "- هدف‌های کاهش درد و بهبود عملکرد هر دو حفظ شده‌اند؛ از آن‌ها طرح درمان خودکار ساخته نشده است.",
              "- احتمال یا رتبهٔ تشخیص، اثبات علت درد از تصویر، اثربخشی درمان یا بازسازی غضروف تولید نشده است.",
              "- این نما موتور ایمنی موجود را اجرا نمی‌کند و فقدان هشدار تأیید ایمنی نیست.",
              "- نسخهٔ ویندوز ۰٫۲ شامل این افزونه نیست؛ این گزارش اجرای نسخهٔ سرویس را نشان می‌دهد.",
              f"- هش قواعد: `{result.rules_sha256}`",
              f"- هش مجموعهٔ منابع: `{result.source_set_sha256}`",
              f"- هش نتیجهٔ نوبت آخر: `{final.result_sha256}`",
              "", "### پنج گزارهٔ تازهٔ Draft", ""]
    for proposal in result.new_draft_proposals:
        lines.append(f"- `{proposal.fact.fact_key}`، نسخهٔ {proposal.version}، هش محتوای تألیفی `{proposal.content_sha256}`")
    lines += ["", "### منابع مقایسهٔ تازه", ""]
    for source in result.source_references:
        if source.source_key.endswith("_workbench"):
            lines += [f"- [{source.source.title}]({source.source.url}) — `{source.access_level}`. {source.verification_note}"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-report", type=Path, help="Explicitly write this synthetic Markdown report.")
    args = parser.parse_args()
    report = render_report()
    if args.write_report:
        args.write_report.write_text(report, encoding="utf-8")
        print(str(args.write_report))
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
