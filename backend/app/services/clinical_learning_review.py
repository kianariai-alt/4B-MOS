"""Read-only clinical learning data-quality review.

This module audits whether the local decision -> treatment -> outcome dataset is
mature enough for transparent cohort review. It deliberately avoids producing
a cross-protocol effectiveness score or treatment ranking.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.treatment_decision import (
    TreatmentDecisionRepository,
)
from backend.app.repositories.treatment_outcome import (
    TreatmentOutcomeRepository,
)
from backend.app.schemas.clinical_learning_review import (
    ClinicalLearningReviewRead,
    FieldCoverageRead,
    LearningDataQualityRead,
    LearningFollowUpCountsRead,
    ProtocolLearningReviewRead,
)
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.treatment_decision import (
    TreatmentDecisionIntegrityError,
    TreatmentDecisionService,
)
from backend.app.services.treatment_outcome import (
    TreatmentOutcomeIntegrityError,
    TreatmentOutcomeService,
)


MIN_LEARNING_CASES = 5
ACTIONABLE_DECISION_TYPES = {
    "select_option",
    "modify_option",
    "combine_options",
    "choose_outside_roadmap",
}


class ClinicalLearningIntegrityError(Exception):
    pass


def _coverage(present_count: int, total_count: int) -> FieldCoverageRead:
    return FieldCoverageRead(
        present_count=present_count,
        total_count=total_count,
        proportion=(
            round(present_count / total_count, 4)
            if total_count
            else None
        ),
    )


def _data_volume(case_count: int) -> str:
    if case_count < MIN_LEARNING_CASES:
        return "insufficient"
    if case_count < 10:
        return "very_limited"
    if case_count < 30:
        return "limited"
    if case_count < 100:
        return "moderate"
    return "substantial"


def _follow_up_bucket(day: int) -> str:
    if 28 <= day <= 70:
        return "early_28_to_70_days"
    if 71 <= day <= 180:
        return "intermediate_71_to_180_days"
    if 181 <= day <= 365:
        return "long_term_181_to_365_days"
    return "outside_standard_windows"


class ClinicalLearningReviewService:
    @staticmethod
    def get_review(db: Session) -> ClinicalLearningReviewRead:
        protocols = ProtocolRepository.list(db)
        protocol_map = {
            (item.code, item.version): item
            for item in protocols
        }

        decision_records = TreatmentDecisionRepository.list_all(db)
        validated_decisions = []
        latest_by_visit = {}
        decision_by_id = {}
        decision_payload_by_id = {}
        for record in decision_records:
            try:
                payload = TreatmentDecisionService._validate(db, record)
            except TreatmentDecisionIntegrityError as error:
                raise ClinicalLearningIntegrityError(str(error)) from error
            validated_decisions.append((record, payload))
            decision_by_id[record.id] = record
            decision_payload_by_id[record.id] = payload
            current = latest_by_visit.get(record.visit_id)
            candidate_key = (record.decided_at, record.id)
            if current is None or candidate_key > (
                current.decided_at,
                current.id,
            ):
                latest_by_visit[record.visit_id] = record

        current_decision_ids = {
            record.id for record in latest_by_visit.values()
        }

        treatments = TreatmentRepository.list_all(db)
        treatment_by_id = {item.id: item for item in treatments}
        protocol_treatment_ids = defaultdict(set)
        protocol_linked_treatment_ids = defaultdict(set)
        decision_linked_treatment_count = 0
        legacy_or_unlinked_treatment_count = 0

        for treatment in treatments:
            snapshot = treatment.protocol_snapshot or {}
            code = snapshot.get("code")
            version = treatment.protocol_version
            if code is not None and version is not None:
                protocol_key = (code, version)
                registered = protocol_map.get(protocol_key)
                if registered is None:
                    raise ClinicalLearningIntegrityError(
                        "A versioned treatment references a protocol that is "
                        "missing from the protocol registry."
                    )
                if (
                    registered.treatment_type != treatment.treatment_type
                    or snapshot.get("version") != version
                    or snapshot.get("treatment_type")
                    != treatment.treatment_type
                ):
                    raise ClinicalLearningIntegrityError(
                        "A treatment protocol snapshot conflicts with the "
                        "registered protocol identity."
                    )
                protocol_treatment_ids[protocol_key].add(treatment.id)

            if treatment.source_treatment_decision_id is None:
                legacy_or_unlinked_treatment_count += 1
                continue

            decision_linked_treatment_count += 1
            decision = decision_by_id.get(
                treatment.source_treatment_decision_id
            )
            if decision is None:
                raise ClinicalLearningIntegrityError(
                    "A treatment references a missing clinician decision."
                )
            if (
                treatment.source_treatment_decision_sha256
                != decision.sha256
            ):
                raise ClinicalLearningIntegrityError(
                    "A treatment decision hash does not match its immutable "
                    "clinician decision."
                )
            decision_payload = decision_payload_by_id[decision.id]
            if code is None or version is None:
                raise ClinicalLearningIntegrityError(
                    "A Decision-linked treatment must freeze an exact "
                    "protocol code and version."
                )
            selected = {
                (
                    item.protocol_code,
                    item.protocol_version,
                    item.treatment_type,
                )
                for item in decision_payload.selected_protocols
            }
            if (
                code,
                version,
                treatment.treatment_type,
            ) not in selected:
                raise ClinicalLearningIntegrityError(
                    "A Decision-linked treatment protocol is not present in "
                    "the immutable clinician decision."
                )
            protocol_linked_treatment_ids[(code, version)].add(
                treatment.id
            )

        outcome_records = TreatmentOutcomeRepository.list_for_roadmap(db)
        validated_outcomes = []
        protocol_outcomes = defaultdict(list)
        treatments_with_outcomes = set()

        for record in outcome_records:
            try:
                outcome = TreatmentOutcomeService._to_read(db, record)
            except TreatmentOutcomeIntegrityError as error:
                raise ClinicalLearningIntegrityError(str(error)) from error
            treatment = treatment_by_id.get(outcome.treatment_id)
            if treatment is None:
                raise ClinicalLearningIntegrityError(
                    "An outcome references a missing treatment."
                )
            treatment_snapshot = treatment.protocol_snapshot or {}
            if (
                outcome.protocol_code != treatment_snapshot.get("code")
                or outcome.protocol_version != treatment.protocol_version
                or outcome.treatment_type != treatment.treatment_type
            ):
                raise ClinicalLearningIntegrityError(
                    "An outcome protocol identity conflicts with its "
                    "current immutable treatment provenance."
                )
            validated_outcomes.append(outcome)
            treatments_with_outcomes.add(outcome.treatment_id)

            if (
                outcome.protocol_code is not None
                and outcome.protocol_version is not None
            ):
                protocol_key = (
                    outcome.protocol_code,
                    outcome.protocol_version,
                )
                registered = protocol_map.get(protocol_key)
                if registered is None:
                    raise ClinicalLearningIntegrityError(
                        "An outcome references a protocol version missing "
                        "from the protocol registry."
                    )
                if registered.treatment_type != outcome.treatment_type:
                    raise ClinicalLearningIntegrityError(
                        "An outcome treatment type conflicts with its "
                        "registered protocol."
                    )
                protocol_outcomes[protocol_key].append(outcome)

        decision_event_refs = defaultdict(int)
        current_decision_refs = defaultdict(int)
        for record, payload in validated_decisions:
            for reference in payload.selected_protocols:
                key = (
                    reference.protocol_code,
                    reference.protocol_version,
                )
                registered = protocol_map.get(key)
                if registered is None:
                    raise ClinicalLearningIntegrityError(
                        "A clinician decision references a protocol version "
                        "missing from the protocol registry."
                    )
                if registered.treatment_type != reference.treatment_type:
                    raise ClinicalLearningIntegrityError(
                        "A clinician decision treatment type conflicts with "
                        "its registered protocol."
                    )
                decision_event_refs[key] += 1
                if record.id in current_decision_ids:
                    current_decision_refs[key] += 1

        protocol_reviews = []
        for protocol in sorted(
            protocols,
            key=lambda item: (item.code, item.version),
        ):
            key = (protocol.code, protocol.version)
            outcomes = protocol_outcomes.get(key, [])
            treatment_ids = protocol_treatment_ids.get(key, set())
            linked_ids = protocol_linked_treatment_ids.get(key, set())
            outcome_treatment_ids = {
                item.treatment_id for item in outcomes
            }
            follow_up_counts = {
                "early_28_to_70_days": 0,
                "intermediate_71_to_180_days": 0,
                "long_term_181_to_365_days": 0,
                "outside_standard_windows": 0,
            }
            for outcome in outcomes:
                follow_up_counts[
                    _follow_up_bucket(outcome.follow_up_day)
                ] += 1

            total_outcomes = len(outcomes)
            patient_present = sum(
                item.patient_rating is not None for item in outcomes
            )
            physician_present = sum(
                item.physician_rating is not None for item in outcomes
            )
            pain_present = sum(
                item.pain_score is not None for item in outcomes
            )
            function_present = sum(
                item.function_score is not None for item in outcomes
            )
            adverse_event_records = sum(
                bool(item.adverse_events) for item in outcomes
            )

            flags = []
            if len(outcome_treatment_ids) < MIN_LEARNING_CASES:
                flags.append("fewer_than_5_treatments_with_outcomes")
            if not linked_ids:
                flags.append("no_decision_linked_treatments")
            if patient_present < total_outcomes:
                flags.append("patient_rating_incomplete")
            if physician_present < total_outcomes:
                flags.append("physician_rating_incomplete")
            if pain_present < total_outcomes:
                flags.append("pain_score_incomplete")
            if function_present < total_outcomes:
                flags.append("function_score_incomplete")

            protocol_reviews.append(
                ProtocolLearningReviewRead(
                    protocol_code=protocol.code,
                    protocol_version=protocol.version,
                    protocol_name=protocol.name,
                    treatment_type=protocol.treatment_type,
                    is_active=protocol.is_active,
                    decision_event_reference_count=(
                        decision_event_refs.get(key, 0)
                    ),
                    current_decision_reference_count=(
                        current_decision_refs.get(key, 0)
                    ),
                    treatment_count=len(treatment_ids),
                    decision_linked_treatment_count=len(linked_ids),
                    treatment_with_outcome_count=len(
                        outcome_treatment_ids
                    ),
                    outcome_record_count=total_outcomes,
                    follow_up_counts=LearningFollowUpCountsRead(
                        **follow_up_counts
                    ),
                    data_volume=_data_volume(
                        len(outcome_treatment_ids)
                    ),
                    patient_rating_coverage=_coverage(
                        patient_present,
                        total_outcomes,
                    ),
                    physician_rating_coverage=_coverage(
                        physician_present,
                        total_outcomes,
                    ),
                    pain_score_coverage=_coverage(
                        pain_present,
                        total_outcomes,
                    ),
                    function_score_coverage=_coverage(
                        function_present,
                        total_outcomes,
                    ),
                    outcome_with_documented_adverse_event_count=(
                        adverse_event_records
                    ),
                    data_quality_flags=flags,
                )
            )

        total_outcomes = len(validated_outcomes)
        global_patient_present = sum(
            item.patient_rating is not None
            for item in validated_outcomes
        )
        global_physician_present = sum(
            item.physician_rating is not None
            for item in validated_outcomes
        )
        global_pain_present = sum(
            item.pain_score is not None
            for item in validated_outcomes
        )
        global_function_present = sum(
            item.function_score is not None
            for item in validated_outcomes
        )
        global_adverse_records = sum(
            bool(item.adverse_events)
            for item in validated_outcomes
        )

        data_quality = LearningDataQualityRead(
            decision_event_count=len(validated_decisions),
            current_decision_count=len(current_decision_ids),
            current_actionable_decision_count=sum(
                record.id in current_decision_ids
                and record.decision_type in ACTIONABLE_DECISION_TYPES
                for record, _payload in validated_decisions
            ),
            decision_linked_treatment_count=(
                decision_linked_treatment_count
            ),
            legacy_or_unlinked_treatment_count=(
                legacy_or_unlinked_treatment_count
            ),
            treatment_with_outcome_count=len(
                treatments_with_outcomes
            ),
            outcome_record_count=total_outcomes,
            patient_rating_coverage=_coverage(
                global_patient_present,
                total_outcomes,
            ),
            physician_rating_coverage=_coverage(
                global_physician_present,
                total_outcomes,
            ),
            pain_score_coverage=_coverage(
                global_pain_present,
                total_outcomes,
            ),
            function_score_coverage=_coverage(
                global_function_present,
                total_outcomes,
            ),
            outcome_with_documented_adverse_event_count=(
                global_adverse_records
            ),
        )

        source_manifest = {
            "schema_version": 1,
            "decision_sha256s": sorted(
                record.sha256
                for record, _payload in validated_decisions
            ),
            "outcome_sha256s": sorted(
                item.sha256 for item in validated_outcomes
            ),
        }
        source_manifest_sha256 = evidence_digest(source_manifest)
        review_payload = {
            "schema_version": 1,
            "data_quality": data_quality.model_dump(mode="json"),
            "protocols": [
                item.model_dump(mode="json")
                for item in protocol_reviews
            ],
            "source_decision_count": len(validated_decisions),
            "source_outcome_count": total_outcomes,
            "source_manifest_sha256": source_manifest_sha256,
            "protocol_ordering": "protocol_code_then_version",
            "local_data_are_observational": True,
            "is_cross_protocol_effectiveness_comparison": False,
            "ranks_treatments": False,
            "produces_learning_score": False,
            "automatically_changes_protocols": False,
            "requires_clinical_and_data_quality_review": True,
        }

        return ClinicalLearningReviewRead(
            generated_at=datetime.now(timezone.utc),
            **review_payload,
            review_sha256=evidence_digest(review_payload),
        )
