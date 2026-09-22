from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.protocol import ProtocolRead


Sha256Pattern = r"^[0-9a-f]{64}$"
RoadmapStatus = Literal[
    "options_available",
    "insufficient_local_data",
    "blocked_pending_safety_evaluation",
    "blocked_stale_safety_evaluation",
    "blocked_pending_safety_review",
]
SimilarityDurationBand = Literal[
    "acute_under_90_days",
    "subacute_90_to_180_days",
    "chronic_over_180_days",
    "unknown",
]
LateralityGroup = Literal[
    "unilateral",
    "bilateral",
    "midline_or_not_applicable",
    "unknown",
]
LocalDataVolume = Literal[
    "insufficient",
    "very_limited",
    "limited",
    "moderate",
    "substantial",
]
FollowUpWindow = Literal[
    "early_28_to_70_days",
    "intermediate_71_to_180_days",
    "long_term_181_to_365_days",
]


class RoadmapTargetProfileRead(BaseModel):
    clinical_context_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=Sha256Pattern,
    )
    body_region: str
    age_years: int | None
    baseline_pain_score: int | None
    symptom_duration_band: SimilarityDurationBand
    laterality_group: LateralityGroup


class RoadmapCohortDefinitionRead(BaseModel):
    same_body_region_required: Literal[True] = True
    exclude_current_patient: Literal[True] = True
    maximum_age_difference_years: int | None
    maximum_baseline_pain_difference: int | None
    symptom_duration_band_required_when_target_known: bool
    laterality_group_required_when_target_known: bool
    minimum_reportable_unique_patients: int
    follow_up_windows: list[FollowUpWindow]
    one_observation_per_patient_protocol_window: Literal[True] = True
    historical_context_must_still_match_outcome_hash: Literal[True] = True


class RoadmapExclusionSummaryRead(BaseModel):
    candidate_outcome_records: int
    excluded_current_patient: int
    excluded_body_region_mismatch: int
    excluded_unreproducible_context: int
    excluded_missing_required_similarity_data: int
    excluded_similarity_mismatch: int
    excluded_missing_or_inactive_protocol: int
    excluded_outside_follow_up_window: int
    duplicate_patient_protocol_window_observations_not_used: int


class RoadmapMetricRead(BaseModel):
    value: float | None
    denominator: int
    minimum_denominator: int
    suppressed_for_small_n: bool


class RoadmapOutcomeDistributionRead(BaseModel):
    improved: int
    unchanged: int
    worsened: int
    mixed: int
    unknown: int


class RoadmapFollowUpWindowRead(BaseModel):
    window: FollowUpWindow
    unique_patient_count: int | None
    unique_patient_count_display: str
    local_data_volume: LocalDataVolume
    median_follow_up_day: float | None
    outcome_distribution: RoadmapOutcomeDistributionRead | None
    observed_improvement_proportion: RoadmapMetricRead
    observed_improvement_wilson_95_low: float | None
    observed_improvement_wilson_95_high: float | None
    median_patient_rating: RoadmapMetricRead
    median_physician_rating: RoadmapMetricRead
    median_pain_change: RoadmapMetricRead
    median_function_score: RoadmapMetricRead
    documented_adverse_event_proportion: RoadmapMetricRead
    source_outcome_sha256s: list[str] = Field(
        default_factory=list,
    )
    is_causal_estimate: Literal[False] = False


class TreatmentOptionRead(BaseModel):
    protocol: ProtocolRead
    treatment_type: str
    protocol_code: str
    protocol_version: str
    body_region: str
    windows: list[RoadmapFollowUpWindowRead]
    reportable_window_count: int
    rationale_codes: list[
        Literal[
            "active_protocol",
            "same_body_region_local_outcomes",
            "deterministically_matched_local_cohort",
            "minimum_cohort_threshold_met",
        ]
    ]
    is_ranked: Literal[False] = False
    is_selected: Literal[False] = False
    is_prescription: Literal[False] = False


class TreatmentOptionsRoadmapRead(BaseModel):
    visit_id: str
    generated_at: datetime
    roadmap_status: RoadmapStatus
    target_profile: RoadmapTargetProfileRead
    safety_evaluation_status: Literal[
        "current",
        "missing",
        "stale",
        "pending_review",
    ]
    safety_finding_count: int
    safety_unresolved_finding_count: int
    cohort_definition: RoadmapCohortDefinitionRead
    exclusions: RoadmapExclusionSummaryRead
    matched_unique_patient_count: int | None
    matched_unique_patient_count_display: str
    options: list[TreatmentOptionRead]
    option_ordering: Literal[
        "protocol_code_then_version"
    ] = "protocol_code_then_version"
    known_limitations: list[str]
    roadmap_steps: list[
        Literal[
            "verify_current_safety_review",
            "review_local_observational_cohort",
            "review_external_evidence_independently",
            "physician_select_modify_or_reject_options",
            "document_clinical_rationale",
        ]
    ]
    roadmap_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=Sha256Pattern,
    )
    local_outcomes_are_observational: Literal[True] = True
    local_outcomes_establish_causality: Literal[False] = False
    ranks_treatments: Literal[False] = False
    is_final_treatment_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    requires_independent_physician_review: Literal[True] = True
