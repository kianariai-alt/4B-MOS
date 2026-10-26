"""Audit reasoning coverage with synthetic cases; do not claim clinical accuracy.

Read-only by default. --write-report writes one explicitly requested Markdown
review file. Independent clinician reference answers remain pending.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.services.orthopedic_assessment import export_offline_assessment
from backend.app.services.orthopedic_interview_tree import build_interview_tree
from backend.app.services.orthopedic_reasoning_review import build_knee_reasoning_review


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "docs/examples/orthopedic-reasoning-review-cases-v1.json"
ROLE_LABELS = {
    "pattern_matching": "شرط مستقیم تطبیق الگو",
    "workflow_only": "فقط دامنه، ابهام، خطر یا پیش‌نیاز",
    "episode_presence_only": "فقط حضور سابقهٔ درمان، بدون تفسیر محتوا",
    "not_used_in_assessment": "بدون نقش در تطبیق یا توقف assessment",
}
STATUS_LABELS = {
    "matched_pattern": "تطبیق با الگوی محدود",
    "pattern_not_matched": "عدم تطبیق الگو؛ بیماری رد نشده",
    "information_missing": "اطلاعات ناکافی",
    "withheld_by_workflow": "انتظار بررسی پیش‌نیاز یا فوریت",
}


def audit_question_roles():
    """Count data dependencies in actual exported tables, not clinical value."""
    model = export_offline_assessment()
    axes = {axis["id"]: axis for axis in model["axes"]}
    card_fields = {axes[id]["field"] for table in model["card_tables"] for id in table["axis_ids"]}
    guard_fields = {axes[id]["field"] for table in model["guard_tables"] for id in table["axis_ids"]}
    result = []
    for node in build_interview_tree().nodes:
        role = ("pattern_matching" if node.field in card_fields else "workflow_only" if node.field in guard_fields
                else "episode_presence_only" if node.repeat_per_treatment else "not_used_in_assessment")
        result.append({"number": node.number, "field": node.field, "role": role, "label_fa": node.question.text_fa})
    return result


def build_challenge_review():
    fixture = json.loads(CASES.read_text(encoding="utf-8"))
    if fixture.get("synthetic_only") is not True or fixture.get("clinically_validated") is not False:
        raise ValueError("Only explicit unvalidated synthetic challenge cases are accepted.")
    cases = []
    for item in fixture["cases"]:
        if item["clinician_reference"]["status"] != "pending_independent_review":
            raise ValueError("Reference adjudication must be introduced through a separate reviewed contract.")
        review = build_knee_reasoning_review(item["request"])
        cases.append({"id": item["id"], "label_fa": item["label_fa"], "review": review,
                      "clinician_reference_status": "pending_independent_review"})
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Challenge case identifiers must be unique.")
    return {"cases": cases, "question_roles": audit_question_roles(), "independent_reference_count": 0}


def render_markdown(result):
    roles = result["question_roles"]
    lines = [
        "# بازبینی عمق استدلال پزشکیار زانو",
        "",
        "این گزارش از کد و ده ورودی ساختگی تولید شده است. هدف، آشکارکردن محدودیت مدل و حفظ شواهد پرونده است؛ عدد دقت تشخیصی یا تأیید بالینی ارائه نمی‌شود.",
        "",
        "مرجع مستقل متخصص: **۰ پرونده**. پاسخ‌های مرجع هر ده پرونده هنوز در انتظار بررسی‌اند. تفاوت خروجی‌های زیر به‌تنهایی نشان نمی‌دهد تشخیص واقعی چه بوده است.",
        "",
        "## نقش واقعی سؤال‌ها در مدل فعلی",
        "",
        "| نقش در assessment | تعداد | شماره‌ها |",
        "|---|---:|---|",
    ]
    for role, label in ROLE_LABELS.items():
        numbers = [row["number"] for row in roles if row["role"] == role]
        lines.append(f"| {label} | {len(numbers)} | {', '.join(map(str,numbers))} |")
    lines.extend([
        "",
        "این جدول وابستگی نرم‌افزار را نشان می‌دهد؛ همهٔ سؤال‌ها نباید تشخیص را تغییر دهند. محدودیت فعلی آن است که شدت، عملکرد، اهداف، بیماری‌های همراه و داروها نیز برنامهٔ شخصیِ ارزیابی/مدیریت ایجاد نمی‌کنند.",
        "",
        "مدل فعلی فقط دو الگوی علائمی و دو کارت یافتهٔ تصویر دارد. هیچ یافتهٔ معاینه برای تطبیق آن‌ها مصرف نمی‌شود. گزارش جدید این یافته‌ها را حفظ و مصرف‌نشدنشان را صریح می‌کند.",
        "",
        "## مقایسه‌های چالشی",
        "",
    ])
    by_id = {case["id"]: case["review"] for case in result["cases"]}
    baseline = by_id["baseline_chronic"].baseline_assessment
    base_ids = [item.id for item in baseline.considerations]
    for id, label in (("chronic_after_injury", "افزودن سابقهٔ آسیب به همان درد مزمن"),
                      ("prior_surgery", "افزودن سابقهٔ جراحی و شرح بیمار"),
                      ("recorded_exam", "افزودن معاینهٔ ثبت‌شده"),
                      ("zero_now", "تغییر درد فعلی به صفر، عملکرد و هدف مراجعه")):
        review = by_id[id]
        current = review.baseline_assessment
        lines.append(f"- **{label}:** وضعیت مدل `{current.status}`؛ افتراق‌های منتشرشده `{[item.id for item in current.considerations]}`؛ برابری با افتراق‌های پایه: `{[item.id for item in current.considerations] == base_ids}`؛ یافتهٔ بالینیِ مصرف‌نشده در تطبیق: `{len(review.clinical_findings_not_used_by_current_model)}`.")
    for case in result["cases"]:
        r = case["review"]
        lines.extend(["", "## " + case["label_fa"], "", r.problem_representation.summary_fa,
                      "", "گزارش‌ها از منشأ اعلام‌شده‌اند و احراز اصالت پرونده نیستند.",
                      "", f"وضعیت پیش‌نمایش قبلی: `{r.baseline_assessment.status}`؛ دادهٔ قرنطینه‌شده: `{len(r.quarantined_observations)}`.",
                      "", "| فرضیهٔ محدود مدل | وضعیت این پرونده |", "|---|---|"])
        for h in r.hypothesis_reviews:
            lines.append(f"| {h.label_fa} | {STATUS_LABELS[h.status]}؛ وضعیت الگو: {STATUS_LABELS[h.pattern_status]} |")
        for h in r.hypothesis_reviews:
            lines.extend(["", "**دفتر شواهد: " + h.label_fa + "**", ""])
            for criterion in h.criteria:
                refs = ", ".join(row.source_ref for row in criterion.observations) or "منشأ دادهٔ قابل‌استفاده موجود نیست"
                lines.append("- " + criterion.explanation_fa + " منشأ: `" + refs + "`.")
        if r.problem_representation.examination:
            lines.extend(["", "**یافته‌های واقعیِ معاینه در ورودی:**", ""])
            for item in r.problem_representation.examination:
                lines.append(f"- {item.label_fa}: {item.value_fa}؛ منشأ `{item.source_ref}`. این ثبت، استفادهٔ تشخیصی از آن در مدل فعلی را ثابت نمی‌کند.")
        lines.extend(["", "**اطلاعات و کارهای بازبینی:**", ""])
        for requirement in r.next_data_requirements[:8]:
            lines.append("- " + requirement.reason_fa + (f" سؤال موجود: {requirement.existing_question_number}." if requirement.existing_question_number else ""))
        lines.extend(["", f"هش گزارش: `{r.result_sha256}`؛ هش assessment قبلی: `{r.assessment_sha256}`."])
    lines.extend(["", "## مرز این اصلاح", "",
                  "این لایه توضیح مبتنی بر ورودی، دفتر شواهد و نقص پوشش را اضافه می‌کند. تشخیص‌ها، شروط تطبیق، قواعد خطر و شواهد درمان قبلی را تغییر نمی‌دهد. هنوز پزشکیار جامع یا معتبر بالینی ساخته نشده است.",
                  "",
                  "مرحلهٔ لازم برای ارزیابی بالینی: تکمیل مرجع هر پرونده توسط متخصص، ثبت افتراق‌ها و دلیل انتظار، سپس سنجش خطاهای مدل روی پرونده‌هایی که برای تألیف قواعد استفاده نشده‌اند. گزارش نباید مرجع خالی را با خروجی خود مدل پر کند.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-report", type=Path)
    args = parser.parse_args(argv)
    result = build_challenge_review()
    if args.write_report:
        args.write_report.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"synthetic_cases": len(result["cases"]), "independent_clinician_references": 0,
                      "clinically_validated": False,
                      "question_roles": {key: sum(row["role"] == key for row in result["question_roles"]) for key in ROLE_LABELS},
                      "report": str(args.write_report) if args.write_report else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
