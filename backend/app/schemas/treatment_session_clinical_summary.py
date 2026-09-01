from typing import Literal

from pydantic import BaseModel

from backend.app.schemas.treatment_variance import (
    TreatmentSessionVarianceRead,
)


PlanAlignmentStatus = Literal[
    "no_plan",
    "aligned",
    "deviation_present",
    "not_assessable",
]


ClinicalAlertSeverity = Literal[
    "info",
    "warning",
]


class TreatmentSessionClinicalAlertRead(
    BaseModel
):
    code: str
    severity: ClinicalAlertSeverity
    message: str

    material_code: str | None = None

    treatment_component_id: (
        str | None
    ) = None

    session_component_id: (
        str | None
    ) = None


class TreatmentSessionClinicalSummaryRead(
    BaseModel
):
    session_id: str
    treatment_id: str
    session_number: int

    session_status: str
    operational_status: str

    has_plan: bool

    plan_alignment_status: (
        PlanAlignmentStatus
    )

    has_deviations: bool

    administered_record_count: int
    deviation_count: int
    traceability_issue_count: int
    alert_count: int

    alerts: list[
        TreatmentSessionClinicalAlertRead
    ]

    variance: TreatmentSessionVarianceRead
