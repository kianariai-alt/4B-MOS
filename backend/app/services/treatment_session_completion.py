from sqlalchemy.orm import Session

from backend.app.schemas.treatment_session_completion import (
    TreatmentSessionCompletionCheckRead,
    TreatmentSessionCompletionIssueRead,
)
from backend.app.services.treatment_session import (
    TreatmentSessionService,
)
from backend.app.services.treatment_session_clinical_summary import (
    TreatmentSessionClinicalSummaryService,
)
from backend.app.services.treatment_variance import (
    TreatmentVarianceIntegrityError,
)


class TreatmentSessionCompletionGuardService:
    @staticmethod
    def evaluate(
        db: Session,
        session_id: str,
    ) -> TreatmentSessionCompletionCheckRead:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        issues: list[
            TreatmentSessionCompletionIssueRead
        ] = []

        try:
            summary = (
                TreatmentSessionClinicalSummaryService
                .get_summary(
                    db,
                    session_id,
                )
            )

        except TreatmentVarianceIntegrityError:
            issues.append(
                TreatmentSessionCompletionIssueRead(
                    code="DATA_INTEGRITY_ERROR",
                    severity="blocker",
                    message=(
                        "Plan and administration "
                        "records contain an "
                        "integrity conflict that "
                        "must be resolved before "
                        "session completion."
                    ),
                )
            )

            return (
                TreatmentSessionCompletionCheckRead(
                    session_id=(
                        treatment_session.id
                    ),
                    treatment_id=(
                        treatment_session
                        .treatment_id
                    ),
                    can_complete=False,
                    readiness="blocked",
                    blocker_count=1,
                    warning_count=0,
                    issues=issues,
                    clinical_summary=None,
                )
            )

        if (
            summary.has_plan
            and summary.administered_record_count
            == 0
        ):
            issues.append(
                TreatmentSessionCompletionIssueRead(
                    code=(
                        "NO_ADMINISTRATION_RECORDED"
                    ),
                    severity="blocker",
                    message=(
                        "The treatment has planned "
                        "components but no actual "
                        "administration record has "
                        "been documented for this "
                        "session."
                    ),
                )
            )

        for alert in summary.alerts:
            if (
                alert.code
                == "TRACEABILITY_MISSING"
            ):
                issues.append(
                    TreatmentSessionCompletionIssueRead(
                        code=alert.code,
                        severity="blocker",
                        message=alert.message,
                        material_code=(
                            alert.material_code
                        ),
                        treatment_component_id=(
                            alert
                            .treatment_component_id
                        ),
                        session_component_id=(
                            alert
                            .session_component_id
                        ),
                    )
                )

                continue

            if alert.code in {
                "PLANNED_COMPONENT_OMITTED",
                "UNDER_ADMINISTERED",
                "OVER_ADMINISTERED",
                "UNIT_MISMATCH",
                "UNPLANNED_ADMINISTRATION",
                "UNQUANTIFIED_COMPONENT",
            }:
                issues.append(
                    TreatmentSessionCompletionIssueRead(
                        code=alert.code,
                        severity="warning",
                        message=alert.message,
                        material_code=(
                            alert.material_code
                        ),
                        treatment_component_id=(
                            alert
                            .treatment_component_id
                        ),
                        session_component_id=(
                            alert
                            .session_component_id
                        ),
                    )
                )

        blocker_count = sum(
            1
            for issue in issues
            if issue.severity == "blocker"
        )

        warning_count = sum(
            1
            for issue in issues
            if issue.severity == "warning"
        )

        can_complete = (
            blocker_count == 0
        )

        if blocker_count > 0:
            readiness = "blocked"

        elif warning_count > 0:
            readiness = (
                "ready_with_warnings"
            )

        else:
            readiness = "ready"

        return (
            TreatmentSessionCompletionCheckRead(
                session_id=(
                    treatment_session.id
                ),
                treatment_id=(
                    treatment_session.treatment_id
                ),
                can_complete=can_complete,
                readiness=readiness,
                blocker_count=blocker_count,
                warning_count=warning_count,
                issues=issues,
                clinical_summary=summary,
            )
        )
