"""Source-bound Draft clinical content for an additive knee workbench.

No general decision runner, language model, diagnostic probability, patient
store or safety-rule activation is introduced. Existing answer resolution and
assessment guards remain the source of workflow constraints.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from backend.app.schemas import orthopedic_workbench as workbench_schema
from backend.app.schemas.medical_knowledge import KnowledgeFactCreate, KnowledgeSourceCreate
from backend.app.schemas.orthopedic_assessment import AssessmentDraftProposal
from backend.app.schemas.orthopedic_knowledge import SourceEntry, content_digest
from backend.app.schemas.orthopedic_workbench import (
    SUPPLEMENTAL_CHOICES, DifferentialComparison, KneeWorkbench, KneeWorkbenchRequest,
    ManagementContextReview, WorkbenchNextItem, WorkbenchObservation,
    WorkbenchQuestion, WorkbenchRelationship, WorkbenchWorkflowEquivalence,
)
from backend.app.services.medical_knowledge import knowledge_content_digest
from backend.app.services.orthopedic_assessment import export_offline_assessment
from backend.app.services.orthopedic_interview_tree import build_interview_tree, build_interview_tree_preview
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_questions import _effective_answers
from backend.app.services.orthopedic_reasoning_review import _display, build_knee_reasoning_review


VERSION = "1.0.0"
OA = "KNEE.WORKBENCH.OA.PHENOTYPE"
STIFFNESS = "KNEE.WORKBENCH.OA.PROLONGED_STIFFNESS"
PFP = "KNEE.WORKBENCH.PFP.SQUAT"
JLT = "KNEE.WORKBENCH.MENISCUS.JOINT_LINE"
MCMURRAY = "KNEE.WORKBENCH.MENISCUS.MCMURRAY"
CARTILAGE = "KNEE.CARTILAGE.HISTORY_EXAM"
MENISCUS = "KNEE.MENISCUS.SCOPE"
ALIASES = {"pain_location": "pain_locations", "aggravating_factor": "aggravating_activities", "care_goal": "care_goals"}
EXTRA_LABELS = {
    "age_band": "گروه سنی", "morning_stiffness": "مدت خشکی صبحگاهی",
    "exam_squat_anterior_pain": "بازآفرینی درد آشنای قدام زانو در اسکواتِ معاینه",
    "exam_mcmurray": "یافتهٔ آزمون مک‌موری در معاینه",
    "pain_locations": "همهٔ محل‌های گزارش‌شدهٔ درد", "aggravating_activities": "همهٔ فعالیت‌های تشدیدکننده",
    "care_goals": "هدف‌های مراجعه",
}
EXTRA_VALUES = {
    "under_45": "کمتر از ۴۵ سال", "45_or_over": "۴۵ سال یا بیشتر", "none": "وجود ندارد",
    "up_to_30_min": "حداکثر ۳۰ دقیقه", "over_30_min": "بیش از ۳۰ دقیقه",
    "positive": "مثبت", "negative": "منفی", "indeterminate": "نامعین",
}


def workbench_questions() -> dict[str, WorkbenchQuestion]:
    """Versioned authoring definitions; do not modify the shared bank contract."""
    result = {
        node.field: WorkbenchQuestion(
            id=node.question.id, field=node.field, text_fa=node.question.text_fa,
            purpose_fa=node.question.purpose_fa, answer_type=node.question.answer_type,
            choices=tuple(node.question.choices), channel="patient_report",
        ) for node in build_interview_tree().nodes
    }
    result["has_pain"] = WorkbenchQuestion(
        id="knee.workbench.has_pain", field="has_pain", text_fa="آیا در دورهٔ این مشکل زانو درد داشته‌اید؟",
        purpose_fa="تعیین شاخهٔ شرح‌حال درد بدون برداشت از شدت درد همین لحظه.",
        answer_type="yes_no", channel="patient_report",
    )
    texts = {
        "age_band": "سن شما کمتر از ۴۵ سال است یا ۴۵ سال و بیشتر؟",
        "morning_stiffness": "خشکی زانو پس از بیدارشدن صبح معمولاً چقدر طول می‌کشد؟",
        "exam_squat_anterior_pain": "آیا در معاینهٔ اسکوات، درد آشنای قدام زانو بازآفرینی شد؟",
        "exam_mcmurray": "نتیجهٔ آزمون مک‌موری در معاینه چه بود؟",
        "pain_locations": "درد را در کدام قسمت‌های زانو احساس می‌کنید؟ همهٔ موارد مربوط را انتخاب کنید.",
        "aggravating_activities": "کدام فعالیت‌ها علائم زانو را بیشتر می‌کنند؟ همهٔ موارد مربوط را انتخاب کنید.",
        "care_goals": "از این مراجعه چه هدف‌هایی دارید؟ همهٔ موارد مربوط را انتخاب کنید.",
    }
    for field, text in texts.items():
        result[field] = WorkbenchQuestion(
            id="knee.workbench." + field, field=field, text_fa=text,
            purpose_fa="رفع ابهام برای مقایسهٔ شواهد توسط پزشک؛ محتوای پیش‌نویس نیازمند بازبینی مستقل است.",
            answer_type="yes_no" if field == "exam_squat_anterior_pain" else
                        "multi_choice" if field in ALIASES.values() else "single_choice",
            choices=SUPPLEMENTAL_CHOICES.get(field, ()),
            channel="physician_exam" if field.startswith("exam_") else "patient_report",
        )
    for field, text, choices in (
        ("exam_joint_line_tenderness", "آیا در معاینه حساسیت خط مفصلی وجود داشت؟", ()),
        ("exam_effusion", "آیا در معاینه افیوژن وجود داشت؟", ()),
        ("exam_range_of_motion", "دامنهٔ حرکت در معاینه چگونه بود؟", ("full", "restricted", "unclear")),
    ):
        result[field] = WorkbenchQuestion(id="knee.workbench." + field, field=field, text_fa=text,
            purpose_fa="ثبت جداگانهٔ یافتهٔ معاینهٔ پزشک؛ بیمار این کانال را تکمیل نمی‌کند.",
            answer_type="single_choice" if choices else "yes_no", choices=choices, channel="physician_exam")
    return result


def _draft_evidence():
    sources = (
        SourceEntry(source_key="nice_ng226_workbench", verified_at="2026-10-26", access_level="indexed_recommendations",
            source=KnowledgeSourceCreate(source_type="guideline", title="Osteoarthritis in over 16s: diagnosis and management (NG226)",
                citation="NICE NG226. Recommendations 1.1.1–1.1.2 and atypical-features definition. Published 19 October 2022; official indexed recommendations checked 26 October 2026. Direct page returned HTTP 403.",
                publisher="NICE", url="https://www.nice.org.uk/guidance/ng226/chapter/Recommendations", publication_date="2022-10-19",
                guideline_version="NG226, recommendations 1.1.1–1.1.2", accessed_at="2026-10-26"),
            verification_note="Official indexed recommendations checked; direct source access was denied (403). No full-source or byte-hash verification is claimed."),
        SourceEntry(source_key="jospt_pfp_workbench", verified_at="2026-10-26", access_level="indexed_recommendations",
            source=KnowledgeSourceCreate(source_type="guideline", title="Patellofemoral Pain: Clinical Practice Guidelines",
                citation="Willy RW et al. J Orthop Sports Phys Ther. 2019;49(9):CPG1–CPG95. Diagnosis recommendation: retropatellar/peripatellar pain, reproduction during squat or other loaded flexion, exclusion of other anterior-knee causes. Publisher indexed recommendation checked; direct page 403.",
                publisher="JOSPT", url="https://www.jospt.org/doi/10.2519/jospt.2019.0302", doi="10.2519/jospt.2019.0302",
                publication_date="2019-08-31", guideline_version="2019, Diagnosis recommendation", accessed_at="2026-10-26"),
            verification_note="Publisher indexed recommendation checked; direct full text was denied (403). General anterior pain is less specific than retropatellar/peripatellar pain; no complete criteria or accuracy assessment is claimed."),
        SourceEntry(source_key="aaos_meniscus_workbench", verified_at="2026-10-26", access_level="full_text",
            source=KnowledgeSourceCreate(source_type="guideline", title="Management of Acute Isolated Meniscal Pathology",
                citation="AAOS. Management of Acute Isolated Meniscal Pathology. Published 10 June 2024. Physical Examination recommendation and rationale, PDF pp. 6–8,18–19. Moderate recommendation; heterogeneous diagnostic accuracy.",
                publisher="AAOS", url="https://www.aaos.org/globalassets/quality-and-practice-resources/acute-meniscal-pathology/amp-cpg.pdf",
                publication_date="2024-06-10", guideline_version="2024, Physical Examination recommendation", accessed_at="2026-10-26"),
            verification_note="Official PDF relevant summary/physical-examination pages read. Scope excludes chronic/degenerative lesions, re-tears, root tears and concomitant ACL/fracture/chondral pathology; trauma alone does not establish applicability. PDF byte hash not computed."),
    )
    by_source = {entry.source_key: entry for entry in sources}
    definitions = (
        (OA, "Clinical OA phenotype for review", "NICE NG226 describes a clinical osteoarthritis diagnostic phenotype in people aged 45 or over who have activity-related joint pain and no morning joint stiffness or stiffness lasting no longer than 30 minutes.",
         "People aged 45 or over undergoing clinician assessment of joint symptoms.", "nice_ng226_workbench",
         "All three features must be considered together; the workbench is not an independently validated diagnostic implementation and other causes remain for clinician assessment."),
        (STIFFNESS, "Prolonged morning stiffness requires broader assessment", "NICE NG226 lists prolonged morning joint stiffness as an atypical feature requiring consideration of alternative or additional diagnoses during osteoarthritis assessment.",
         "People undergoing clinician assessment for suspected osteoarthritis.", "nice_ng226_workbench",
         "Stiffness lasting more than 30 minutes is not proof of rheumatoid arthritis or another particular diagnosis; no automatic imaging order follows."),
        (PFP, "Familiar anterior knee pain during squat", "The 2019 patellofemoral pain guideline includes reproduction of retropatellar or peripatellar pain during squatting or other loaded-flexion activities in the diagnostic assessment of patellofemoral pain.",
         "People undergoing clinician assessment for retropatellar or peripatellar knee pain.", "jospt_pfp_workbench",
         "Other causes of anterior knee pain require exclusion; the general anterior-location field does not establish exact retropatellar/peripatellar location, and a positive or negative squat finding alone does not establish or exclude a diagnosis."),
        (JLT, "Joint-line tenderness in acute isolated meniscal assessment", "The AAOS 2024 acute isolated meniscal pathology guideline includes joint-line tenderness as a potentially useful physical-examination finding in diagnosis within its specified clinical scope.",
         "People assessed by a clinician for acute isolated meniscal pathology within the AAOS guideline scope.", "aaos_meniscus_workbench",
         "Applicability is unconfirmed from trauma alone. Chronic/degenerative, re-tear, root-tear and concomitant ACL/fracture/chondral contexts are outside this source's scope; one negative examination does not exclude a meniscal disorder."),
        (MCMURRAY, "McMurray in acute isolated meniscal assessment", "The AAOS 2024 acute isolated meniscal pathology guideline includes the McMurray test as a potentially useful physical-examination assessment within its specified clinical scope.",
         "People assessed by a clinician for acute isolated meniscal pathology within the AAOS guideline scope.", "aaos_meniscus_workbench",
         "Diagnostic accuracy varies across included studies. Guideline scope is not established by trauma alone; a positive test is not proof and a single negative test cannot exclude a meniscal disorder."),
    )
    proposals = []
    for key, title, statement, population, source_key, limitation in definitions:
        fact = KnowledgeFactCreate(fact_key=key, title=title,
            statement=statement + "\n\nDraft workbench application and limits: " + limitation,
            clinical_domain="orthopedics_knee", population=population,
            indication="Source-bound Draft clinician comparison only; independent source and specialist review required. " + limitation,
            evidence_grade="ungraded", sources=[by_source[source_key].source])
        proposals.append(AssessmentDraftProposal(fact=fact, content_sha256=knowledge_content_digest(fact_key=key, version=1, content=fact)))
    return tuple(proposals), sources


def _relationships():
    """Clinical-content inventory, not a generic rule-execution language."""
    return {
        "version": VERSION,
        "oa": {"age_band": OA, "pain_pattern": OA, "morning_stiffness": (OA, STIFFNESS)},
        "pfp": {"pain_locations": PFP, "aggravating_activities": PFP, "exam_squat_anterior_pain": PFP},
        "meniscus": {"trauma": MENISCUS, "trauma_mechanism": MENISCUS,
                     "exam_joint_line_tenderness": JLT, "exam_mcmurray": MCMURRAY, "imaging_meniscal_lesion": MENISCUS},
        "cartilage": {"imaging_cartilage_lesion": CARTILAGE, "exam_effusion": CARTILAGE, "exam_range_of_motion": CARTILAGE},
    }


def build_knee_workbench(request: KneeWorkbenchRequest | dict) -> KneeWorkbench:
    request = KneeWorkbenchRequest.model_validate(request.model_dump(mode="json") if isinstance(request, KneeWorkbenchRequest) else request)
    preview = build_interview_tree_preview(request.interview)
    baseline = build_knee_reasoning_review(request.interview)
    questions = workbench_questions()
    proposals, new_sources = _draft_evidence()
    pack = load_knee_pack()
    hashes = {fact.fact.fact_key: fact.content_sha256 for fact in pack.facts}
    hashes.update({entry.fact.fact_key: entry.content_sha256 for entry in proposals})
    # Resolve multiple-choice answers as sets without changing any retained
    # source record or treating selection order as clinical importance.
    resolution_rows = tuple(item.model_copy(update={"value": tuple(sorted(item.value))})
                            if type(item.value) is tuple else item for item in request.supplemental_observations)
    _, effective_extra, extra_reasons = _effective_answers(SimpleNamespace(observations=resolution_rows))
    base_rows = [WorkbenchObservation(field=row.field, value=row.value, value_fa=row.value_fa,
                  state=row.state, provenance=row.provenance, source_ref=row.source_ref,
                  usability=row.usability, reason=row.reason)
                 for row in (*baseline.problem_representation.history, *baseline.problem_representation.examination,
                             *baseline.problem_representation.imaging, *baseline.quarantined_observations)]
    def show(item):
        if item.state == "unknown": return "نمی‌دانم"
        if item.state == "declined": return "مایل به پاسخ نیستم"
        if item.value is None: return "پاسخ کامل ثبت نشده"
        if type(item.value) is tuple:
            single = next((field for field, multi in ALIASES.items() if multi == item.field), item.field)
            return "، ".join(_display(SimpleNamespace(field=single, state="confirmed", value=value)) for value in item.value)
        if item.field in EXTRA_VALUES or type(item.value) is str and item.value in EXTRA_VALUES:
            return EXTRA_VALUES.get(item.value, str(item.value))
        return _display(item)
    def usable_extra(item):
        resolved = effective_extra.get(item.field)
        comparable_value = tuple(sorted(item.value)) if type(item.value) is tuple else item.value
        return resolved is not None and item.state == "confirmed" and comparable_value == resolved.value
    extras = [WorkbenchObservation(field=item.field, value=item.value, value_fa=show(item), state=item.state,
              provenance=item.provenance, source_ref=item.source_ref,
              usability="usable" if usable_extra(item) else "quarantined",
              reason=None if usable_extra(item) else extra_reasons.get(item.field, item.state))
              for item in request.supplemental_observations]
    rows = [*base_rows, *extras]
    effective = {row.field: row for row in rows if row.usability == "usable"}
    alias_conflicts = []
    for single, multi in ALIASES.items():
        if single in effective and multi in effective and effective[single].value not in effective[multi].value:
            alias_conflicts.extend((single, multi))
    # A pain-location report also needs the explicit pain-presence routing fact.
    if "pain_locations" in effective and ("has_pain" not in effective or effective["has_pain"].value is not True):
        alias_conflicts.append("pain_locations")
        if "has_pain" in effective and effective["has_pain"].value is False:
            alias_conflicts.append("has_pain")
    if "aggravating_activities" in effective and ("has_pain" not in effective or effective["has_pain"].value is not True):
        neutral = effective["aggravating_activities"].value == ("none",)
        if "has_pain" not in effective or not neutral:
            alias_conflicts.append("aggravating_activities")
            if "has_pain" in effective and effective["has_pain"].value is False:
                alias_conflicts.append("has_pain")
    alias_conflicts = set(alias_conflicts)
    rows = [row.model_copy(update={"usability": "quarantined", "reason": "contradictory" if "has_pain" in effective else "incomplete"})
            if row.field in alias_conflicts else row for row in rows]
    effective = {row.field: row for row in rows if row.usability == "usable"}
    extras = tuple(row for row in rows if row.field in questions and row.field in EXTRA_LABELS)
    quarantined = tuple(row for row in rows if row.usability == "quarantined")
    def get(field):
        single = next((key for key, multi in ALIASES.items() if multi == field), None)
        return effective.get(field) or effective.get(single)
    def value(field):
        item = get(field)
        return item.value if item else None
    def selections(field):
        val = value(field)
        return val if type(val) is tuple else (val,) if val is not None else ()
    def observed(field):
        single = next((key for key, multi in ALIASES.items() if multi == field), None)
        return tuple(row for row in rows if row.field in {field, single})

    # Re-evaluate the existing guards without changing their rules. Only a
    # missing single pain-location axis has a declared multi-choice equivalent;
    # no risk, uncertainty, surgery or dependency prerequisite is waived.
    model = export_offline_assessment()
    guard_outcomes = []
    equivalences = []
    for guard in model["guard_tables"]:
        outcome = guard["rows"]["|".join(baseline.baseline_assessment.axis_tokens[axis] for axis in guard["axis_ids"])]
        if outcome["status"] == "ready": continue
        base_location_missing = not any(item.field == "pain_location" for item in request.interview.context.observations)
        if (guard["id"] == "core:pain_location" and base_location_missing
                and get("pain_locations") is not None and "pain_location" not in alias_conflicts):
            equivalences.append(WorkbenchWorkflowEquivalence(guard_id="core:pain_location",
                source_refs=tuple(row.source_ref for row in observed("pain_locations") if row.usability == "usable"),
                explanation_fa="در نمای چندگزینه‌ای، محل‌های قابل‌استفادهٔ درد، شکاف ثبت محل را پوشش می‌دهند؛ هیچ محل منفردی ساخته نشده و وضعیت نمای پایه تغییر نکرده است."))
            continue
        guard_outcomes.append((guard, outcome))
    priorities = {"outside_scope": 100, "prompt_physician_review": 90, "side_specific_review": 80, "insufficient_information": 60}
    status = max((outcome["status"] for _, outcome in guard_outcomes), key=lambda candidate: priorities[candidate], default="differential_review")
    if alias_conflicts and status == "differential_review": status = "insufficient_information"
    withheld = status != "differential_review"
    next_items = []
    seen_next = set()
    def add_next(field, category, action, reason, comparisons=(), keys=(), priority="discriminating_information", episode_ref=None):
        token = (field, category, episode_ref)
        if token in seen_next: return
        seen_next.add(token)
        next_items.append(WorkbenchNextItem(id="knee.workbench.next." + (field or category) + ("." + episode_ref if episode_ref else ""),
            field=field, episode_ref=episode_ref, category=category, action=action,
            question=questions.get(field) if category in {"patient_question", "clinician_exam"} else None,
            reason_fa=reason, addresses_comparison_ids=tuple(comparisons), source_fact_keys=tuple(keys),
            source_content_sha256s=tuple(hashes[key] for key in keys), priority=priority))

    # First expose actual unresolved workflow questions. Clarification belongs
    # to the physician; unknown/declined answers are retained without looping.
    workflow_fields = {axis["field"] for guard, _ in guard_outcomes for axis in model["axes"] if axis["id"] in guard["axis_ids"]}
    candidates = {(item.field, item.episode_ref): item for item in preview.question_candidates}
    for item in baseline.next_data_requirements:
        if item.category != "workflow_prerequisite" or item.field is None: continue
        if item.field not in workflow_fields: continue
        field = (item.field if item.question_action in {"not_automatically_reask", "physician_clarification"}
                 else ALIASES.get(item.field, item.field))
        if get(field) is not None: continue
        extra_reason = extra_reasons.get(field)
        if extra_reason in {"unknown", "declined"}:
            add_next(field, "physician_review", "not_automatically_reask",
                     "پاسخ چندگزینه‌ای نامعلوم یا انصراف ثبت شده است؛ شکاف باقی است ولی سؤال خودکار تکرار نمی‌شود.",
                     keys=item.source_fact_keys, priority="workflow_first")
            continue
        if extra_reason:
            add_next(field, "physician_review", "physician_clarification",
                     "گزارش چندگزینه‌ای موجود نیازمند روشن‌سازی پزشک است؛ پاسخ قبلی حفظ می‌شود.",
                     keys=item.source_fact_keys, priority="workflow_first")
            continue
        if item.question_action == "not_automatically_reask":
            add_next(field, "physician_review", "not_automatically_reask", item.reason_fa, keys=item.source_fact_keys, priority="workflow_first")
        else:
            action = "physician_clarification" if item.question_action == "physician_clarification" else "ask_missing"
            add_next(field, "physician_review" if action == "physician_clarification" else "patient_question", action,
                     item.reason_fa, keys=item.source_fact_keys, priority="workflow_first")
    for field in sorted(alias_conflicts):
        add_next(field, "physician_review", "physician_clarification", "پاسخ‌های یک‌گزینه‌ای، چندگزینه‌ای یا شاخهٔ وجود درد با هم سازگار نیستند؛ همهٔ گزارش‌ها حفظ شده‌اند و انتخابی خودکار جایگزین آن‌ها نمی‌شود.", priority="clarification")
    if status == "prompt_physician_review":
        keys = tuple(dict.fromkeys(key for guard, outcome in guard_outcomes
                                  if outcome["status"] == "prompt_physician_review" for key in outcome["source_fact_keys"]))
        add_next(None, "physician_review", "review_existing",
                 "اطلاعات خطر گزارش‌شده نیازمند بررسی زودهنگام پزشک است؛ ادامهٔ مقایسهٔ معمول یا تکمیل سؤال‌ها تأیید ایمنی نیست.",
                 keys=keys, priority="workflow_first")
    elif status not in {"outside_scope", "side_specific_review"} and get("chief_complaint") is None:
        raw_chief = observed("chief_complaint")
        if not raw_chief:
            add_next("chief_complaint", "patient_question", "ask_missing",
                     "شکایت اصلی هنوز ثبت نشده است؛ پیش از جزئیات، مشکل اصلی بیمار روشن شود.",
                     keys=("KNEE.OA.PRESENTATION",), priority="workflow_first")

    relationships = {"oa": [], "pfp": [], "meniscus": [], "cartilage": []}
    def relation(comp, field, code, explanation, keys):
        keys = (keys,) if type(keys) is str else tuple(keys)
        relationships[comp].append(WorkbenchRelationship(id="knee.workbench." + comp + "." + field,
            field=field, relation=code if get(field) is not None else "unavailable",
            explanation_fa=explanation if get(field) is not None else "دادهٔ قابل‌استفاده برای «" + EXTRA_LABELS.get(field, field) + "» ثبت نشده است؛ فقدان داده پاسخ منفی نیست.",
            observations=observed(field), source_fact_keys=keys, source_content_sha256s=tuple(hashes[key] for key in keys)))
    relation("oa", "age_band", "supports" if value("age_band") == "45_or_over" else "discordant",
             "گروه سنی ثبت‌شده: " + (get("age_band").value_fa if get("age_band") else "نامعلوم") + "؛ کمتر از ۴۵ سال بودن فقط با فنوتیپ سادهٔ این راهنما تطبیق ندارد و آرتروز را رد نمی‌کند.", OA)
    relation("oa", "pain_pattern", "supports" if value("pain_pattern") == "activity" else "neutral",
             "الگوی ثبت‌شدهٔ درد: " + (get("pain_pattern").value_fa if get("pain_pattern") else "نامعلوم") + "؛ درد هنگام فعالیت بخشی از فنوتیپ راهنماست و سایر الگوها نیازمند تفسیر پزشک‌اند.", OA)
    relation("oa", "morning_stiffness", "supports" if value("morning_stiffness") in {"none", "up_to_30_min"} else "discordant",
             "خشکی صبحگاهی: " + (get("morning_stiffness").value_fa if get("morning_stiffness") else "نامعلوم") + "؛ خشکی طولانی‌تر زمینهٔ بررسی علت‌های دیگر است و تشخیص مشخصی را اثبات نمی‌کند.", (OA, STIFFNESS))
    relation("pfp", "pain_locations", "supports" if "anterior" in selections("pain_locations") else "discordant",
             "محل‌های درد ثبت‌شده: " + (get("pain_locations").value_fa if get("pain_locations") else "نامعلوم") + "؛ قدامی بودن با این زمینه سازگار است، ولی محل دقیق دور یا پشت کشکک از پاسخ کلی تعیین نمی‌شود.", PFP)
    relation("pfp", "aggravating_activities", "supports" if {"stairs", "loaded_flexion"}.intersection(selections("aggravating_activities")) else "neutral",
             "فعالیت‌های تشدیدکننده: " + (get("aggravating_activities").value_fa if get("aggravating_activities") else "نامعلوم") + "؛ پله یا خم‌کردن زیر بار زمینهٔ بررسی درد پاتلوفمورال است؛ هیچ انتخابی حذف نشده است.", PFP)
    relation("pfp", "exam_squat_anterior_pain", "supports" if value("exam_squat_anterior_pain") is True else "discordant",
             "بازآفرینی درد آشنا در معاینه: " + (get("exam_squat_anterior_pain").value_fa if get("exam_squat_anterior_pain") else "نامعلوم") + "؛ این یافته به‌تنهایی تشخیص را اثبات یا رد نمی‌کند و منع یا احتیاط انجام آزمون با پزشک است.", PFP)
    relation("meniscus", "trauma", "neutral", "سابقهٔ آسیب ثبت‌شده است؛ آسیب به‌تنهایی نوع پارگی یا انطباق با دامنهٔ ضایعهٔ حاد و منفرد را تعیین نمی‌کند.", MENISCUS)
    relation("meniscus", "trauma_mechanism", "neutral", "مکانیسم ثبت‌شده باید در زمینهٔ بالینی تفسیر شود؛ چرخش ورزشی به‌تنهایی پارگی منیسک را اثبات نمی‌کند.", MENISCUS)
    acute_context = value("trauma") is True and value("duration") in {"days", "weeks"}
    relation("meniscus", "exam_joint_line_tenderness", "supports" if acute_context and value("exam_joint_line_tenderness") is True else "neutral",
             "حساسیت خط مفصلی: " + (get("exam_joint_line_tenderness").value_fa if get("exam_joint_line_tenderness") else "نامعلوم") + "؛ در زمینهٔ حادِ آسیب برای بررسی پزشک مفید است، اما دامنهٔ منفرد بودن هنوز اثبات نشده و نتیجهٔ منفی بیماری را رد نمی‌کند.", JLT)
    relation("meniscus", "exam_mcmurray", "supports" if acute_context and value("exam_mcmurray") == "positive" else "neutral",
             "مک‌موری: " + (get("exam_mcmurray").value_fa if get("exam_mcmurray") else "نامعلوم") + "؛ یک نتیجهٔ مثبت یا منفی به‌تنهایی تعیین‌کننده نیست؛ تفسیر راهنما فقط در دامنهٔ بالینی مناسب مطرح است.", MCMURRAY)
    relation("meniscus", "imaging_meniscal_lesion", "supports" if value("imaging_meniscal_lesion") is True else "neutral",
             "گزارش تصویر بررسی‌شدهٔ منیسک: " + (get("imaging_meniscal_lesion").value_fa if get("imaging_meniscal_lesion") else "نامعلوم") + "؛ یافتهٔ ساختاری به‌تنهایی علت درد، نوع ضایعه یا نیاز به جراحی را اثبات نمی‌کند.", MENISCUS)
    relation("cartilage", "imaging_cartilage_lesion", "supports" if value("imaging_cartilage_lesion") is True else "neutral",
             "گزارش تصویر بررسی‌شدهٔ غضروف: " + (get("imaging_cartilage_lesion").value_fa if get("imaging_cartilage_lesion") else "نامعلوم") + "؛ محل، درجه و تطبیق بالینی لازم‌اند؛ علت درد، OCD یا بازسازی غضروف استنباط نمی‌شود.", CARTILAGE)
    for field in ("exam_effusion", "exam_range_of_motion"):
        relation("cartilage", field, "neutral", "یافتهٔ معاینه ثبت و برای تفسیر پزشک حفظ شده است؛ افیوژن یا محدودیت حرکت اختصاصی ضایعهٔ غضروفی نیست.", CARTILAGE)

    # A finite, source-bound interview agenda: screening first, then actual
    # unresolved discriminators; no inferred information-gain score.
    relevant = {"oa": value("has_pain") is True,
                "pfp": value("has_pain") is True and "anterior" in selections("pain_locations"),
                "meniscus": value("trauma") is True or value("imaging_meniscal_lesion") is True,
                "cartilage": value("imaging_cartilage_lesion") is True}
    extras_needed = [("age_band", "oa", OA), ("morning_stiffness", "oa", OA),
                     ("aggravating_activities", "pfp", PFP), ("exam_squat_anterior_pain", "pfp", PFP),
                     ("exam_joint_line_tenderness", "meniscus", JLT), ("exam_mcmurray", "meniscus", MCMURRAY)]
    for field, comp, key in extras_needed:
        if not relevant[comp] or get(field) is not None: continue
        raw = observed(field)
        reason = next((row.reason for row in raw if row.usability == "quarantined"), None)
        if reason in {"unknown", "declined"}:
            add_next(field, "physician_review", "not_automatically_reask", "پاسخ نامعلوم یا انصراف حفظ شده است؛ تکرار خودکار سؤال انجام نمی‌شود.", (comp,), (key,))
        elif reason:
            add_next(field, "physician_review", "physician_clarification", "گزارش موجود کامل و سازگار نیست؛ روشن‌سازی پزشک پیش از استفاده لازم است.", (comp,), (key,), priority="clarification")
        elif status not in {"prompt_physician_review", "outside_scope", "side_specific_review"}:
            add_next(field, "clinician_exam" if field.startswith("exam_") else "patient_question",
                     "consider_examination" if field.startswith("exam_") else "ask_missing",
                     "این داده برای روشن‌شدن رابطهٔ «" + EXTRA_LABELS.get(field, field) + "» با مقایسهٔ فعلی ثبت نشده است؛ انتخاب و امکان معاینه با پزشک است.", (comp,), (key,))
    if not withheld:
        for candidate in preview.question_candidates:
            if candidate.field in {"pain_location", "aggravating_factor", "care_goal"}:
                field = ALIASES[candidate.field]
                if get(field) is not None: continue
            else: field = candidate.field
            if any(row.field == field and row.state in {"unknown", "declined"} for row in rows): continue
            add_next(field, "physician_review" if candidate.action == "physician_clarification" else "patient_question",
                     candidate.action, candidate.rationale_fa, keys=candidate.source_fact_keys, priority="context_review", episode_ref=candidate.episode_ref)
    if relevant["cartilage"]:
        add_next("imaging_cartilage_lesion", "imaging_review", "review_existing", "اگر تصویربرداری موجود است، پزشک محل و درجهٔ ضایعه و تناسب آن با علائم را بررسی کند؛ این مورد درخواست تصویر تازه نیست.", ("cartilage",), (CARTILAGE,), priority="context_review")
    if value("morning_stiffness") == "over_30_min":
        add_next("morning_stiffness", "physician_review", "review_existing", "خشکی صبحگاهی طولانی‌تر با فنوتیپ سادهٔ آرتروز تطبیق ندارد؛ علت‌های التهابی یا دیگر باید توسط پزشک بررسی شوند، بدون نسبت‌دادن تشخیص مشخص.", ("oa",), (STIFFNESS,), priority="clarification")
    if any(value(field) is not None for field in ("exam_effusion", "exam_range_of_motion", "imaging_kl_grade")):
        add_next(None, "physician_review", "review_existing", "افیوژن، دامنهٔ حرکت و درجهٔ KL در زمینهٔ بالینی تفسیر شوند؛ KL درجهٔ رادیوگرافیک است و با شدت درد یا ناتوانی یکی نیست.", priority="context_review")
    labels = {"oa": "آرتروز زانو", "pfp": "درد پاتلوفمورال", "meniscus": "اختلالات منیسک", "cartilage": "یافته‌های غضروفی و استئوکندرال"}
    limitations = {
        "oa": ("فنوتیپ راهنما جایگزین بررسی پزشک و تشخیص‌های دیگر نیست؛ جوان‌تر بودن یا سابقهٔ آسیب آرتروز را رد نمی‌کند.",),
        "pfp": ("محل عمومی قدام زانو جای محل دقیق دور یا پشت کشکک نیست؛ علت‌های دیگر درد قدام زانو بررسی نشده‌اند.",),
        "meniscus": ("راهنمای معاینه فقط ضایعات حاد و منفرد را پوشش می‌دهد؛ دامنهٔ ضایعات دژنراتیو، پارگی مجدد و آسیب همراه جداست. یک آزمون منفی، بیماری را رد نمی‌کند.",),
        "cartilage": ("علائم و معاینه اختصاصی نیستند؛ پرچم تصویر محل، درجه، پایداری یا بلوغ اسکلتی را ثبت نمی‌کند و علت درد را اثبات نمی‌کند.",),
    }
    comparisons = []
    for comp in ("oa", "pfp", "meniscus", "cartilage"):
        comp_rows = tuple(relationships[comp])
        available = any(row.relation != "unavailable" for row in comp_rows)
        if comp == "oa" and value("age_band") == "45_or_over" and value("pain_pattern") == "activity" and value("morning_stiffness") in {"none", "up_to_30_min"}:
            summary = "سه ویژگی ثبت‌شده با فنوتیپ بالینی راهنمای NICE تطبیق دارند؛ این تطبیق تشخیص تأییدشده نیست و ارزیابی پزشک لازم است."
        else:
            summary = "مقایسهٔ شواهد ثبت‌شده برای بازبینی «" + labels[comp] + "»؛ ناسازگاری یا فقدان داده، رد بیماری نیست."
        if withheld: summary = "جمع‌بندی معمول به‌علت پیش‌نیاز یا نیاز به بررسی پزشک معلق است. " + summary
        comparisons.append(DifferentialComparison(id=comp, label_fa=labels[comp],
            status="withheld_by_workflow" if withheld else "evidence_for_physician_review" if available else "information_missing",
            summary_fa=summary, relationships=comp_rows, limitations_fa=limitations[comp]))
    management_fields = {"functional_limitation", "pain_score_now", "care_goal", "care_goals", "diagnosed_conditions", "medication_list", "prior_treatment", "prior_surgery"}
    management_rows = tuple(row for row in rows if row.field in management_fields)
    management = ManagementContextReview(observations=management_rows, review_points_fa=(
        "شدت درد همین حالا، محدودیت عملکرد و هدف‌های انتخاب‌شده جداگانه برای تصمیم مشترک پزشک و بیمار حفظ می‌شوند؛ تشخیص از شدت درد استنباط نمی‌شود.",
        "داروها و بیماری‌های گزارش‌شده نیازمند تطبیق پزشک‌اند؛ متن آزاد به منع مصرف، نام داروی ساختاریافته یا طرح درمان تبدیل نمی‌شود.",
        "شرح و پاسخ هر درمان قبلی در اپیزود جداگانهٔ نمای پایه باقی می‌مانند؛ بهبود درد یا عملکرد اثبات اثر علّی درمان یا بازسازی غضروف نیست.",
    ))
    source_map = {entry.source_key: entry for entry in (*baseline.baseline_assessment.source_references, *new_sources)}
    source_set = tuple(source_map[key] for key in sorted(source_map))
    tree_order = {node.field: node.number for node in preview.tree.nodes}
    tree_order.update({multi: tree_order[single] for single, multi in ALIASES.items()})
    tree_order["has_pain"] = 10.5  # explicit routing before pain-specific history
    next_items.sort(key=lambda item: (
        {"workflow_first": 0, "clarification": 1, "discriminating_information": 2, "context_review": 3}[item.priority],
        tree_order.get(item.field, 100), item.id,
    ))
    summary = baseline.problem_representation.summary_fa
    usable_extras = [EXTRA_LABELS[row.field] + ": " + row.value_fa for row in extras if row.usability == "usable"]
    if usable_extras: summary += "؛ " + "؛ ".join(dict.fromkeys(usable_extras))
    source_hash = content_digest({"sources": [source.model_dump(mode="json") for source in source_set], "fact_hashes": hashes})
    rules_hash = content_digest({"version": VERSION, "relationships": _relationships(), "source_set_sha256": source_hash,
        "baseline_rules_sha256": baseline.rules_sha256, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(Path(workbench_schema.__file__).read_bytes()).hexdigest(),
        "question_definitions": [questions[key].model_dump(mode="json") for key in sorted(questions)]})
    result = KneeWorkbench(baseline_review=baseline, baseline_workflow_status=baseline.baseline_assessment.status,
        workflow_status=status, workflow_equivalences=tuple(equivalences), summary_fa=summary,
        routine_evaluation_withheld=withheld, supplemental_observations=extras,
        quarantined_observations=quarantined, comparisons=tuple(comparisons), next_items=tuple(next_items),
        management_review=management, source_references=source_set, new_draft_proposals=proposals,
        limitations_fa=("مقایسه‌ها محدود، بدون رتبه‌بندی و احتمال تشخیصی‌اند؛ این خروجی اعتبارسنجی مستقل بالینی نشده است.",
                        "منابع آنلاین جدید خودکار وارد منطق تشخیصی نمی‌شوند؛ در این نما فقط نسخه‌های صریحِ پیش‌نویسِ دارای منشأ مصرف شده‌اند.",
                        "این نما موتور ایمنی را اجرا نمی‌کند؛ نبود هشدار تأیید ایمنی بیمار نیست. قراردادهای مشترک و قواعد عملیاتی تغییر نکرده‌اند."),
        request_sha256=content_digest(request.model_dump(mode="json")), rules_sha256=rules_hash,
        source_set_sha256=source_hash, result_sha256="0" * 64)
    return result.model_copy(update={"result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))})
