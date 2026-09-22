from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DataVolume = Literal[
    "insufficient",
    "very_limited",
    "limited",
    "moderate",
    "substantial",
]


class LearningMetricRead(BaseModel):
    value: float | None
    denominator: int
    minimum_denominator: int
    suppressed_for_small_n: bool


class LearningFollowUpCountsRead(BaseModel):
    early_28_to_70_days: int = 0
    intermediate_71_to_180_days: int = 0
    long_term_181_to_365_days: int = 0
    outside_standard_windows: int = 0


class LearningOutcomeDistributionRead(BaseModel):
    improved: int = 0
    unchanged: int = 0
    worsened: int = 0
    mixed: int = 0
    unknown: int = 0


class LearningDataQualityRead(BaseModel):
    decision_event_count: int
    current_decision_count: int
    current_actionable_decision_count: int
    decision_linked_treatment_count: int
    legacy_or_unlinked_treatment_count: int
    treatment_with_outcome_count: int
    outcome_record_count: int
    outcome_with_patient_rating_count: int
    outcome_with_physician_rating_count: int
    outcome_with_pain_score_count: int
    outcome_with_function_score_count: int
    outcome_with_documented_adverse_event_count: int


class ProtocolLearningReviewRead(BaseModel):
    protocol_code: str
    protocol_version: str
    protocol_name: str
    treatment_type: str
    is_active: bool
    decision_event_reference_count: int
    current_decision_reference_count: int
    treatment_count: int
    decision_linked_treatment_count: int
    treatment_with_outcome_count: int
    outcome_record_count: int
    follow_up_counts: LearningFollowUpCountsRead
    data_volume: DataVolume
    outcome_distribution: LearningOutcomeDistributionRead | None
    median_patient_rating: LearningMetricRead
    median_physician_rating: LearningMetricRead
    median_follow_up_pain_score: LearningMetricRead
    median_function_score: LearningMetricRead
    documented_adverse_event_proportion: LearningMetricRead
    missing_patient_rating_count: int
    missing_physician_rating_count: int
    missing_pain_score_count: int
    missing_function_score_count: int
    data_quality_flags: list[
        Literal[
            "fewer_than_5_treatments_with_outcomes",
            "no_decision_linked_treatments",
            "patient_rating_incomplete",
            "physician_rating_incomplete",
            "pain_score_incomplete",
            "function_score_incomplete",
        ]
    ]
    is_performance_score: Literal[False] = False
    is_treatment_ranking: Literal[False] = False


class ClinicalLearningReviewRead(BaseModel):
    generated_at: datetime
    data_quality: LearningDataQualityRead
    protocols: list[ProtocolLearningReviewRead]
    source_decision_count: int
    source_outcome_count: int
    source_manifest_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    review_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    protocol_ordering: Literal[
        "protocol_code_then_version"
    ] = "protocol_code_then_version"
    local_data_are_observational: Literal[True] = True
    is_cross_protocol_comparison: Literal[False] = False
    ranks_treatments: Literal[False] = False
    produces_learning_score: Literal[False] = False
    automatically_changes_protocols: Literal[False] = False
    requires_clinical_and_data_quality_review: Literal[True] = True
