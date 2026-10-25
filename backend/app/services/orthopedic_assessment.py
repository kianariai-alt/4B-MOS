"""Fixed orthopedic knowledge compatibility, compiled to finite review tables.

This consumes the existing source-preserving preview, never a text similarity
model, diagnostic score, general rule engine, active safety rule or patient DB.
The offline model contains the same finite tables, not representative-patient
result hashes. All source bindings and content rules remain independently
unreviewed Draft authoring proposals.
"""
from __future__ import annotations

import hashlib
from itertools import product
import json
from pathlib import Path

from backend.app.schemas import orthopedic_assessment as assessment_schema
from backend.app.schemas.medical_knowledge import KnowledgeFactCreate, KnowledgeSourceCreate
from backend.app.schemas.orthopedic_assessment import (
    AssessmentConsideration, AssessmentDraftProposal, ConditionalTreatmentEvidence,
    KneeAssessmentPreview,
)
from backend.app.schemas.orthopedic_interview_tree import (
    BOOLEAN_FIELDS, CHOICES, KneeInterviewTreePreviewRequest,
)
from backend.app.schemas.orthopedic_knowledge import SourceEntry, content_digest
from backend.app.services.medical_knowledge import knowledge_content_digest
from backend.app.services.orthopedic_interview_tree import build_interview_tree, build_interview_tree_preview
from backend.app.services.orthopedic_knowledge import load_knee_pack


VERSION = "1.0.0"
TOKENS = ("p", "n", "u")
CORE = ("has_pain", "onset", "duration", "pain_location", "pain_pattern", "trauma", "mechanical_locking", "prior_surgery")
RISK = ("fever", "acute_swelling", "systemic_symptoms")
NEURO = ("sensory_change", "weakness", "foot_coldness", "foot_color_change")
PFP_KEY = "KNEE.PFP.PRESENTATION"
HEADLINES = {
    "prompt_physician_review": "اطلاعات نیازمند بررسی زودهنگام پزشک؛ جمع‌بندی معمول و شواهد درمان فعلاً متوقف است.",
    "outside_scope": "این اطلاعات خارج از دامنهٔ جمع‌بندی زانو است.",
    "side_specific_review": "برای جمع‌بندی، شرح‌حال هر زانو جداگانه مشخص شود.",
    "insufficient_information": "اطلاعات برای پیشنهاد تشخیصی قابل‌دفاع کافی یا سازگار نیست؛ موارد زیر توسط پزشک روشن شوند.",
    "single_prefix": "تشخیص پیشنهادی برای بررسی پزشک: ",
    "multiple": "چند تشخیص افتراقی برای بررسی پزشک مطرح است؛ ترتیب نمایش رتبهٔ احتمال نیست.",
}


