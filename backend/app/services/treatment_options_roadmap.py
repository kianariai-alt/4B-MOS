"""Transparent local-outcome treatment options for independent physician review."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from math import sqrt
from statistics import median

from sqlalchemy.orm import Session

from backend.app.models.patient import Patient
from backend.app.models.treatment_outcome import TreatmentOutcome
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.treatment_outcome import TreatmentOutcomeRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.protocol import ProtocolRead
from backend.app.schemas.treatment_options_roadmap import (
    RoadmapCohortDefinitionRead,
    RoadmapExclusionSummaryRead,
    RoadmapFollowUpWindowRead,
    RoadmapMetricRead,
    RoadmapOutcomeDistributionRead,
    RoadmapTargetProfileRead,
    TreatmentOptionRead,
    TreatmentOptionsRoadmapRead,
)
from backend.app.services.clinical_context import (
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.clinical_safety_review import (
    ClinicalSafetyFindingReviewService,
)
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.treatment_outcome import (
    TreatmentOutcomeIntegrityError,
    TreatmentOutcomeService,
)


MIN_REPORTABLE_UNIQUE_PATIENTS = 5
MAX_AGE_DIFFERENCE_YEARS = 15
MAX_BASELINE_PAIN_DIFFERENCE = 3
FOLLOW_UP_WINDOWS = (
    ("early_28_to_70_days", 28, 70, 49),
    ("intermediate_71_to_180_days", 71, 180, 126),
    ("long_term_181_to_365_days", 181, 365, 273),
)
ROADMAP_STEPS = [
    "verify_current_safety_review",
    "review_local_observational_cohort",
    "review_external_evidence_independently",
    "physician_select_modify_or_reject_options",
    "document_clinical_rationale",
]
KNOWN_LIMITATIONS = [
    "Local outcomes are observational and cannot establish that a treatment "
    "caused an observed result.",
    "The cohort is defined by a small set of structured variables and does not "
    "claim full biological or prognostic similarity between patients.",
    "Confounding, selection bias, concomitant care, missing follow-up, outcome "
    "measurement quality and protocol drift may distort local comparisons.",
    "A protocol is shown only when an active exact code/version exists and at "
    "least one follow-up window meets the minimum unique-patient threshold.",
    "Options are ordered by protocol code/version, never by apparent benefit, "
    "rating, adverse-event frequency or any composite score.",
    "External evidence is not automatically inferred from local outcomes and "
    "must be reviewed independently by the physician.",
]


class TreatmentRoadmapNotFoundError(Exception):
    pass


class TreatmentRoadmapConflictError(Exception):
    pass


class TreatmentRoadmapIntegrityError(Exception):
    pass


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_years(date_of_birth: date | None, on_date: date) -> int | None:
    if date_of_birth is None or date_of_birth > on_date:
        return None
    return (
        on_date.year
        - date_of_birth.year
        - (
            (on_date.month, on_date.day)
            < (date_of_birth.month, date_of_birth.day)
        )
    )


def _duration_band(
    symptom_onset_date: date | None,
    visit_date: date,
) -> str:
    if symptom_onset_date is None or symptom_onset_date > visit_date:
        return "unknown"
    days = (visit_date - symptom_onset_date).days
    if days < 90:
        return "acute_under_90_days"
    if days <= 180:
        return "subacute_90_to_180_days"
    return "chronic_over_180_days"


def _laterality_group(value: str | None) -> str:
    if value in {"left", "right"}:
        return "unilateral"
    if value == "bilateral":
        return "bilateral"
    if value in {"midline", "not_applicable"}:
        return "midline_or_not_applicable"
    return "unknown"


def _window_for_day(day: int) -> tuple[str, int] | None:
    for name, low, high, midpoint in FOLLOW_UP_WINDOWS:
        if low <= day <= high:
            return name, midpoint
    return None


def _data_volume(count: int) -> str:
    if count < MIN_REPORTABLE_UNIQUE_PATIENTS:
        return "insufficient"
    if count < 10:
        return "very_limited"
    if count < 30:
        return "limited"
    if count < 100:
        return "moderate"
    return "substantial"


def _metric(
    values: list[float],
    *,
    reducer,
) -> RoadmapMetricRead:
    denominator = len(values)
    reportable = denominator >= MIN_REPORTABLE_UNIQUE_PATIENTS
    return RoadmapMetricRead(
        value=(
            round(float(reducer(values)), 4)
            if reportable
            else None
        ),
        denominator=denominator,
        minimum_denominator=MIN_REPORTABLE_UNIQUE_PATIENTS,
        suppressed_for_small_n=not reportable,
    )


def _proportion_metric(successes: int, denominator: int) -> RoadmapMetricRead:
    reportable = denominator >= MIN_REPORTABLE_UNIQUE_PATIENTS
    return RoadmapMetricRead(
        value=(
            round(successes / denominator, 4)
            if reportable and denominator
            else None
        ),
        denominator=denominator,
        minimum_denominator=MIN_REPORTABLE_UNIQUE_PATIENTS,
        suppressed_for_small_n=not reportable,
    )


def _wilson_interval(successes: int, denominator: int) -> tuple[float, float] | None:
    if denominator < MIN_REPORTABLE_UNIQUE_PATIENTS:
        return None
    z = 1.96
    proportion = successes / denominator
    z2 = z * z
    denominator_term = 1 + z2 / denominator
    center = (
        proportion + z2 / (2 * denominator)
    ) / denominator_term
    half = (
        z
        * sqrt(
            proportion * (1 - proportion) / denominator
            + z2 / (4 * denominator * denominator)
        )
        / denominator_term
    )
    return (
        round(max(0.0, center - half), 4),
        round(min(1.0, center + half), 4),
    )


class TreatmentOptionsRoadmapService:
    @staticmethod
    def _require_visit(db: Session, visit_id: str):
        visit = VisitRepository.get_by_id(db, visit_id)
        if visit is None:
            raise TreatmentRoadmapNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        patient = db.get(Patient, visit.patient_id)
        if patient is None:
            raise TreatmentRoadmapIntegrityError(
                "The target visit references a missing patient."
            )
        return visit, patient

    @staticmethod
    def _target_profile(
        db: Session,
        visit_id: str,
    ) -> tuple[RoadmapTargetProfileRead, object, object, object]:
        visit, patient = TreatmentOptionsRoadmapService._require_visit(
            db,
            visit_id,
        )
        try:
            context = ClinicalContextService.get_current_context(db, visit_id)
        except ClinicalContextNotFoundError as error:
            raise TreatmentRoadmapNotFoundError(str(error)) from error
        except ClinicalContextIntegrityError as error:
            raise TreatmentRoadmapIntegrityError(str(error)) from error

        if context.intake is None:
            raise TreatmentRoadmapConflictError(
                "A final structured clinical intake is required before "
                "building a treatment options roadmap."
            )
        body_region = context.intake.body_region or visit.body_region
        if not body_region or not _normalize_text(body_region):
            raise TreatmentRoadmapConflictError(
                "A structured body region is required before building a "
                "treatment options roadmap."
            )

        visit_date = _as_utc(visit.visit_date).date()
        profile = RoadmapTargetProfileRead(
            clinical_context_sha256=clinical_context_digest(context),
            body_region=body_region,
            age_years=_age_years(patient.date_of_birth, visit_date),
            baseline_pain_score=context.intake.pain_score,
            symptom_duration_band=_duration_band(
                context.intake.symptom_onset_date,
                visit_date,
            ),
            laterality_group=_laterality_group(context.intake.laterality),
        )
        return profile, visit, patient, context

    @staticmethod
    def _cohort_definition(
        target: RoadmapTargetProfileRead,
    ) -> RoadmapCohortDefinitionRead:
        return RoadmapCohortDefinitionRead(
            maximum_age_difference_years=(
                MAX_AGE_DIFFERENCE_YEARS
                if target.age_years is not None
                else None
            ),
            maximum_baseline_pain_difference=(
                MAX_BASELINE_PAIN_DIFFERENCE
                if target.baseline_pain_score is not None
                else None
            ),
            symptom_duration_band_required_when_target_known=(
                target.symptom_duration_band != "unknown"
            ),
            laterality_group_required_when_target_known=(
                target.laterality_group != "unknown"
            ),
            minimum_reportable_unique_patients=(
                MIN_REPORTABLE_UNIQUE_PATIENTS
            ),
            follow_up_windows=[
                item[0] for item in FOLLOW_UP_WINDOWS
            ],
        )

    @staticmethod
    def _empty_exclusions() -> RoadmapExclusionSummaryRead:
        return RoadmapExclusionSummaryRead(
            candidate_outcome_records=0,
            excluded_current_patient=0,
            excluded_body_region_mismatch=0,
            excluded_unreproducible_context=0,
            excluded_missing_required_similarity_data=0,
            excluded_similarity_mismatch=0,
            excluded_missing_or_inactive_protocol=0,
            excluded_outside_follow_up_window=0,
            duplicate_patient_protocol_window_observations_not_used=0,
        )

    @staticmethod
    def _safety_status(db: Session, visit_id: str) -> tuple[str, int, int]:
        inbox = ClinicalSafetyFindingReviewService.get_inbox(db, visit_id)
        if inbox.evaluation is None:
            return "missing", 0, 0
        if inbox.evaluation_matches_current_context is not True:
            return "stale", len(inbox.findings), len(inbox.findings)
        unresolved = sum(
            1
            for item in inbox.findings
            if item.timeline.review_status != "assessed"
        )
        if unresolved:
            return "pending_review", len(inbox.findings), unresolved
        return "current", len(inbox.findings), 0

    @staticmethod
    def _hash_response_fields(
        *,
        visit_id: str,
        status: str,
        target_profile,
        safety_status: str,
        safety_finding_count: int,
        safety_unresolved_count: int,
        cohort_definition,
        exclusions,
        matched_unique_patient_count: int,
        options,
    ) -> str:
        return evidence_digest(
            {
                "schema_version": 1,
                "visit_id": visit_id,
                "roadmap_status": status,
                "target_profile": target_profile.model_dump(mode="json"),
                "safety_evaluation_status": safety_status,
                "safety_finding_count": safety_finding_count,
                "safety_unresolved_finding_count": safety_unresolved_count,
                "cohort_definition": cohort_definition.model_dump(mode="json"),
                "exclusions": exclusions.model_dump(mode="json"),
                "matched_unique_patient_count": matched_unique_patient_count,
                "options": [
                    item.model_dump(mode="json")
                    for item in options
                ],
                "known_limitations": KNOWN_LIMITATIONS,
                "roadmap_steps": ROADMAP_STEPS,
                "local_outcomes_are_observational": True,
                "local_outcomes_establish_causality": False,
                "ranks_treatments": False,
                "is_final_treatment_recommendation": False,
                "is_clinical_clearance": False,
                "requires_independent_physician_review": True,
            }
        )

    @staticmethod
    def _blocked_response(
        *,
        visit_id: str,
        target_profile: RoadmapTargetProfileRead,
        safety_status: str,
        safety_finding_count: int,
        safety_unresolved_count: int,
    ) -> TreatmentOptionsRoadmapRead:
        status = {
            "missing": "blocked_pending_safety_evaluation",
            "stale": "blocked_stale_safety_evaluation",
            "pending_review": "blocked_pending_safety_review",
        }[safety_status]
        cohort_definition = TreatmentOptionsRoadmapService._cohort_definition(
            target_profile
        )
        exclusions = TreatmentOptionsRoadmapService._empty_exclusions()
        roadmap_sha256 = TreatmentOptionsRoadmapService._hash_response_fields(
            visit_id=visit_id,
            status=status,
            target_profile=target_profile,
            safety_status=safety_status,
            safety_finding_count=safety_finding_count,
            safety_unresolved_count=safety_unresolved_count,
            cohort_definition=cohort_definition,
            exclusions=exclusions,
            matched_unique_patient_count=0,
            options=[],
        )
        return TreatmentOptionsRoadmapRead(
            visit_id=visit_id,
            generated_at=datetime.now(timezone.utc),
            roadmap_status=status,
            target_profile=target_profile,
            safety_evaluation_status=safety_status,
            safety_finding_count=safety_finding_count,
            safety_unresolved_finding_count=safety_unresolved_count,
            cohort_definition=cohort_definition,
            exclusions=exclusions,
            matched_unique_patient_count=0,
            matched_unique_patient_count_display="0",
            options=[],
            known_limitations=list(KNOWN_LIMITATIONS),
            roadmap_steps=list(ROADMAP_STEPS),
            roadmap_sha256=roadmap_sha256,
        )

    @staticmethod
    def _historical_profile(
        db: Session,
        outcome,
    ) -> tuple[str, int | None, int | None, str, str, str]:
        visit = VisitRepository.get_by_id(db, outcome.visit_id)
        if visit is None:
            raise TreatmentRoadmapIntegrityError(
                "A treatment outcome references a missing visit."
            )
        patient = db.get(Patient, visit.patient_id)
        if patient is None:
            raise TreatmentRoadmapIntegrityError(
                "A treatment outcome references a visit with no patient."
            )
        try:
            context = ClinicalContextService.get_current_context(
                db,
                outcome.visit_id,
            )
        except (
            ClinicalContextNotFoundError,
            ClinicalContextIntegrityError,
        ) as error:
            raise TreatmentRoadmapIntegrityError(str(error)) from error
        if context.intake is None:
            return (
                visit.patient_id,
                None,
                None,
                "unknown",
                "unknown",
                "unreproducible",
            )
        if clinical_context_digest(context) != outcome.clinical_context_sha256:
            return (
                visit.patient_id,
                None,
                None,
                "unknown",
                "unknown",
                "unreproducible",
            )
        visit_date = _as_utc(visit.visit_date).date()
        return (
            visit.patient_id,
            _age_years(patient.date_of_birth, visit_date),
            context.intake.pain_score,
            _duration_band(
                context.intake.symptom_onset_date,
                visit_date,
            ),
            _laterality_group(context.intake.laterality),
            "reproducible",
        )

    @staticmethod
    def _window_summary(
        window_name: str,
        matches: list[dict],
    ) -> RoadmapFollowUpWindowRead:
        count = len(matches)
        reportable = count >= MIN_REPORTABLE_UNIQUE_PATIENTS
        statuses = Counter(
            item["outcome"].outcome_status
            for item in matches
        )
        known_outcomes = [
            item["outcome"]
            for item in matches
            if item["outcome"].outcome_status != "unknown"
        ]
        improved_count = sum(
            1
            for item in known_outcomes
            if item.outcome_status == "improved"
        )
        improvement_metric = _proportion_metric(
            improved_count,
            len(known_outcomes),
        )
        interval = _wilson_interval(
            improved_count,
            len(known_outcomes),
        )

        patient_ratings = [
            float(item["outcome"].patient_rating)
            for item in matches
            if item["outcome"].patient_rating is not None
        ]
        physician_ratings = [
            float(item["outcome"].physician_rating)
            for item in matches
            if item["outcome"].physician_rating is not None
        ]
        pain_changes = [
            float(
                item["baseline_pain"]
                - item["outcome"].pain_score
            )
            for item in matches
            if (
                item["baseline_pain"] is not None
                and item["outcome"].pain_score is not None
            )
        ]
        function_scores = [
            float(item["outcome"].function_score)
            for item in matches
            if item["outcome"].function_score is not None
        ]
        documented_adverse_events = sum(
            1
            for item in matches
            if item["outcome"].adverse_events
        )
        adverse_metric = _proportion_metric(
            documented_adverse_events,
            count,
        )

        return RoadmapFollowUpWindowRead(
            window=window_name,
            unique_patient_count=count,
            unique_patient_count_display=str(count),
            local_data_volume=_data_volume(count),
            median_follow_up_day=(
                round(
                    float(median([
                        item["outcome"].follow_up_day
                        for item in matches
                    ])),
                    1,
                )
                if reportable
                else None
            ),
            outcome_distribution=(
                RoadmapOutcomeDistributionRead(
                    improved=statuses.get("improved", 0),
                    unchanged=statuses.get("unchanged", 0),
                    worsened=statuses.get("worsened", 0),
                    mixed=statuses.get("mixed", 0),
                    unknown=statuses.get("unknown", 0),
                )
                if reportable
                else None
            ),
            observed_improvement_proportion=improvement_metric,
            observed_improvement_wilson_95_low=(
                interval[0] if interval else None
            ),
            observed_improvement_wilson_95_high=(
                interval[1] if interval else None
            ),
            median_patient_rating=_metric(
                patient_ratings,
                reducer=median,
            ),
            median_physician_rating=_metric(
                physician_ratings,
                reducer=median,
            ),
            median_pain_change=_metric(
                pain_changes,
                reducer=median,
            ),
            median_function_score=_metric(
                function_scores,
                reducer=median,
            ),
            documented_adverse_event_proportion=adverse_metric,
            source_outcome_sha256s=(
                sorted(
                    item["outcome"].sha256
                    for item in matches
                )
                if reportable
                else []
            ),
        )

    @staticmethod
    def get_roadmap(
        db: Session,
        visit_id: str,
    ) -> TreatmentOptionsRoadmapRead:
        (
            target,
            target_visit,
            target_patient,
            _target_context,
        ) = TreatmentOptionsRoadmapService._target_profile(
            db,
            visit_id,
        )
        safety_status, finding_count, unresolved_count = (
            TreatmentOptionsRoadmapService._safety_status(
                db,
                visit_id,
            )
        )
        if safety_status != "current":
            return TreatmentOptionsRoadmapService._blocked_response(
                visit_id=visit_id,
                target_profile=target,
                safety_status=safety_status,
                safety_finding_count=finding_count,
                safety_unresolved_count=unresolved_count,
            )

        active_protocols = {
            (item.code, item.version): item
            for item in ProtocolRepository.list(db)
            if item.is_active
        }
        exclusions = {
            "candidate_outcome_records": 0,
            "excluded_current_patient": 0,
            "excluded_body_region_mismatch": 0,
            "excluded_unreproducible_context": 0,
            "excluded_missing_required_similarity_data": 0,
            "excluded_similarity_mismatch": 0,
            "excluded_missing_or_inactive_protocol": 0,
            "excluded_outside_follow_up_window": 0,
            "duplicate_patient_protocol_window_observations_not_used": 0,
        }
        target_region = _normalize_text(target.body_region)
        matched: list[dict] = []

        for record in TreatmentOutcomeRepository.list_for_roadmap(db):
            exclusions["candidate_outcome_records"] += 1
            try:
                outcome = TreatmentOutcomeService._to_read(db, record)
            except TreatmentOutcomeIntegrityError as error:
                raise TreatmentRoadmapIntegrityError(str(error)) from error

            historical_visit = VisitRepository.get_by_id(
                db,
                outcome.visit_id,
            )
            if historical_visit is None:
                raise TreatmentRoadmapIntegrityError(
                    "A treatment outcome references a missing visit."
                )
            if historical_visit.patient_id == target_patient.id:
                exclusions["excluded_current_patient"] += 1
                continue
            if _normalize_text(outcome.body_region) != target_region:
                exclusions["excluded_body_region_mismatch"] += 1
                continue

            window = _window_for_day(outcome.follow_up_day)
            if window is None:
                exclusions["excluded_outside_follow_up_window"] += 1
                continue

            protocol_key = (
                outcome.protocol_code,
                outcome.protocol_version,
            )
            if (
                outcome.protocol_code is None
                or outcome.protocol_version is None
                or protocol_key not in active_protocols
            ):
                exclusions["excluded_missing_or_inactive_protocol"] += 1
                continue
            protocol = active_protocols[protocol_key]
            if protocol.treatment_type != outcome.treatment_type:
                raise TreatmentRoadmapIntegrityError(
                    "An outcome treatment type conflicts with its active "
                    "protocol code/version."
                )

            (
                patient_id,
                age_years,
                baseline_pain,
                duration_band,
                laterality_group,
                reproducibility,
            ) = TreatmentOptionsRoadmapService._historical_profile(
                db,
                outcome,
            )
            if reproducibility != "reproducible":
                exclusions["excluded_unreproducible_context"] += 1
                continue

            missing_required = (
                (target.age_years is not None and age_years is None)
                or (
                    target.baseline_pain_score is not None
                    and baseline_pain is None
                )
                or (
                    target.symptom_duration_band != "unknown"
                    and duration_band == "unknown"
                )
                or (
                    target.laterality_group != "unknown"
                    and laterality_group == "unknown"
                )
            )
            if missing_required:
                exclusions[
                    "excluded_missing_required_similarity_data"
                ] += 1
                continue

            mismatch = False
            if (
                target.age_years is not None
                and age_years is not None
                and abs(target.age_years - age_years)
                > MAX_AGE_DIFFERENCE_YEARS
            ):
                mismatch = True
            if (
                target.baseline_pain_score is not None
                and baseline_pain is not None
                and abs(
                    target.baseline_pain_score - baseline_pain
                ) > MAX_BASELINE_PAIN_DIFFERENCE
            ):
                mismatch = True
            if (
                target.symptom_duration_band != "unknown"
                and duration_band != target.symptom_duration_band
            ):
                mismatch = True
            if (
                target.laterality_group != "unknown"
                and laterality_group != target.laterality_group
            ):
                mismatch = True
            if mismatch:
                exclusions["excluded_similarity_mismatch"] += 1
                continue

            matched.append(
                {
                    "outcome": outcome,
                    "patient_id": patient_id,
                    "baseline_pain": baseline_pain,
                    "protocol": protocol,
                    "window": window[0],
                    "window_midpoint": window[1],
                }
            )

        selected: dict[tuple[str, str, str, str], dict] = {}
        for item in matched:
            outcome = item["outcome"]
            key = (
                item["patient_id"],
                outcome.protocol_code,
                outcome.protocol_version,
                item["window"],
            )
            existing = selected.get(key)

            def choice_key(candidate: dict) -> tuple:
                candidate_outcome = candidate["outcome"]
                return (
                    abs(
                        candidate_outcome.follow_up_day
                        - candidate["window_midpoint"]
                    ),
                    -_as_utc(candidate_outcome.recorded_at).timestamp(),
                    candidate_outcome.sha256,
                )

            if existing is None or choice_key(item) < choice_key(existing):
                if existing is not None:
                    exclusions[
                        "duplicate_patient_protocol_window_observations_not_used"
                    ] += 1
                selected[key] = item
            else:
                exclusions[
                    "duplicate_patient_protocol_window_observations_not_used"
                ] += 1

        grouped: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for item in selected.values():
            outcome = item["outcome"]
            grouped[
                (outcome.protocol_code, outcome.protocol_version)
            ][item["window"]].append(item)

        options: list[TreatmentOptionRead] = []
        for protocol_key in sorted(grouped):
            protocol = active_protocols[protocol_key]
            window_map = grouped[protocol_key]
            windows = [
                TreatmentOptionsRoadmapService._window_summary(
                    name,
                    window_map.get(name, []),
                )
                for name, _low, _high, _midpoint in FOLLOW_UP_WINDOWS
            ]
            reportable_count = sum(
                1
                for item in windows
                if (
                    item.unique_patient_count is not None
                    and item.unique_patient_count
                    >= MIN_REPORTABLE_UNIQUE_PATIENTS
                )
            )
            if not reportable_count:
                continue
            options.append(
                TreatmentOptionRead(
                    protocol=ProtocolRead.model_validate(protocol),
                    treatment_type=protocol.treatment_type,
                    protocol_code=protocol.code,
                    protocol_version=protocol.version,
                    body_region=target.body_region,
                    windows=windows,
                    reportable_window_count=reportable_count,
                    rationale_codes=[
                        "active_protocol",
                        "same_body_region_local_outcomes",
                        "deterministically_matched_local_cohort",
                        "minimum_cohort_threshold_met",
                    ],
                )
            )

        matched_unique_patient_count = len(
            {item["patient_id"] for item in matched}
        )
        status = (
            "options_available"
            if options
            else "insufficient_local_data"
        )
        cohort_definition = TreatmentOptionsRoadmapService._cohort_definition(
            target
        )
        exclusion_model = RoadmapExclusionSummaryRead(**exclusions)
        roadmap_sha256 = TreatmentOptionsRoadmapService._hash_response_fields(
            visit_id=visit_id,
            status=status,
            target_profile=target,
            safety_status=safety_status,
            safety_finding_count=finding_count,
            safety_unresolved_count=unresolved_count,
            cohort_definition=cohort_definition,
            exclusions=exclusion_model,
            matched_unique_patient_count=matched_unique_patient_count,
            options=options,
        )

        return TreatmentOptionsRoadmapRead(
            visit_id=visit_id,
            generated_at=datetime.now(timezone.utc),
            roadmap_status=status,
            target_profile=target,
            safety_evaluation_status=safety_status,
            safety_finding_count=finding_count,
            safety_unresolved_finding_count=unresolved_count,
            cohort_definition=cohort_definition,
            exclusions=exclusion_model,
            matched_unique_patient_count=matched_unique_patient_count,
            matched_unique_patient_count_display=str(
                matched_unique_patient_count
            ),
            options=options,
            known_limitations=list(KNOWN_LIMITATIONS),
            roadmap_steps=list(ROADMAP_STEPS),
            roadmap_sha256=roadmap_sha256,
        )
