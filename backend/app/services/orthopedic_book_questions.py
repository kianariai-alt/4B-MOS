"""Attach Draft book provenance to an unchanged existing question selection.

Only 001/002 annotate questions already returned by the current selector. Other
book concepts surface physician review requirements for data not represented by
the v1 context. No findings, diagnoses, treatment choices or safety rules arise.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path

from backend.app.schemas import orthopedic_book_questions as bridge_schema
from backend.app.schemas.orthopedic_book_questions import (
    BookClinicianReviewRequirement, BookQuestionAnnotation, BookQuestionPreview,
    BookQuestionPreviewRequest, BookQuestionSourceReference,
)
from backend.app.schemas.orthopedic_book_review import KneeBookReviewPack
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack, content_digest
from backend.app.services.orthopedic_book_review import load_knee_book_review_pack, validate_knee_book_review_pack
from backend.app.services.orthopedic_knowledge import load_knee_pack, validate_knee_pack
from backend.app.services.orthopedic_questions import select_questions


RULE_VERSION = "1.0.0"
QUESTION_BINDINGS = (
    dict(field="pain_score", candidate_keys=("BOOK.KNEE.001",), required_scopes=("arthroplasty_review",),
         rationale_fa="در بازبینی آرتروپلاستی، درد باید جدا از شدت رادیوگرافیک ثبت یا روشن شود؛ این ارجاع تعیین اندیکاسیون جراحی نیست."),
    dict(field="functional_limitation", candidate_keys=("BOOK.KNEE.001",), required_scopes=("arthroplasty_review",),
         rationale_fa="محدودیت عملکرد باید مستقل از درجهٔ تصویر ثبت یا روشن شود؛ تناسب منبع با بیمار ارزیابی نشده است."),
    dict(field="relevant_comorbidity", candidate_keys=("BOOK.KNEE.002",), required_scopes=("arthroplasty_review",),
         rationale_fa="شناسایی بیماری‌های همراه بخشی از شرح‌حال پیش از آرتروپلاستی است؛ این پرسش امتیاز خطر یا صلاحیت جراحی تعیین نمی‌کند."),
)

CLINICIAN_REVIEW_BINDINGS = (
    dict(id="book.review.mcmurray", title_fa="نتیجهٔ معاینهٔ مک‌موری",
         reason_fa="در صورت بررسی پارگی منیسک، نتیجهٔ مک‌موری باید از معاینهٔ پزشک بیاید؛ سؤال بیمار یا نتیجهٔ عمومی معاینه جای آن را نمی‌گیرد.",
         candidate_keys=("BOOK.KNEE.003",), required_scopes=("meniscus_review",),
         required_information=("نتیجهٔ مک‌موری: مثبت، منفی، نامشخص یا انجام‌نشده؛ همراه منشأ معاینه",),
         data_channel="physician_exam"),
    dict(id="book.review.structural_location", title_fa="محل ساختاری ضایعه",
         reason_fa="در صورت بررسی ضایعهٔ غضروفی یا استئوکندرال، محل ساختاری از ارزیابی تخصصی تأییدشده ثبت شود؛ محل درد یا پرچم وجود ضایعه کافی نیست.",
         candidate_keys=("BOOK.KNEE.004",), required_scopes=("cartilage_review",),
         required_information=("محل ساختاری ضایعه از گزارش تصویربرداری، جراحی یا ارزیابی تخصصی تأییدشده",),
         data_channel="physician_assessment"),
    dict(id="book.review.skeletal_maturity", title_fa="وضعیت بلوغ اسکلتی در زمینهٔ OCD",
         reason_fa="اگر OCD مشکوک یا مستند بررسی می‌شود، وضعیت صفحهٔ رشد نیازمند ارزیابی تخصصی است؛ از سن یا گفتهٔ بیمار استنباط نمی‌شود.",
         candidate_keys=("BOOK.KNEE.005",), required_scopes=("ocd_review",),
         required_information=("وضعیت بلوغ اسکلتی یا فیز با منشأ ارزیابی تخصصی",), data_channel="physician_assessment"),
    dict(id="book.review.meniscal_vascular_zone", title_fa="ناحیهٔ پارگی و ظرفیت ترمیم",
         reason_fa="در صورت بررسی پارگی منیسک، ناحیهٔ ساختاری پارگی با محل درد متفاوت است؛ هیچ احتمال ترمیم یا روش جراحی از این کارت تعیین نمی‌شود.",
         candidate_keys=("BOOK.KNEE.006",), required_scopes=("meniscus_review",),
         required_information=("ناحیهٔ ساختاری پارگی برای بررسی ارتباط با خون‌رسانی",), data_channel="physician_assessment"),
    dict(id="book.review.meniscal_prp_context", title_fa="زمینهٔ شواهد PRP و ترمیم منیسک",
         reason_fa="برای مرور شواهد PRP در منیسک، شرح مداخله و درمان همراه باید تفکیک شود؛ انتخاب این دامنه به معنای دریافت PRP توسط بیمار نیست.",
         candidate_keys=("BOOK.KNEE.007",), required_scopes=("meniscus_review", "prp_evidence_review"),
         required_information=("مسیر تزریق و فرآورده در شرح مطالعه یا مدرک درمان",
                               "همراهی با trephination، ترمیم یا بازسازی منیسک و گروه مقایسه"),
         data_channel="physician_treatment_record"),
    dict(id="book.review.separate_outcomes", title_fa="ثبت جداگانهٔ پیامدهای درمان",
         reason_fa="درمان قبلی گزارش شده است، اما نوع آن و دریافت PRP تأیید نشده است. اگر PRP در مدرک درمان تأیید شود، درد، عملکرد و یافتهٔ ساختاری جدا بررسی شوند؛ پاسخ عمومی درمان، بازسازی غضروف یا اثر علّی را اثبات نمی‌کند.",
         candidate_keys=("BOOK.KNEE.008",), required_scopes=("prp_evidence_review",),
         required_information=("نوع درمان قبلی و تأیید یا نبود دریافت PRP در مدرک درمان",
                               "تغییر درد گزارش‌شده، مستقل از عملکرد",
                               "تغییر عملکرد گزارش‌شده، مستقل از درد",
                               "یافتهٔ ساختاری با روش و منشأ تأییدشده، مستقل از علائم"),
         data_channel="physician_outcome_review", requires_prior_treatment=True),
    dict(id="book.review.focal_cartilage_scope", title_fa="دامنهٔ محدود ضایعهٔ موضعی غضروف",
         reason_fa="برای بازبینی زمینهٔ آرتروپلاستی در ضایعهٔ موضعی غضروف، انطباق با جمعیت محدود منبع باید توسط پزشک بررسی شود؛ این کارت اندیکاسیون یا منع جراحی صادر نمی‌کند.",
         candidate_keys=("BOOK.KNEE.009",), required_scopes=("arthroplasty_review", "cartilage_review"),
         required_information=("بازبینی انطباق جمعیت با دامنهٔ میانسال فعال در منبع",
                               "علامت‌دار، منفرد، موضعی و تمام‌ضخامت بودن ضایعهٔ غضروف فمور از مدرک تخصصی"),
         data_channel="physician_assessment"),
)


def _source_reference(entry) -> BookQuestionSourceReference:
    target_hash = None
    if entry.action == "support_existing":
        target_hash = next(reference.content_sha256 for reference in entry.related_facts
                           if reference.fact_key == entry.registry_fact_key)
    return BookQuestionSourceReference(
        candidate_key=entry.candidate_key, registry_fact_key=entry.registry_fact_key,
        action=entry.action, title=entry.title, summary=entry.summary,
        population=entry.population, indication=entry.indication,
        application_conditions=entry.application_conditions, limitations=entry.limitations,
        evidence_scope=entry.evidence_scope,
        content_sha256=entry.draft_preview.content_sha256 if entry.draft_preview else None,
        entry_sha256=content_digest(entry.model_dump(mode="json")),
        support_scope=entry.support_scope, target_base_fact_content_sha256=target_hash,
        source=entry.source.model_copy(deep=True), provenance=entry.provenance.model_copy(deep=True),
    )


def build_book_question_preview(
    request: BookQuestionPreviewRequest | Mapping,
    base_pack: KneeKnowledgePack | None = None,
    book_pack: KneeBookReviewPack | Mapping | None = None,
) -> BookQuestionPreview:
    """Add only source annotations and explicit physician review information.

    Missing/answered/conflicting question selection is delegated unchanged to
    select_questions. These workflow scopes do not assert a diagnosis, verified
    treatment, population fit, or a requirement to order an examination/image.
    """
    request = BookQuestionPreviewRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, BookQuestionPreviewRequest) else dict(request)
    )
    base = load_knee_pack() if base_pack is None else validate_knee_pack(base_pack)
    supplement = validate_knee_book_review_pack(
        load_knee_book_review_pack() if book_pack is None else book_pack, base,
    )
    baseline = select_questions(request.context, base)
    entries = {entry.candidate_key: entry for entry in supplement.entries}
    needed = {key for rule in (*QUESTION_BINDINGS, *CLINICIAN_REVIEW_BINDINGS)
              for key in rule["candidate_keys"]}
    if not needed <= entries.keys():
        raise ValueError("Book question bindings require all referenced Draft candidates.")
    scopes = set(request.review_scopes)
    annotations = []
    cards = []
    in_scope = request.context.body_region == "knee"
    prior_treatment = any(item.field == "prior_treatment" and item.value is True
                          for item in baseline.structured_symptoms)
    if in_scope:
        for candidate in baseline.question_candidates:
            for rule in QUESTION_BINDINGS:
                if candidate.field == rule["field"] and set(rule["required_scopes"]) <= scopes:
                    annotations.append(BookQuestionAnnotation(
                        question_id=candidate.question.id, field=candidate.field,
                        rule_id=candidate.rule_id, rule_version=candidate.rule_version,
                        action=candidate.action, candidate_keys=rule["candidate_keys"],
                        rationale_fa=rule["rationale_fa"],
                    ))
        for rule in CLINICIAN_REVIEW_BINDINGS:
            if not set(rule["required_scopes"]) <= scopes:
                continue
            if rule.get("requires_prior_treatment") and not prior_treatment:
                continue
            cards.append(BookClinicianReviewRequirement(**{
                key: value for key, value in rule.items()
                if key not in {"required_scopes", "requires_prior_treatment"}
            }))
    used = {key for item in (*annotations, *cards) for key in item.candidate_keys}
    sources = tuple(_source_reference(entries[key]) for key in sorted(used))
    rules_sha256 = content_digest({
        "schema_version": RULE_VERSION,
        "bridge_artifact_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_artifact_sha256": hashlib.sha256(Path(bridge_schema.__file__).read_bytes()).hexdigest(),
        "baseline_rules_sha256": baseline.rules_sha256,
        "supplement_manifest_sha256": supplement.manifest_sha256,
        "question_bindings": QUESTION_BINDINGS,
        "clinician_review_bindings": CLINICIAN_REVIEW_BINDINGS,
        "entry_sha256s": {key: content_digest(entries[key].model_dump(mode="json")) for key in sorted(needed)},
        "selection_policy": "existing-candidates-only;explicit-scopes;effective-prior-treatment;no-population-inference-v1",
    })
    reasons = list(baseline.review_reasons)
    reasons.extend(("book_drafts_require_independent_review", "population_applicability_not_assessed",
                    "existing_safety_engine_not_evaluated_by_preview"))
    if not scopes:
        reasons.append("no_book_review_scope_selected")
    if cards:
        reasons.append("book_information_not_represented_in_context_v1")
    result = BookQuestionPreview(
        review_scopes=request.review_scopes,
        request_sha256=content_digest(request.model_dump(mode="json")),
        base_pack_manifest_sha256=base.manifest_sha256,
        supplement_manifest_sha256=supplement.manifest_sha256,
        page_review_bundle_sha256=supplement.page_review_bundle_sha256,
        rules_sha256=rules_sha256, baseline=baseline,
        question_annotations=tuple(annotations), clinician_review_requirements=tuple(cards),
        source_references=sources, review_reasons=tuple(dict.fromkeys(reasons)),
        result_sha256="0" * 64,
    )
    return result.model_copy(update={
        "result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"})),
    })