def _json_value(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pfp_proposal():
    source = KnowledgeSourceCreate(
        source_type="other", title="Patellofemoral Pain Syndrome",
        citation="American Academy of Orthopaedic Surgeons. OrthoInfo: Patellofemoral Pain Syndrome. Official patient-education page; full text reviewed 2026-10-25. Not a diagnostic-accuracy study.",
        publisher="AAOS OrthoInfo", url="https://www.orthoinfo.org/diseases--conditions/patellofemoral-pain-syndrome/",
        guideline_version="Official educational webpage; source version not displayed", accessed_at="2026-10-25",
    )
    metadata = {
        "body_region": "knee", "topic": "patellofemoral_pain", "source_keys": ["aaos_pfp_education"],
        "conditions": ["Clinician assessment of anterior/peripatellar symptoms and alternative causes is required."],
        "limitations": ["Educational source, ungraded evidence; this is not a validated diagnostic rule.",
                        "Anterior pain with loaded flexion does not establish cartilage damage or a diagnosis.",
                        "Independent source and specialist review remain pending."],
    }
    fact = KnowledgeFactCreate(
        fact_key=PFP_KEY, title="Anterior pain with loaded flexion: patellofemoral assessment context",
        statement="Anterior or peripatellar pain associated with loaded knee flexion, such as stairs, can prompt clinician consideration of patellofemoral pain; other causes require assessment.\n\nOrthopedic assessment metadata v1:\n" + _json_value(metadata),
        clinical_domain="orthopedics_knee", population="People undergoing clinician-led assessment of anterior knee pain.",
        indication="Draft educational differential context; no diagnosis, cartilage-damage inference or treatment authorization.",
        evidence_grade="ungraded", sources=[source],
    )
    return AssessmentDraftProposal(fact=fact, content_sha256=knowledge_content_digest(fact_key=fact.fact_key, version=1, content=fact)), SourceEntry(
        source_key="aaos_pfp_education", source=source, verified_at="2026-10-25", access_level="full_text",
        verification_note="Official educational page read; supports symptom context only. No diagnostic accuracy, cartilage regeneration or independent specialist approval is inferred.",
    )


def export_offline_assessment() -> dict:
    """Export closed finite tables for this specific Draft content version."""
    pack = load_knee_pack()
    proposal, pfp_source = _pfp_proposal()
    facts = {item.fact.fact_key: item for item in pack.facts}
    hashes = {key: item.content_sha256 for key, item in facts.items()}
    hashes[PFP_KEY] = proposal.content_sha256
    fact_sources = {key: item.source_keys for key, item in facts.items()}
    fact_sources[PFP_KEY] = ("aaos_pfp_education",)

    def card(id, label, supporting, limitations, gaps, requirements, keys, compatibility="authored_pattern_for_review"):
        return AssessmentConsideration(
            id=id, label_fa=label, supporting_findings_fa=tuple(supporting), limitations_fa=tuple(limitations),
            information_gaps_fa=tuple(gaps), assessment_requirements_fa=tuple(requirements),
            source_fact_keys=tuple(keys), source_content_sha256s=tuple(hashes[key] for key in keys),
            source_keys=tuple(sorted({source for key in keys for source in fact_sources[key]})), compatibility=compatibility,
        ).model_dump(mode="json")

    cards = [
        card("knee_oa", "الگوی درد مکانیکی مزمن؛ آرتروز زانو از افتراق‌هاست",
             ["درد گزارش‌شده با شروع تدریجی، مدت ماه‌ها یا سال‌ها و ارتباط با فعالیت سازگار است."],
             ["این الگو اختصاصی نیست و تشخیص یا برتری احتمال OA را ثابت نمی‌کند.", "درجهٔ تصویر با درد و ناتوانی یکسان نیست."],
             ["سن و الگوی خشکی صبحگاهی در این ۳۰ سؤال ثبت نشده‌اند؛ معیار تشخیصی رسمی کامل نشده است."],
             ["معاینهٔ پزشک و بررسی علل جایگزین، دامنهٔ حرکت و عملکرد."], ["KNEE.OA.PRESENTATION", "KNEE.OA.KL_CONTEXT"]),
        card("patellofemoral_pain", "درد پاتلوفمورال از افتراق‌های درد جلوی زانوست",
             ["درد جلوی زانو با پله یا خم‌کردن زانو زیر بار گزارش شده است."],
             ["از محل درد، نرمی یا تخریب غضروف کشکک نتیجه‌گیری نمی‌شود.", "علل دیگر درد قدامی باید بررسی شوند."],
             ["بازآفرینی علائم و معاینهٔ تخصصی توسط پزشک ثبت نشده است."],
             ["بررسی محل درد و الگوی بارگذاری توسط پزشک؛ تشخیص افتراقی تاندون، مفصل و سایر ساختارها."], [PFP_KEY]),
        card("meniscal_finding", "ضایعهٔ منیسک در مدرک تصویربرداریِ بازبینی‌شده؛ نیازمند تطبیق بالینی",
             ["وجود ضایعهٔ منیسک در کانال تصویر بازبینی‌شده ثبت شده است."],
             ["وجود ضایعه ثابت نمی‌کند علت درد همین یافته است.", "تصویر به‌تنهایی روش درمان یا نیاز به جراحی تعیین نمی‌کند."],
             ["تطبیق معاینه، مکانیسم و نوع ضایعه و علائم نیازمند بررسی پزشک است."],
             ["تفکیک آسیب حاد از تغییرات دژنراتیو و بررسی کاربرد راهنمای مرتبط."],
             ["KNEE.MENISCUS.SCOPE", "KNEE.MENISCUS.EXAMINATION"], "documented_finding_for_review"),
        card("cartilage_finding", "ضایعهٔ غضروفیِ گزارش‌شده در تصویر بازبینی‌شده؛ نیازمند تطبیق بالینی",
             ["وجود ضایعهٔ غضروفی در کانال تصویر بازبینی‌شده ثبت شده است."],
             ["این پرچم نوع، محل، درجه، علت درد یا وجود OCD را ثابت نمی‌کند."],
             ["محل و درجهٔ ساختاری و در صورت بررسی OCD، بلوغ اسکلتی و پایداری نامشخص‌اند."],
             ["بررسی گزارش ساختاری و انطباق با علائم توسط پزشک."],
             ["KNEE.CARTILAGE.CLASSIFICATION", "KNEE.CARTILAGE.HISTORY_EXAM"], "documented_finding_for_review"),
    ]
    urgent_cards = [
        card("urgent_infection_inflammation", "تورم تازه یا علائم عمومی؛ علت باید توسط پزشک روشن شود",
             ["اطلاعات تب، تورم تازه یا بدحالی گزارش شده است؛ این‌ها تشخیص نیستند."],
             ["تورم به‌تنهایی عفونت را ثابت نمی‌کند؛ نبود تب نیز عفونت را رد نمی‌کند.", "نبود هشدار تأیید ایمنی نیست."],
             ["معاینه و ارزیابی فوریت توسط پزشک لازم است."], ["ارجاع اطلاعات به پزشک و موتور ایمنی موجود."],
             ["KNEE.SAFETY.HOT_JOINT", "KNEE.SAFETY.SEPSIS"], "urgent_context_for_review"),
        card("urgent_neurovascular", "گزارش عصبی‌عروقی نیازمند بررسی زودهنگام پزشک است",
             ["تغییر حس، ضعف، سردی یا تغییر رنگ تازه گزارش شده است."],
             ["گزارش بیمار تشخیص آسیب عروقی یا نتیجهٔ معاینه نیست."],
             ["زمینهٔ آسیب و معاینهٔ عصبی‌عروقی لازم است."], ["بررسی فوری اطلاعات توسط پزشک؛ مصاحبه نباید رسیدگی را عقب بیندازد."],
             ["KNEE.SAFETY.NEUROVASCULAR_TRAUMA"], "urgent_context_for_review"),
        card("urgent_internal_derangement", "در گیرکردن حرکت پس از آسیب، ضایعهٔ داخلی زانو از افتراق‌هاست",
             ["سابقهٔ آسیب و گیرکردن حرکت گزارش شده‌اند."],
             ["منیسک، جسم آزاد یا آسیب‌های دیگر باید بررسی شوند؛ گزارش قفل‌شدن پارگی جابه‌جا‌شده را ثابت نمی‌کند.", "جراحی یا MRI برای همهٔ آسیب‌ها توصیه نمی‌شود."],
             ["تفکیک بلوک مکانیکی واقعی از توقف حرکت به‌علت درد با پزشک است."], ["ارزیابی تخصصی حرکت و آسیب همراه توسط پزشک."],
             ["KNEE.MENISCUS.SCOPE", "KNEE.MENISCUS.MOTION_BLOCK"], "urgent_context_for_review"),
    ]
    evidence = []
    for id, label, summary, keys, limitations in (
        ("oa_exercise", "شواهد ورزش‌درمانی در OA تأییدشده توسط پزشک", "راهنمای ACR/AF برای OA زانو از ورزش حمایت می‌کند؛ برنامه با وضعیت و توان بیمار تطبیق داده می‌شود.", ["KNEE.OA.EXERCISE"], ["نوع و شدت تمرین در این خروجی تجویز نمی‌شود."]),
        ("oa_topical_nsaid", "شواهد NSAID موضعی در OA تأییدشده توسط پزشک", "ACR/AF از NSAID موضعی برای OA زانو حمایت می‌کند؛ انتخاب دارو به بررسی پزشک وابسته است.", ["KNEE.OA.TOPICAL_NSAID"], ["دارو و دوز تجویز نمی‌شود؛ حساسیت، بیماری‌ها، تداخل‌ها و خطرهای فردی باید جدا بررسی شوند."]),
    ):
        evidence.append(ConditionalTreatmentEvidence(
            id=id, label_fa=label, summary_fa=summary,
            conditions_fa=("فقط اگر پزشک پس از بررسی، تشخیص OA و تناسب گزینه را تأیید کند.", "کامل‌بودن پرسش‌ها تأیید ایمنی، نبود منع مصرف یا دستور درمان نیست."),
            limitations_fa=tuple(limitations) + ("این خلاصهٔ شواهد، طرح درمان شخصی نیست و اثربخشی یا بازسازی غضروف را از پاسخ قبلی استنتاج نمی‌کند.",),
            source_fact_keys=tuple(keys), source_content_sha256s=tuple(hashes[key] for key in keys),
            source_keys=tuple(sorted({source for key in keys for source in fact_sources[key]})),
        ).model_dump(mode="json"))

    axes = []
    def axis(id, input, field, positive=(), negative=(), known=False):
        tokens = {_json_value(value): "p" for value in positive}
        tokens.update({_json_value(value): "n" for value in negative})
        if known:
            values = (True, False) if field in BOOLEAN_FIELDS else CHOICES.get(field, ())
            tokens = {_json_value(value): ("u" if value == "unclear" else "p") for value in values}
        axes.append(dict(id=id, input=input, field=field, value_tokens=tokens, default_token="u", tokens=list(TOKENS)))
        return id

    axis("region", "region", "body_region", ["knee"], ["other"])
    axis("side", "usable_history", "laterality", ["right", "left"], ["both"])
    for field in sorted(BOOLEAN_FIELDS):
        axis(field, "usable_history", field, [True], [False])
    for field in CORE:
        axis("known:" + field, "usable_history", field, known=True)
    axis("gradual", "usable_history", "onset", ["gradual"], ["sudden"])
    axis("chronic", "usable_history", "duration", ["months", "years"], ["days", "weeks"])
    axis("activity_pain", "usable_history", "pain_pattern", ["activity", "mixed"], ["rest", "night"])
    axis("anterior", "usable_history", "pain_location", ["anterior"], ["medial", "lateral", "posterior", "diffuse"])
    axis("loaded_flexion", "usable_history", "aggravating_factor", ["stairs", "loaded_flexion"], ["walking", "none", "other"])
    for field in ("imaging_meniscal_lesion", "imaging_cartilage_lesion"):
        axis(field, "usable_clinical", field, [True], [False])
    for field in (*RISK, *NEURO, "trauma", "mechanical_locking"):
        axis("raw:" + field, "raw_true", field)
    tree = build_interview_tree()
    field_labels = {node.field: node.question.text_fa for node in tree.nodes}
    field_labels["has_pain"] = "وجود یا نبود درد در دورهٔ مشکل زانو"
    for node in tree.nodes:
        if node.conditions and not node.repeat_per_treatment:
            axis("presence:" + node.field, "raw_presence", node.field)
    axis("episode_presence", "episode_presence", "treatment_episodes")

    guards = []
    def guard(id, ids, decide, priority, keys=(), urgent_ids=()):
        rows = {}
        for values in product(TOKENS, repeat=len(ids)):
            status, reason = decide(values)
            rows["|".join(values)] = dict(status=status, reason_fa=reason,
                source_fact_keys=list(keys), urgent_consideration_ids=list(urgent_ids) if status == "prompt_physician_review" else [])
        guards.append(dict(id=id, axis_ids=ids, priority=priority, rows=rows))

    guard("region", ["region"], lambda x: ("ready", "") if x[0] == "p" else
          ("outside_scope", "دامنهٔ بدن خارج از زانو است.") if x[0] == "n" else
          ("insufficient_information", "ناحیهٔ بدن مشخص نشده است."), 100)
    guard("side", ["side"], lambda x: ("ready", "") if x[0] == "p" else
          ("side_specific_review", "برای دو زانو، زمینه‌های راست و چپ جدا لازم است.") if x[0] == "n" else
          ("insufficient_information", "سمت زانو باید مشخص یا روشن شود."), 80)
    for field in RISK:
        guard("raw_risk:" + field, ["raw:" + field], lambda x, field=field: ("prompt_physician_review", "اطلاعات تازهٔ تب، تورم یا بدحالی نیازمند بررسی پزشک است.") if x[0] == "p" else ("ready", ""),
              90, ["KNEE.SAFETY.HOT_JOINT", "KNEE.SAFETY.SEPSIS"], ["urgent_infection_inflammation"])
        guard("risk_readiness:" + field, [field], lambda x, field=field: ("ready", "") if x[0] == "n" else
              ("insufficient_information", "پاسخ کامل و سازگارِ تب، تورم تازه و بدحالی برای این جمع‌بندی لازم است."), 60)
    for field in NEURO:
        guard("raw_neuro:" + field, ["raw:" + field], lambda x: ("prompt_physician_review", "علامت عصبی‌عروقی گزارش‌شده باید زودهنگام توسط پزشک بررسی شود.") if x[0] == "p" else ("ready", ""),
              90, ["KNEE.SAFETY.NEUROVASCULAR_TRAUMA"], ["urgent_neurovascular"])
        guard("neuro_readiness:" + field, ["trauma", field], lambda x: ("ready", "") if x[0] != "p" or x[1] == "n" else
              ("insufficient_information", "در سابقهٔ آسیب، وضعیت چهار علامت عصبی‌عروقی باید روشن شود."), 60)
    guard("movement_block", ["raw:trauma", "raw:mechanical_locking"], lambda x: ("prompt_physician_review", "گیرکردن حرکت پس از آسیب نیازمند بررسی تخصصی پزشک است.") if x == ("p", "p") else ("ready", ""),
          90, ["KNEE.MENISCUS.MOTION_BLOCK"], ["urgent_internal_derangement"])
    for field in CORE:
        # Pain descriptors are not required when no pain was explicitly reported.
        ids = ["has_pain", "known:" + field] if field in {"pain_location", "pain_pattern"} else ["known:" + field]
        guard("core:" + field, ids, lambda x, field=field: ("ready", "") if x[-1] == "p" or (len(x) == 2 and x[0] == "n") else
              ("insufficient_information", "این بخش شرح‌حال باید روشن شود: " + field_labels[field]), 50)
    guard("surgical_context", ["prior_surgery"], lambda x: ("insufficient_information", "سابقهٔ جراحی نیازمند بازبینی نوع عمل و زمینهٔ بالینی است؛ متن بیمار به نوع جراحی تبدیل نمی‌شود.") if x[0] == "p" else ("ready", ""), 65)
    for node in tree.nodes:
        if node.repeat_per_treatment:
            continue
        for condition in node.conditions:
            guard("dependency:" + node.field, [condition.field, "presence:" + node.field], lambda x: ("ready", "") if x[0] == "p" or x[1] == "n" else
                  ("insufficient_information", "پاسخ وابسته با پیش‌نیاز فعلی سازگار یا روشن نیست؛ اصل پاسخ حفظ شود."), 70)
    guard("episode_dependency", ["prior_treatment", "episode_presence"], lambda x: ("ready", "") if x[0] == "p" or x[1] == "n" else
          ("insufficient_information", "سابقه‌های درمان با پاسخ کلیِ درمان قبلی نیازمند تطبیق‌اند."), 70)

    tables = []
    for id, ids, match in (
        ("knee_oa", ["has_pain", "gradual", "chronic", "activity_pain", "trauma"], ("p", "p", "p", "p", "n")),
        ("patellofemoral_pain", ["has_pain", "anterior", "loaded_flexion", "trauma"], ("p", "p", "p", "n")),
        ("meniscal_finding", ["imaging_meniscal_lesion"], ("p",)),
        ("cartilage_finding", ["imaging_cartilage_lesion"], ("p",)),
    ):
        tables.append(dict(id=id, axis_ids=ids, rows={"|".join(values): values == match for values in product(TOKENS, repeat=len(ids))}))
    used = {key for item in (*cards, *urgent_cards, *evidence) for key in item["source_keys"]}
    sources = [source.model_dump(mode="json") for source in pack.sources if source.source_key in used]
    sources.append(pfp_source.model_dump(mode="json"))
    result = dict(schema_id="4b-mos.knee-assessment-offline", schema_version=VERSION,
        axes=axes, guard_tables=guards, card_tables=tables, cards=cards, urgent_cards=urgent_cards,
        fact_sources={key: list(values) for key, values in sorted(fact_sources.items())},
        treatment_evidence=evidence, headlines=HEADLINES, source_references=sources,
        no_match_requirement_fa="الگوی فعلی با افتراق‌های محدود این نسخه تطبیق کافی ندارد؛ معاینه و بررسی علل دیگر لازم است.",
        review_notes_fa=["این موارد افتراق‌های قابل‌بررسی‌اند؛ درصد احتمال، تشخیص قطعی یا برنامهٔ درمان تولید نشده است.", "نبود علامت گزارش‌شده، تأیید ایمنی نیست و موتور ایمنی موجود باید جدا ارزیابی کند."],
        new_draft_proposals=[proposal.model_dump(mode="json")],
        output_policy={"ready_status": "ready", "priority_direction": "highest", "single_headline_prefix": HEADLINES["single_prefix"],
                       "multiple_headline": HEADLINES["multiple"], "no_match_status": "insufficient_information"},
        governance_status="draft", requires_independent_review=True, approved_fact_count=0,
        safety_evaluation="not_performed", is_diagnosis=False, is_recommendation=False,
        authorizes_treatment=False, is_clinical_clearance=False,
        website_source_policy="Zetamed topic inventory reviewed; no website-only medical rule or automatic approval.",
        base_pack_manifest_sha256=pack.manifest_sha256, tree_sha256=tree.tree_sha256,
        selector_artifact_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        schema_artifact_sha256=hashlib.sha256(Path(assessment_schema.__file__).read_bytes()).hexdigest(),
    )
    return dict(result, model_sha256=content_digest(result))


def _tokens(model, request, preview):
    history = {item.field: item.value for item in preview.structured_answers}
    clinical = {item.field: item.value for item in preview.usable_clinical_findings}
    raw = {}
    for item in request.context.observations:
        raw.setdefault(item.field, []).append(item)
    result = {}
    for axis in model["axes"]:
        mode, field = axis["input"], axis["field"]
        if mode == "raw_true":
            token = "p" if any(item.value is True for item in raw.get(field, ())) else "n"
        elif mode == "raw_presence":
            items = raw.get(field, ())
            meaningful = any(item.value is not None and item.value is not False and not (type(item.value) is int and item.value == 0) and item.value != "none" for item in items)
            token = "p" if meaningful else "u" if any(item.state != "confirmed" for item in items) else "n"
        elif mode == "episode_presence":
            token = "p" if any(episode.observations for episode in request.context.treatment_episodes) else "n"
        else:
            values = history if mode == "usable_history" else clinical
            value = request.context.body_region if mode == "region" else values.get(field)
            token = axis["value_tokens"].get(_json_value(value), axis["default_token"])
        result[axis["id"]] = token
    return result


def evaluate_assessment_model(model: dict, axis_tokens: dict) -> dict:
    """Evaluate only the precompiled finite data for this content artifact."""
    if model.get("model_sha256") != content_digest({key: value for key, value in model.items() if key != "model_sha256"}):
        raise ValueError("Assessment knowledge table hash does not match its content.")
    if any(axis_tokens.get(axis["id"]) not in TOKENS for axis in model["axes"]):
        raise ValueError("Every assessment axis requires an explicit supported token.")
    decisions = []
    for table in model["guard_tables"]:
        outcome = table["rows"]["|".join(axis_tokens[id] for id in table["axis_ids"])]
        if outcome["status"] != "ready":
            decisions.append((table["priority"], outcome))
    decisions.sort(key=lambda item: item[0], reverse=True)
    reasons = list(dict.fromkeys(outcome["reason_fa"] for _, outcome in decisions))
    if decisions:
        status = decisions[0][1]["status"]
        urgent_ids = {key for _, outcome in decisions for key in outcome["urgent_consideration_ids"]} if status == "prompt_physician_review" else set()
        return dict(status=status, headline_fa=model["headlines"][status], considerations=[],
                    urgent_considerations=[item for item in model["urgent_cards"] if item["id"] in urgent_ids],
                    information_requirements_fa=reasons, conditional_treatment_evidence=[], review_reasons_fa=reasons)
    ids = {table["id"] for table in model["card_tables"] if table["rows"]["|".join(axis_tokens[id] for id in table["axis_ids"]) ]}
    cards = [item for item in model["cards"] if item["id"] in ids]
    status = "differential_review" if cards else "insufficient_information"
    headline = (model["headlines"]["single_prefix"] + cards[0]["label_fa"] if len(cards) == 1 else
                model["headlines"]["multiple"] if cards else model["headlines"]["insufficient_information"])
    missing = list(dict.fromkeys(text for item in cards for text in item["information_gaps_fa"]))
    if not cards:
        missing.append(model["no_match_requirement_fa"])
    return dict(status=status, headline_fa=headline, considerations=cards, urgent_considerations=[],
        information_requirements_fa=missing,
        conditional_treatment_evidence=[item for item in model["treatment_evidence"] if item["requires_card_id"] in ids],
        review_reasons_fa=model["review_notes_fa"])


def build_knee_assessment(request: KneeInterviewTreePreviewRequest | dict) -> KneeAssessmentPreview:
    request = KneeInterviewTreePreviewRequest.model_validate(request.model_dump(mode="json") if isinstance(request, KneeInterviewTreePreviewRequest) else request)
    preview = build_interview_tree_preview(request)
    model = export_offline_assessment()
    tokens = _tokens(model, request, preview)
    reviewed = evaluate_assessment_model(model, tokens)
    result = KneeAssessmentPreview(
        **reviewed, axis_tokens=tokens, lookup_model_sha256=model["model_sha256"],
        source_references=model["source_references"], new_draft_proposals=model["new_draft_proposals"],
        preview_sha256=preview.result_sha256, request_sha256=content_digest(request.model_dump(mode="json")),
        rules_sha256=content_digest({"version": VERSION, "model_sha256": model["model_sha256"]}), result_sha256="0" * 64,
    )
    return result.model_copy(update={"result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))})
