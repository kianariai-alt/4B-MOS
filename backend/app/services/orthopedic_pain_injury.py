"""Zetamed-organized pain/injury review over the unchanged Draft workbench.

The article is central to organization, while clinical content remains bound
to independently identified sources and existing Registry-compatible drafts.
This does not rank diseases, run safety rules or approve a web-source claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.app.schemas import orthopedic_pain_injury as review_schema
from backend.app.schemas.medical_knowledge import KnowledgeFactCreate, KnowledgeSourceCreate
from backend.app.schemas.orthopedic_assessment import AssessmentDraftProposal
from backend.app.schemas.orthopedic_knowledge import SourceEntry, content_digest
from backend.app.schemas.orthopedic_pain_injury import (
    KneePainInjuryReview, PainInjuryCoverageGap, PainInjuryRoute, ZetamedSourceSnapshot,
)
from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest, WorkbenchObservation
from backend.app.services.medical_knowledge import knowledge_content_digest
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_workbench import build_knee_workbench


VERSION = "1.0.0"
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "knowledge/zetamed_knee_pain_source_v1.json"
COMBINED = "KNEE.PAIN_INJURY.MULTISTRUCTURE"
INSTABILITY = "KNEE.PAIN_INJURY.INSTABILITY_CONTEXT"
RISK_FIELDS = {"fever", "acute_swelling", "systemic_symptoms", "sensory_change", "weakness", "foot_coldness", "foot_color_change"}
ALIASES = {"pain_location": "pain_locations", "aggravating_factor": "aggravating_activities", "care_goal": "care_goals"}


def load_organizing_source_snapshot(raw: dict | None = None) -> dict:
    """Validate recorded acquisition metadata, without claiming to rehash HTML."""
    if raw is None:
        raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return ZetamedSourceSnapshot.model_validate(raw).model_dump(mode="json")


def _evidence(snapshot):
    organizing = SourceEntry(source_key="zetamed_knee_pain", verified_at="2026-10-26", access_level="full_text",
        source=KnowledgeSourceCreate(source_type="other", title="درد زانو — زتامد",
            citation="محمد زهرائی. درد زانو. زتامد. تاریخ درج‌شده ۵ سپتامبر ۲۰۲۵؛ بخش‌های زمان‌بندی، آسیب، علائم مکانیکی، آرتروز و زمینهٔ التهاب بازبینی شدند.",
            publisher="Zetamed", url=snapshot["url"], publication_date="2025-09-05",
            guideline_version=snapshot["source_version"], accessed_at="2026-10-26"),
        verification_note="Primary organizing source requested by the physician; educational webpage. Independent medical approval is absent. Recorded response-body hash identifies acquisition bytes; the original article text is not retained or independently rehashed here.")
    sources = []
    for key, title, url, sections in (
        ("aaos_common_knee_injuries_review", "Common Knee Injuries", "https://www.orthoinfo.org/diseases--conditions/common-knee-injuries/", "Common Knee Injuries, Fractures, Dislocation"),
        ("aaos_acl_education_review", "Anterior Cruciate Ligament (ACL) Injuries", "https://www.orthoinfo.org/diseases--conditions/anterior-cruciate-ligament-acl-injuries/", "Symptoms of an ACL Tear; Physical Examination and Patient History"),
    ):
        sources.append(SourceEntry(source_key=key, verified_at="2026-10-26", access_level="full_text",
            source=KnowledgeSourceCreate(source_type="other", title=title, publisher="AAOS OrthoInfo", url=url,
                citation="AAOS OrthoInfo. " + title + ". Relevant sections read directly: " + sections + ". Publication date independently unverified.",
                publication_date=None, guideline_version="Official educational webpage; dated edition not displayed", accessed_at="2026-10-26"),
            verification_note="Relevant original English text directly reviewed. Educational source, not a validated software diagnostic rule; article date and original document byte hash are not independently verified."))
    definitions = (
        (COMBINED, "Knee injury can involve multiple structures",
         "A knee injury can involve more than one anatomical structure.", sources[0]),
        (INSTABILITY, "Giving-way as an ACL assessment context",
         "A feeling that the knee gives way can occur in anterior cruciate ligament injury.", sources[1]),
    )
    proposals = []
    for key, title, statement, source in definitions:
        fact = KnowledgeFactCreate(fact_key=key, title=title, statement=statement,
            clinical_domain="orthopedics_knee", population="People presenting to a clinician with a knee injury or reported instability.",
            indication="Draft context for a physician's differential review. History alone does not identify or exclude a particular damaged structure, grade severity or indicate surgery. Independent clinical review remains required.",
            evidence_grade="ungraded", sources=[source.source])
        proposals.append(AssessmentDraftProposal(fact=fact, content_sha256=knowledge_content_digest(fact_key=key, version=1, content=fact)))
    return organizing, tuple(sources), tuple(proposals)


def build_knee_pain_injury_review(request: KneeWorkbenchRequest | dict, *, source_snapshot: dict | None = None) -> KneePainInjuryReview:
    request = KneeWorkbenchRequest.model_validate(request.model_dump(mode="json") if isinstance(request, KneeWorkbenchRequest) else request)
    snapshot = load_organizing_source_snapshot(source_snapshot)
    organizing, additional_sources, proposals = _evidence(snapshot)
    workbench = build_knee_workbench(request)
    pack = load_knee_pack()
    hashes = {row.fact.fact_key: row.content_sha256 for row in pack.facts}
    hashes.update({row.fact.fact_key: row.content_sha256 for row in (*workbench.new_draft_proposals, *proposals)})
    # Use the workbench's resolved usability, including cross-channel alias
    # quarantine. Replacing a duplicate representation never resolves sources.
    rows = {}
    problem = workbench.baseline_review.problem_representation
    for row in (*problem.history, *problem.examination, *problem.imaging):
        rows[(row.field, row.source_ref)] = WorkbenchObservation(
            **row.model_dump(include={"field", "value", "value_fa", "state", "provenance", "source_ref", "usability", "reason"}))
    for row in (*workbench.supplemental_observations, *workbench.quarantined_observations):
        rows[(row.field, row.source_ref)] = row
    actual = tuple(rows.values())
    effective = {row.field: row for row in actual if row.usability == "usable"}
    def value(field):
        return effective[field].value if field in effective else None
    def selections(single):
        val = value(ALIASES.get(single, single))
        if val is None: val = value(single)
        return val if type(val) is tuple else () if val is None else (val,)
    def state(known, present):
        return "information_missing" if not known else "context_present" if present else "context_not_reported"
    locking, chief = value("mechanical_locking"), value("chief_complaint")
    location, activities = selections("pain_location"), selections("aggravating_factor")
    neuro_fields = ("sensory_change", "weakness", "foot_coldness", "foot_color_change")
    hot_fields = ("fever", "acute_swelling", "systemic_symptoms")
    # These literal content dimensions group known reports. They are neither
    # mutually exclusive diagnoses nor a new general model-execution language.
    definitions = (
        ("temporal_course", "زمان‌بندی شروع و تداوم", ("onset", "duration", "pain_score_now"),
         state(value("onset") is not None and value("duration") is not None, True),
         "شروع، مدت و شدت جدا گزارش می‌شوند؛ شروع ناگهانی می‌تواند با تداوم سال‌ها همراه باشد و از آن شدت یا تشخیص نتیجه نمی‌شود.",
         "زمان‌بندی درد؛ نمای متنی بازبینی‌شده سطرهای ۶۳–۷۱", ("oa", "pfp", "meniscus", "cartilage"), ("KNEE.OA.PRESENTATION", "KNEE.MENISCUS.SCOPE")),
        ("trauma_context", "زمینهٔ آسیب و مکانیسم", ("trauma", "trauma_mechanism", *neuro_fields),
         state(value("trauma") is not None, value("trauma") is True),
         "سابقه و مکانیسم ثبت‌شده زمینهٔ بررسی هم‌زمان ساختارها هستند؛ آسیب منفرد، پارگی خاص یا شدت آسیب از آن‌ها احراز نمی‌شود.",
         "آسیب مستقیم و غیرمستقیم؛ نمای متنی سطرهای ۸۰–۱۰۵", ("meniscus", "cartilage"), (COMBINED, "KNEE.SAFETY.NEUROVASCULAR_TRAUMA")),
        ("mechanical_symptoms", "گیرکردن و احساس ناپایداری", ("mechanical_locking", "pain_limited_motion", "chief_complaint", "exam_range_of_motion"),
         state(locking is not None or chief == "instability", locking is True or chief == "instability"),
         "گیرکردن، توقف به‌علت درد و انتخاب ناپایداری به‌عنوان شکایت اصلی جدا حفظ می‌شوند؛ انتخاب شکایت دیگری، نبود ناپایداری را اثبات نمی‌کند.",
         "نشانه‌های مکانیکی؛ نمای متنی سطرهای ۹۱–۱۰۱ و ۱۴۷–۱۵۰", ("meniscus", "cartilage"), ("KNEE.MENISCUS.MOTION_BLOCK", INSTABILITY)),
        ("anterior_loaded_pain", "محل قدامی و فعالیت تشدیدکننده", ("has_pain", "pain_location", "pain_locations", "aggravating_factor", "aggravating_activities", "exam_squat_anterior_pain"),
         state(bool(location) and bool(activities), "anterior" in location and bool({"stairs", "loaded_flexion"}.intersection(activities))),
         "همهٔ محل‌ها و فعالیت‌ها حفظ می‌شوند؛ درد قدامی یا درد پله، کندرومالاسی یا آسیب غضروف را اثبات نمی‌کند.",
         "درد قدامی؛ نمای متنی سطرهای ۱۱۹–۱۲۱ و ۱۷۸–۱۸۱", ("pfp", "oa"), ("KNEE.WORKBENCH.PFP.SQUAT",)),
        ("persistent_load_related", "تداوم علائم و ارتباط با فعالیت", ("has_pain", "onset", "duration", "pain_pattern", "age_band", "morning_stiffness"),
         state(value("duration") is not None and value("pain_pattern") is not None,
               value("duration") in {"months", "years"} and value("pain_pattern") == "activity"),
         "تداوم و الگوی درد زمینهٔ مقایسه‌اند؛ فنوتیپ OA در دفتر اصلی به سن و خشکی نیز وابسته است و سابقهٔ آسیب آن را خودکار رد نمی‌کند.",
         "درد پایدار و تغییرات مفصلی؛ نمای متنی سطرهای ۱۷۶–۱۸۳", ("oa", "meniscus"), ("KNEE.WORKBENCH.OA.PHENOTYPE",)),
        ("inflammatory_and_risk", "اطلاعات التهاب و خطر", (*hot_fields, *neuro_fields, "morning_stiffness", "exam_effusion"),
         state(any(value(field) is True for field in hot_fields) or value("morning_stiffness") == "over_30_min" or value("exam_effusion") is True
               or all(value(field) is not None for field in hot_fields),
               any(value(field) is True for field in hot_fields) or value("morning_stiffness") == "over_30_min" or value("exam_effusion") is True),
         "یافته‌های قابل‌استفاده و گزارش‌های خطرِ کنارگذاشته‌شده جدا هستند؛ نبود تب عفونت را رد نمی‌کند و افیوژن تشخیص اختصاصی نیست.",
         "زمینهٔ عفونت و التهاب؛ نمای متنی سطرهای ۱۱۰–۱۱۵ و ۱۵۳–۱۶۳", (), ("KNEE.SAFETY.HOT_JOINT", "KNEE.SAFETY.SEPSIS", "KNEE.SAFETY.NEUROVASCULAR_TRAUMA", "KNEE.WORKBENCH.OA.PROLONGED_STIFFNESS")),
        ("structural_findings", "یافته‌های مستند ساختاری", ("imaging_meniscal_lesion", "imaging_cartilage_lesion", "imaging_kl_grade"),
         state(any(value(field) is not None for field in ("imaging_meniscal_lesion", "imaging_cartilage_lesion", "imaging_kl_grade")), True),
         "گزارش مثبت یا منفی تصویرِ بررسی‌شده به‌عنوان اطلاعات مستند حفظ می‌شود؛ سایر ساختارها از یک گزارش عادی فرض نمی‌شوند و این داده علت درد، ضرورت جراحی یا شدت ناتوانی نیست.",
         "ساختارهای مفصلی و یافته‌های تصویر؛ نمای متنی سطرهای ۵۳–۶۰ و ۱۷۹–۱۸۳", ("meniscus", "cartilage", "oa"), ("KNEE.MENISCUS.SCOPE", "KNEE.CARTILAGE.HISTORY_EXAM", "KNEE.OA.KL_CONTEXT")),
        ("postoperative_and_uncovered", "سابقهٔ جراحی و حوزه‌های بررسی‌نشده", ("prior_surgery", "surgery_description", "functional_limitation"),
         state(value("prior_surgery") is not None, value("prior_surgery") is True),
         "توقف بررسی معمول پس از جراحی مطابق موتور موجود حفظ می‌شود؛ از متن آزاد، وجود پروتز، عفونت یا نوع جراحی استنباط نمی‌شود.",
         "زمینهٔ جراحی قبلی و پوشش افتراق؛ نمای متنی سطرهای ۲۱۹–۲۳۲", (), ("KNEE.CARTILAGE.HISTORY_EXAM",)),
    )
    routes = []
    for id, label, fields, status, interpretation, locator, comparisons, keys in definitions:
        linked_fields = set(fields) | {ALIASES[field] for field in fields if field in ALIASES}
        safety_keys = {"KNEE.SAFETY.HOT_JOINT", "KNEE.SAFETY.SEPSIS", "KNEE.SAFETY.NEUROVASCULAR_TRAUMA"}
        links = tuple(item for item in workbench.next_items if item.field in linked_fields
                      or id == "inflammatory_and_risk" and item.field is None and item.category == "physician_review"
                      and item.priority == "workflow_first" and safety_keys.intersection(item.source_fact_keys))
        routes.append(PainInjuryRoute(id=id, label_fa=label, status=status,
            interpretation_fa=interpretation, article_section_locator=locator,
            observations=tuple(row for row in actual if row.field in fields),
            differential_comparison_ids=comparisons, source_fact_keys=keys,
            source_content_sha256s=tuple(hashes[key] for key in keys), question_links=links,
            limitations_fa=("این محور سازمان‌دهی شرح‌حال است؛ وضعیت آن احتمال، تشخیص یا رد بیماری نیست.",
                            "محدودیت دامنه، تناقض و توقف‌های بررسی پزشک در دفتر اصلی معتبر می‌مانند.")))
    gaps = tuple(PainInjuryCoverageGap(id=id, label_fa=label, reason_fa=reason) for id, label, reason in (
        ("ligament", "آسیب رباطی", "حس ناپایداری زمینهٔ بررسی پزشک است؛ معاینات اختصاصی و مدل افتراقی رباط در چهار مقایسهٔ موجود پیاده نشده‌اند."),
        ("fracture_dislocation", "شکستگی و دررفتگی", "این حوزه‌ها از شرح‌حال تنها ارزیابی یا رد نمی‌شوند؛ نیاز به ارزیابی پزشک دارند و مدل اختصاصی این نما نیستند."),
        ("inflammatory", "بیماری التهابی یا عفونت", "اطلاعات خطر و خشکی طولانی حفظ می‌شوند؛ تشخیص اختصاصی پیاده نشده است. منبع SANJO مربوط به مفصل طبیعی است و به پروتز تعمیم خودکار ندارد."),
        ("periarticular", "بافت‌های اطراف مفصل", "منطق اختصاصی افتراق تاندون، بورس و سایر علل اطراف مفصل پیاده نشده است؛ این شکاف به معنی نبود بیماری نیست."),
        ("biomechanical", "زمینهٔ بیومکانیک", "قدرت عضله، راستای اندام و وضعیت وزن در این ورودی احراز نشده‌اند؛ ضعف یا اضافه‌وزن از درد و عملکرد استنباط نمی‌شود."),
    ))
    source_map = {row.source_key: row for row in (*pack.sources, *workbench.source_references, *additional_sources, organizing)}
    sources = tuple(source_map[key] for key in sorted(source_map))
    source_hash = content_digest({"sources": [row.model_dump(mode="json") for row in sources], "fact_hashes": hashes,
                                  "snapshot_metadata_sha256": snapshot["metadata_sha256"]})
    rules_hash = content_digest({"version": VERSION, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(Path(review_schema.__file__).read_bytes()).hexdigest(),
        "source_set_sha256": source_hash, "workbench_rules_sha256": workbench.rules_sha256,
        "route_ids": [row.id for row in routes], "source_role": "primary_organizing_source;medical_claims_require_separate_source_review"})
    result = KneePainInjuryReview(workbench=workbench, organizing_source=organizing,
        source_document_sha256=snapshot["source_document_sha256"], source_snapshot_metadata_sha256=snapshot["metadata_sha256"],
        routes=tuple(routes), coverage_gaps=gaps,
        raw_risk_observations=tuple(row for row in actual if row.field in RISK_FIELDS and row.value is True),
        routine_evaluation_withheld=workbench.routine_evaluation_withheld, source_references=sources, new_draft_proposals=proposals,
        limitations_fa=("مقالهٔ زتامد ستون اصلی سازمان‌دهی نوع درد و زمینهٔ آسیب است؛ وزن تشخیصی یا تأیید خودکارِ ادعاهای پزشکی آن نیست.",
                        "طبقه‌بندی‌ها هم‌پوشانی دارند و شدت درد، علت ساختاری یا طرح درمان را تعیین نمی‌کنند.",
                        "این نما مستقل از موتور ایمنی عملیاتی و فاقد اعتبارسنجی مستقل بالینی است؛ نبود هشدار تأیید ایمنی نیست."),
        request_sha256=content_digest(request.model_dump(mode="json")), rules_sha256=rules_hash,
        source_set_sha256=source_hash, result_sha256="0" * 64)
    return result.model_copy(update={"result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))})
