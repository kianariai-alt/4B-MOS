"""Generate a source-organized review of five existing synthetic cases."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from backend.app.services.orthopedic_pain_injury import build_knee_pain_injury_review


ROOT = Path(__file__).resolve().parents[2]
CASE_IDS = ("baseline_chronic", "chronic_after_injury", "prior_surgery", "urgent_information", "conflicting_onset")
LABELS = {
    "context_present": "زمینهٔ ثبت‌شده برای مرور",
    "context_not_reported": "گزارش مؤید این زمینه ثبت نشده؛ بیماری رد نشده است",
    "information_missing": "اطلاعات قابل‌استفاده کافی نیست",
}


def synthetic_reviews():
    source = json.loads((ROOT / "docs/examples/orthopedic-reasoning-review-cases-v1.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in source["cases"]}
    results = []
    for identifier in CASE_IDS:
        case = deepcopy(cases[identifier])
        request = {"interview": case["request"], "supplemental_observations": []}
        if identifier == "baseline_chronic":
            for field, value in (
                ("age_band", "45_or_over"), ("morning_stiffness", "up_to_30_min"),
                ("pain_locations", ["anterior", "medial"]),
                ("aggravating_activities", ["walking", "stairs"]),
            ):
                request["supplemental_observations"].append({"field": field, "value": value,
                    "state": "confirmed", "provenance": "patient_report", "source_ref": "synthetic:zetamed:baseline"})
        if identifier == "chronic_after_injury":
            observations = request["interview"]["context"]["observations"]
            for item in observations:
                if item["field"] == "onset": item["value"] = "sudden"
                if item["field"] == "chief_complaint": item["value"] = "instability"
                if item["field"] == "trauma_mechanism": item["value"] = "sport_twist"
            if not any(item["field"] == "trauma_mechanism" for item in observations):
                observations.append({"field": "trauma_mechanism", "value": "sport_twist", "state": "confirmed",
                                     "provenance": "patient_report", "source_ref": "synthetic:zetamed:injury"})
            case["label_fa"] = "شروع ناگهانی در گذشته، تداوم سال‌ها و شکایت ناپایداری"
        if case["clinician_reference"]["status"] != "pending_independent_review":
            raise ValueError("This demo requires separate, still-pending clinical reference cases.")
        results.append((case, build_knee_pain_injury_review(request)))
    return results


def render_report():
    reviewed = synthetic_reviews()
    first = reviewed[0][1]
    lines = ["# نقشهٔ درد و آسیب بر محور مقالهٔ زتامد: اجرای پنج پروندهٔ ساختگی", "",
        "این گزارش از اجرای واقعی سرویس تولید شده است. مقالهٔ زتامد منبع اصلی سازمان‌دهی است؛ "
        "پشتوانهٔ روابط پزشکی و محدودیت هر کدام جدا ثبت می‌شوند. همهٔ موارد Draft و نیازمند بررسی مستقل متخصص‌اند؛ "
        "هیچ‌یک از این پنج پرونده پاسخ مرجع تأییدشدهٔ مستقل ندارد.", "",
        f"منبع اصلی: [{first.organizing_source.source.title}]({first.organizing_source.source.url})، "
        f"نقش `{first.organizing_source_role}`.", "",
        "هشت محور: زمان‌بندی، آسیب، علائم مکانیکی، درد قدامی و بارگذاری، علائم پایدار، خطر/التهاب، "
        "یافته‌های ساختاری و جراحی قبلی/شکاف پوشش.", ""]
    for case, result in reviewed:
        lines += ["## " + case["label_fa"], "", result.workbench.summary_fa, "",
            f"وضعیت کار: `{result.workbench.workflow_status}`؛ تعلیق بررسی معمول: "
            + ("بله" if result.routine_evaluation_withheld else "خیر؛ این وضعیت تأیید ایمنی نیست"), "",
            "| محور | وضعیت زمینه | مشاهدات واقعیِ قابل‌استفاده | مقایسهٔ موجود |",
            "|---|---|---|---|"]
        for route in result.routes:
            values = "؛ ".join(f"{row.field}: {row.value_fa} [{row.source_ref}]" for row in route.observations
                               if row.usability == "usable") or "دادهٔ قابل‌استفاده کافی نیست"
            columns = (route.label_fa, LABELS[route.status], values,
                       ", ".join(route.differential_comparison_ids) or "بازبینی پزشک / حوزهٔ فاقد مدل اختصاصی")
            lines.append("| " + " | ".join(item.replace("|", " / ").replace("\n", " ") for item in columns) + " |")
        if result.workbench.quarantined_observations:
            lines += ["", "داده‌های کنارگذاشته‌شده برای استدلال، با حفظ گزارش اولیه:", ""]
            for row in result.workbench.quarantined_observations:
                lines.append(f"- `{row.field}`: {row.value_fa}؛ حالت `{row.state}`، دلیل `{row.reason}`، منبع `{row.source_ref}`.")
        if result.raw_risk_observations:
            lines += ["", "گزارش‌های مثبت خطر، از جمله گزارش تأییدنشده، حفظ شده‌اند:", ""]
            for row in result.raw_risk_observations:
                lines.append(f"- `{row.field}`: `{row.state}`، `{row.usability}`، منبع `{row.source_ref}`؛ تشخیص از این داده صادر نشده است.")
        candidates = [item for item in result.workbench.next_items
                      if item.category == "patient_question" and item.action == "ask_missing"]
        if result.workbench.workflow_status in {"prompt_physician_review", "outside_scope", "side_specific_review"}:
            candidates = []
        lines += ["", "سؤال معمول بعدی: " + (candidates[0].question.text_fa if candidates else
                  "پرسش خودکار معمول عرضه نشده است؛ وضعیت بررسی پزشک و شکاف‌های ثبت‌شده ملاک‌اند."), "",
                  f"هش نتیجه: `{result.result_sha256}`", ""]
    lines += ["## حوزه‌هایی که مدل اختصاصی آن‌ها کامل نشده است", ""]
    for gap in first.coverage_gaps:
        lines.append(f"- {gap.label_fa}: {gap.reason_fa}")
    lines += ["", "## پیوند محورها به منابع", ""]
    for route in first.routes:
        lines += [f"- `{route.id}`: {route.article_section_locator}؛ گزاره‌های پزشکی: "
                  + ", ".join(f"`{key}`" for key in route.source_fact_keys)]
    lines += ["", "## حدود این اجرا", "",
        "- منبع وب به‌عنوان تشخیص‌گر، امتیاز احتمال، دستور MRI یا ضرورت جراحی استفاده نشده است.",
        "- شروع ناگهانی و تداوم سال‌ها در پروندهٔ دوم مستقل باقی مانده‌اند؛ از شروع ناگهانی، آسیب اخیر یا شدت زیاد ساخته نشده است.",
        "- درد قدامی به آسیب غضروف، ناپایداری به پارگی قطعی ACL و سابقهٔ جراحی به وجود پروتز تبدیل نشده است.",
        "- مدل ایمنی موجود اجرا نشده است؛ توقف‌ها حفظ شده‌اند و نبود هشدار ایمنی را تأیید نمی‌کند.",
        "- بستهٔ ویندوز ۰٫۲ هنوز این افزونه را ندارد.",
        f"- هش بایت پاسخ وب ثبت‌شده: `{first.source_document_sha256}`؛ HTML خام نگه‌داری نشده است.",
        f"- هش فرادادهٔ دریافت: `{first.source_snapshot_metadata_sha256}`.",
        f"- هش قواعد اجرا: `{first.rules_sha256}`.",
        "- دو گزارهٔ تازه Draft، موجودی تألیفی ۴۳ مفهوم و Approved صفر؛ واردسازی Registry انجام نشده است.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-report", type=Path)
    args = parser.parse_args()
    report = render_report()
    if args.write_report:
        args.write_report.write_text(report, encoding="utf-8")
        print(str(args.write_report))
    else:
        print(report)


if __name__ == "__main__":
    main()
