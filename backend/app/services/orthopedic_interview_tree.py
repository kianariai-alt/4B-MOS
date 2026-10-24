"""Draft clinical-content routing over existing answer resolution and Registry.

This is not a general rule runner, active interview, safety engine, or patient
store. The existing bank export is an authoring view; supplemental pain routing
and treatment-episode constraints are represented by the tree/preview contract.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
from types import SimpleNamespace

from backend.app.schemas import orthopedic_interview_tree as tree_schema
from backend.app.schemas.orthopedic_book_review import KneeBookReviewPack
from backend.app.schemas.orthopedic_interview_tree import (
    BOOLEAN_FIELDS, CHOICES, InterviewTreeCandidate, InterviewTreeNode,
    KneeInterviewTree, KneeInterviewTreePreview, KneeInterviewTreePreviewRequest,
    TreeBookBinding, TreeCondition, TreeInformationGap,
)
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack, content_digest
from backend.app.schemas.physician_questions import BankContent, InterviewQuestion
from backend.app.services import orthopedic_questions as existing_questions
from backend.app.services.orthopedic_book_questions import _source_reference
from backend.app.services.orthopedic_book_review import load_knee_book_review_pack, validate_knee_book_review_pack
from backend.app.services.orthopedic_knowledge import load_knee_pack, validate_knee_pack


RULE_VERSION = "1.0.0"
OA = "KNEE.OA.PRESENTATION"
CARTILAGE = "KNEE.CARTILAGE.HISTORY_EXAM"
MENISCUS = "KNEE.MENISCUS.SCOPE"
MOTION = "KNEE.MENISCUS.MOTION_BLOCK"
HOT = "KNEE.SAFETY.HOT_JOINT"
SYSTEMIC = "KNEE.SAFETY.SEPSIS"
NEURO = "KNEE.SAFETY.NEUROVASCULAR_TRAUMA"

# Number, field, plain patient wording, stage, contextual Registry fact, parent.
# These are versioned clinical-content bindings, not executable medical rules.
QUESTION_CONTENT = (
    (1, "chief_complaint", "مشکل اصلی زانوی شما چیست؟", "opening", OA, None),
    (2, "laterality", "مشکل مربوط به زانوی راست است یا چپ؟", "opening", None, None),
    (3, "trauma", "آیا این مشکل پس از یک آسیب مشخص شروع شد؟", "opening", MENISCUS, None),
    (4, "fever", "آیا همراه مشکل زانو تب داشته‌اید؟", "risk_information", HOT, None),
    (5, "acute_swelling", "آیا زانو به‌تازگی به‌طور واضح متورم شده است؟", "risk_information", HOT, None),
    (6, "systemic_symptoms", "آیا همراه مشکل زانو احساس بدحالی عمومی دارید؟", "risk_information", SYSTEMIC, None),
    (7, "sensory_change", "آیا پس از آسیب، بی‌حسی یا تغییر حس تازه‌ای در پای همان سمت پیدا کرده‌اید؟", "risk_information", NEURO, "trauma"),
    (8, "weakness", "آیا پس از آسیب، ضعف تازه‌ای در پای همان سمت پیدا کرده‌اید؟", "risk_information", NEURO, "trauma"),
    (9, "foot_coldness", "آیا پس از آسیب، پای همان سمت سرد شده است؟", "risk_information", NEURO, "trauma"),
    (10, "foot_color_change", "آیا پس از آسیب، رنگ پای همان سمت تغییر کرده است؟", "risk_information", NEURO, "trauma"),
    (11, "onset", "شروع علائم ناگهانی بود یا تدریجی؟", "symptoms", OA, None),
    (12, "duration", "از شروع علائم چقدر گذشته است؟", "symptoms", OA, None),
    (13, "pain_location", "درد را بیشتر در کدام قسمت زانو احساس می‌کنید؟", "symptoms", CARTILAGE, "has_pain"),
    (14, "pain_score_now", "شدت درد زانو همین حالا از صفر تا ده چقدر است؟ صفر یعنی بدون درد و ده یعنی شدیدترین درد قابل‌تصور.", "symptoms", OA, "has_pain"),
    (15, "pain_pattern", "درد بیشتر در چه زمانی رخ می‌دهد؟", "symptoms", OA, "has_pain"),
    (16, "aggravating_factor", "کدام فعالیت بیشتر علائم زانو را تشدید می‌کند؟", "symptoms", CARTILAGE, "has_pain"),
    (17, "relieving_factor", "چه چیزی علائم زانو را کاهش می‌دهد؟", "symptoms", OA, "has_pain"),
    (18, "mechanical_locking", "آیا زانو هنگام حرکت گیر می‌کند، به‌طوری‌که نتوانید حرکت را ادامه دهید؟", "mechanical", MOTION, None),
    (19, "pain_limited_motion", "هنگام آن اتفاق، آیا درد باعث شد خودتان حرکت را متوقف کنید؟", "mechanical", MOTION, "mechanical_locking"),
    (20, "functional_limitation", "مشکل زانو تا چه حد فعالیت‌های روزمرهٔ شما را محدود کرده است؟", "symptoms", OA, None),
    (21, "trauma_mechanism", "آسیب زانو چگونه اتفاق افتاد؟", "history", MENISCUS, "trauma"),
    (22, "prior_surgery", "آیا قبلاً روی همین زانو جراحی شده‌اید؟", "history", CARTILAGE, None),
    (23, "surgery_description", "چه جراحی‌ای روی این زانو انجام شده است؟", "history", CARTILAGE, "prior_surgery"),
    (24, "prior_treatment", "آیا قبلاً برای همین مشکل زانو درمانی دریافت کرده‌اید؟", "history", CARTILAGE, None),
    (25, "treatment_description", "چه درمانی دریافت کرده‌اید؟", "history", CARTILAGE, "prior_treatment"),
    (26, "treatment_pain_response", "پس از آن درمان، درد شما کمتر شد، تغییری نکرد یا بیشتر شد؟", "history", CARTILAGE, "prior_treatment"),
    (27, "treatment_function_response", "پس از آن درمان، توان انجام فعالیت‌های روزمره بهتر شد، تغییری نکرد یا بدتر شد؟", "history", CARTILAGE, "prior_treatment"),
    (28, "diagnosed_conditions", "چه بیماری‌هایی دارید که قبلاً پزشک تشخیص داده باشد؟", "history", OA, None),
    (29, "medication_list", "در حال حاضر چه داروهایی مصرف می‌کنید؟", "history", OA, None),
    (30, "care_goal", "مهم‌ترین هدف شما از مراجعه برای مشکل زانو چیست؟", "goals", OA, None),
)
EPISODE_NUMBERS = {25, 26, 27}
SPLIT_NUMBERS = {7, 8, 9, 10, 26, 27}
FOLLOW_UP_NUMBERS = {2, 19, 23, 25}
BOOK_BINDINGS = {14: "BOOK.KNEE.001", 20: "BOOK.KNEE.001", 28: "BOOK.KNEE.002"}


def _packs(base_pack=None, book_pack=None):
    base = load_knee_pack() if base_pack is None else validate_knee_pack(base_pack)
    supplement = validate_knee_book_review_pack(
        load_knee_book_review_pack() if book_pack is None else book_pack, base,
    )
    return base, supplement


def build_interview_tree(
    base_pack: KneeKnowledgePack | None = None,
    book_pack: KneeBookReviewPack | Mapping | None = None,
) -> KneeInterviewTree:
    """Build a source-bound authoring tree; loading creates no approved bank."""
    base, supplement = _packs(base_pack, book_pack)
    nodes = []
    used_sources = set()
    for number, field, text, stage, fact_key, parent in QUESTION_CONTENT:
        fact = base.get_fact(fact_key) if fact_key else None
        if fact:
            used_sources.update(fact.source_keys)
        # BankContent can express a boolean predecessor, but cannot express the
        # supplemental routing fact or per-treatment repetition. Never pretend
        # the plain bank export is sufficient to execute the complete tree.
        bank_parent = parent if parent != "has_pain" else None
        question = InterviewQuestion(
            id="knee.tree." + field, text_fa=text,
            purpose_fa="تکمیل شرح‌حال گزارش‌شده برای بازبینی پزشک؛ این عبارت و اتصال منبع پیش‌نویس‌اند.",
            answer_type="yes_no" if field in BOOLEAN_FIELDS else "single_choice" if field in CHOICES else "text",
            choices=list(CHOICES.get(field, ())),
            depends_on_id="knee.tree." + bank_parent if bank_parent else None,
            show_when_answer_in=["yes"] if bank_parent else [],
        )
        nodes.append(InterviewTreeNode(
            number=number, field=field, question=question, stage=stage,
            conditions=(TreeCondition(field=parent, equals=True),) if parent else (),
            repeat_per_treatment=number in EPISODE_NUMBERS,
            requires_treatment_description=number in {26, 27},
            source_fact_keys=(fact_key,) if fact else (),
            source_content_sha256s=(fact.content_sha256,) if fact else (),
            book_bindings=(TreeBookBinding(candidate_key=BOOK_BINDINGS[number]),) if number in BOOK_BINDINGS else (),
            rationale_fa=("شناسهٔ سمت برای نظم شرح‌حال است و ادعای پزشکی یا منبع کتابی مستقل ندارد." if number == 2 else
                          "این اتصال، زمینهٔ تألیف سؤال برای رفع شکاف اطلاعات است؛ منبع، اعتبارسنجی عبارت دقیق پرسشنامه را اثبات نمی‌کند."),
            authorship="split_existing" if number in SPLIT_NUMBERS else "proposed_follow_up" if number in FOLLOW_UP_NUMBERS else "existing_reworded",
        ))
    entries = {entry.candidate_key: entry for entry in supplement.entries}
    book_sources = tuple(_source_reference(entries[key]) for key in sorted(set(BOOK_BINDINGS.values())))
    tree = KneeInterviewTree(
        bank=BankContent(
            title_fa="پیش‌نویس درخت ۳۰ سؤالی شرح‌حال زانو",
            scope_fa="نمای تألیف برای بازبینی پزشک؛ اجرا نیازمند شروط درخت، مشاهدهٔ صریح وجود درد و تفکیک هر درمان است؛ این بانک به‌تنهایی مصاحبهٔ فعال نیست.",
            questions=[node.question for node in nodes],
        ),
        nodes=tuple(nodes), base_pack_manifest_sha256=base.manifest_sha256,
        supplement_manifest_sha256=supplement.manifest_sha256,
        source_references=tuple(source for source in base.sources if source.source_key in used_sources),
        book_source_references=book_sources, tree_sha256="0" * 64,
    )
    return tree.model_copy(update={"tree_sha256": content_digest(tree.model_dump(mode="json", exclude={"tree_sha256"}))})


def _resolved(observations):
    # Reuse the existing source-preserving resolution policy rather than create
    # a second general answer/rule engine. Every input was strictly validated.
    return existing_questions._effective_answers(SimpleNamespace(observations=observations))


def build_interview_tree_preview(
    request: KneeInterviewTreePreviewRequest | Mapping,
    base_pack: KneeKnowledgePack | None = None,
    book_pack: KneeBookReviewPack | Mapping | None = None,
) -> KneeInterviewTreePreview:
    """Suggest missing Draft questions; preserve reports without interpreting text."""
    request = KneeInterviewTreePreviewRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, KneeInterviewTreePreviewRequest) else dict(request)
    )
    tree = build_interview_tree(base_pack, book_pack)
    context = request.context
    grouped, effective, reasons = _resolved(context.observations)
    _, effective_clinical, clinical_reasons = _resolved(context.clinical_findings)
    episode_resolutions = {episode.episode_ref: _resolved(episode.observations)
                           for episode in context.treatment_episodes}
    candidates = []
    gaps = []
    reviews = ["draft_tree_requires_independent_review", "existing_safety_engine_not_evaluated_by_preview",
               "book_population_applicability_not_assessed", "bank_export_requires_tree_routing_and_episode_constraints"]
    scopes = set(request.review_scopes)

    if context.body_region == "knee":
        if "laterality" in effective and effective["laterality"].value == "both":
            reviews.append("bilateral_history_requires_separate_side_contexts")
        # These fixed clinical-content dependencies also constrain which reports
        # can be used. Do not promote a dependent answer when its parent is
        # uncertain, or repair a false parent from the child's text/value.
        initial_effective = dict(effective)
        quarantine = {}
        for node in tree.nodes:
            if node.repeat_per_treatment or node.field not in initial_effective:
                continue
            for condition in node.conditions:
                parent = initial_effective.get(condition.field)
                child = initial_effective[node.field]
                if parent is not None and parent.value is True:
                    continue
                neutral = (child.value is False or (type(child.value) is int and child.value == 0)
                           or child.value == "none")
                if parent is not None and parent.value is False and not neutral:
                    quarantine[condition.field] = "contradictory"
                    quarantine[node.field] = "contradictory"
                    reviews.append("parent_child_conflict:" + condition.field + ":" + node.field)
                    if condition.field == "has_pain":
                        reviews.append("inconsistent_pain_presence_requires_physician_review")
                elif parent is None:
                    quarantine.setdefault(node.field, "incomplete")
                    reviews.append("dependent_answer_requires_parent_clarification:" + condition.field + ":" + node.field)
        for field, reason in quarantine.items():
            effective.pop(field, None)
            reasons[field] = reason

        prior = initial_effective.get("prior_treatment")
        for episode in context.treatment_episodes:
            _, episode_effective, episode_reasons = episode_resolutions[episode.episode_ref]
            if prior is None or prior.value is not True:
                reason = "contradictory" if prior is not None and prior.value is False else "incomplete"
                if episode_effective:
                    reviews.append("treatment_episode_requires_parent_clarification:" + episode.episode_ref)
                    if reason == "contradictory":
                        effective.pop("prior_treatment", None)
                        reasons["prior_treatment"] = "contradictory"
                    for field in tuple(episode_effective):
                        episode_effective.pop(field)
                        episode_reasons[field] = reason
            elif "treatment_description" not in episode_effective:
                for field in ("treatment_pain_response", "treatment_function_response"):
                    if field in episode_effective:
                        episode_effective.pop(field)
                        episode_reasons.setdefault(field, "incomplete")
                        reviews.append("treatment_outcome_requires_description_clarification:" + episode.episode_ref + ":" + field)

    def add(node, effective_answers, answer_reasons, episode_ref=None):
        if node.field in effective_answers:
            return
        reason = answer_reasons.get(node.field, "missing")
        gaps.append(TreeInformationGap(field=node.field, episode_ref=episode_ref, reason=reason,
                                       requires_physician_review=reason != "missing"))
        if reason != "missing":
            reviews.append(reason + ":" + node.field + (":" + episode_ref if episode_ref else ""))
        if reason in {"unknown", "declined"}:
            return
        clarify = reason in {"incomplete", "unverified", "contradictory"}
        candidates.append(InterviewTreeCandidate(
            number=node.number, field=node.field, question=node.question.model_copy(deep=True),
            episode_ref=episode_ref, action="physician_clarification" if clarify else "ask_missing",
            rule_id="knee.tree." + node.field,
            source_fact_keys=node.source_fact_keys, source_content_sha256s=node.source_content_sha256s,
            book_candidate_keys=tuple(binding.candidate_key for binding in node.book_bindings
                                      if binding.required_scope in scopes),
            rationale_fa=("پاسخ موجود نیازمند روشن‌سازی پزشک است؛ پاسخ قبلی حفظ شده است." if clarify else
                          "این داده ثبت نشده است؛ سؤال در شاخهٔ مربوط و با حفظ سایر پاسخ‌ها پیشنهاد می‌شود."),
        ))

    if context.body_region != "knee":
        reviews.append("outside_knee_scope" if context.body_region == "other" else "body_region_requires_physician_clarification")
    else:
        if "has_pain" not in effective:
            reason = reasons.get("has_pain", "missing")
            gaps.append(TreeInformationGap(field="has_pain", reason=reason, requires_physician_review=True))
            reviews.append("needs_pain_presence_clarification")
        for field, reason in reasons.items():
            if field == "has_pain":
                reviews.append(reason + ":has_pain")
        # No inference from main complaint, medication names, imaging severity,
        # or free text establishes pain presence or a clinical diagnosis.
        for node in tree.nodes:
            if any(condition.field not in effective or effective[condition.field].value is not condition.equals
                   for condition in node.conditions):
                continue
            if node.number not in EPISODE_NUMBERS:
                add(node, effective, reasons)
                continue
            if not context.treatment_episodes:
                if node.number == 25:
                    add(node, {}, {})
                    reviews.append("treatment_episode_capture_required")
                continue
            for episode in context.treatment_episodes:
                _, episode_effective, episode_reasons = episode_resolutions[episode.episode_ref]
                if node.requires_treatment_description and "treatment_description" not in episode_effective:
                    continue
                add(node, episode_effective, episode_reasons, episode.episode_ref)

        if context.treatment_episodes and not ("prior_treatment" in effective and effective["prior_treatment"].value is True):
            reviews.append("treatment_episodes_require_prior_treatment_clarification")
        # Preserve uncertainty even in branches not opened by a complete parent.
        # A blocked child must never disappear from the physician review view.
        for field, reason in reasons.items():
            if not any(gap.field == field and gap.episode_ref is None for gap in gaps):
                gaps.append(TreeInformationGap(field=field, reason=reason, requires_physician_review=True))
            reviews.append(reason + ":" + field)
        for episode in context.treatment_episodes:
            _, _, episode_reasons = episode_resolutions[episode.episode_ref]
            for field, reason in episode_reasons.items():
                if not any(gap.field == field and gap.episode_ref == episode.episode_ref for gap in gaps):
                    gaps.append(TreeInformationGap(field=field, episode_ref=episode.episode_ref,
                                                   reason=reason, requires_physician_review=True))
                reviews.append(reason + ":" + field + ":" + episode.episode_ref)
        for field, reason in clinical_reasons.items():
            gaps.append(TreeInformationGap(field=field, reason=reason, requires_physician_review=True))
            reviews.append(reason + ":" + field)
        # Risk-information review prompts remain Draft authoring output. These
        # neither execute nor replace the existing Clinical Safety Rule Engine.
        positives = {item.field for item in context.observations if item.value is True}
        if {"fever", "acute_swelling"} <= positives:
            reviews.append("draft_hot_joint_information_requires_prompt_physician_review")
        if "systemic_symptoms" in positives:
            reviews.append("draft_systemic_symptom_information_requires_physician_review")
        if "trauma" in positives and positives & {"sensory_change", "weakness", "foot_coldness", "foot_color_change"}:
            reviews.append("draft_neurovascular_trauma_information_requires_prompt_physician_review")
        elif positives & {"sensory_change", "weakness", "foot_coldness", "foot_color_change"}:
            reviews.append("neurovascular_report_requires_trauma_context_physician_review")
        if ("has_pain" in effective and effective["has_pain"].value is False
                and any(item.field == "pain_score_now" and type(item.value) is int and item.value > 0
                        for item in context.observations)):
            reviews.append("inconsistent_pain_presence_requires_physician_review")
        if {"trauma", "mechanical_locking"} <= positives:
            reviews.append("draft_traumatic_motion_block_information_requires_physician_review")

    selected_book_keys = {key for candidate in candidates for key in candidate.book_candidate_keys}
    structured = tuple(item for item in context.observations if item.field in effective and item.state == "confirmed")
    unverified = tuple(item for item in context.observations if item.field not in effective or item.state != "confirmed")
    usable_clinical = tuple(item for item in context.clinical_findings
                            if item.field in effective_clinical and item.state == "confirmed")
    rules_sha = content_digest({
        "version": RULE_VERSION, "tree_sha256": tree.tree_sha256,
        "selector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(Path(tree_schema.__file__).read_bytes()).hexdigest(),
        "existing_resolver_sha256": hashlib.sha256(Path(existing_questions.__file__).read_bytes()).hexdigest(),
        "selection_policy": "typed-explicit-branches;missing-only;preserve-unknown-declined;clarify-conflicts;per-treatment;no-nlp-no-clearance-v1",
    })
    result = KneeInterviewTreePreview(
        tree=tree, context=context, review_scopes=request.review_scopes,
        question_candidates=tuple(candidates), information_gaps=tuple(gaps),
        structured_answers=structured, unverified_answers=unverified,
        clinical_findings=context.clinical_findings, usable_clinical_findings=usable_clinical,
        source_references=tree.source_references,
        book_source_references=tuple(source for source in tree.book_source_references
                                     if source.candidate_key in selected_book_keys),
        review_reasons=tuple(dict.fromkeys(reviews)),
        request_sha256=content_digest(request.model_dump(mode="json")), rules_sha256=rules_sha,
        result_sha256="0" * 64,
    )
    return result.model_copy(update={"result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))})
