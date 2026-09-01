from typing import Literal

from pydantic import BaseModel

from backend.app.schemas.treatment_session_clinical_summary import (
    TreatmentSessionClinicalSummaryRead,
)


CompletionReadiness = Literal[
    "ready",
    "ready_with_warnings",
    "blocked",
]


CompletionIssueSeverity = Literal[
    "warning",
    "blocker",
]


class TreatmentSessionCompletionIssueRead(
    BaseModel
):
    code: str
    severity: CompletionIssueSeverity
    message: str

    material_code: str | None = None

    treatment_component_id: (
        str | None
    ) = None

    session_component_id: (
        str | None
    ) = None


class TreatmentSessionCompletionCheckRead(
    BaseModel
):
    session_id: str
    treatment_id: str

    can_complete: bool

    readiness: CompletionReadiness

    blocker_count: int
    warning_count: int

    issues: list[
        TreatmentSessionCompletionIssueRead
    ]

    clinical_summary: (
        TreatmentSessionClinicalSummaryRead
        | None
    )
