from sqlalchemy.orm import Session

from backend.app.repositories.treatment_session_component import (
    TreatmentSessionComponentRepository,
)
from backend.app.schemas.treatment_session_clinical_summary import (
    TreatmentSessionClinicalAlertRead,
    TreatmentSessionClinicalSummaryRead,
)
from backend.app.services.treatment_session import (
    TreatmentSessionService,
)
from backend.app.services.treatment_variance import (
    TreatmentVarianceService,
)


class TreatmentSessionClinicalSummaryService:
    @staticmethod
    def get_summary(
        db: Session,
        session_id: str,
    ) -> TreatmentSessionClinicalSummaryRead:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        variance = (
            TreatmentVarianceService
            .get_session_variance(
                db,
                session_id,
            )
        )

        actual_components = (
            TreatmentSessionComponentRepository
            .list_by_session(
                db,
                session_id,
            )
        )

        alerts: list[
            TreatmentSessionClinicalAlertRead
        ] = []

        deviation_count = 0

        for item in variance.components:
            if item.status == "omitted":
                deviation_count += 1

                alerts.append(
                    TreatmentSessionClinicalAlertRead(
                        code="PLANNED_COMPONENT_OMITTED",
                        severity="warning",
                        message=(
                            "A planned treatment "
                            "component has no linked "
                            "administration record."
                        ),
                        material_code=(
                            item.material_code
                        ),
                        treatment_component_id=(
                            item.treatment_component_id
                        ),
                    )
                )

            elif (
                item.status
                == "under_administered"
            ):
                deviation_count += 1

                alerts.append(
                    TreatmentSessionClinicalAlertRead(
                        code="UNDER_ADMINISTERED",
                        severity="warning",
                        message=(
                            "Actual administered "
                            "amount is lower than "
                            "the planned amount."
                        ),
                        material_code=(
                            item.material_code
                        ),
                        treatment_component_id=(
                            item.treatment_component_id
                        ),
                    )
                )

            elif (
                item.status
                == "over_administered"
            ):
                deviation_count += 1

                alerts.append(
                    TreatmentSessionClinicalAlertRead(
                        code="OVER_ADMINISTERED",
                        severity="warning",
                        message=(
                            "Actual administered "
                            "amount is higher than "
                            "the planned amount."
                        ),
                        material_code=(
                            item.material_code
                        ),
                        treatment_component_id=(
                            item.treatment_component_id
                        ),
                    )
                )

            elif (
                item.status
                == "unit_mismatch"
            ):
                deviation_count += 1

                alerts.append(
                    TreatmentSessionClinicalAlertRead(
                        code="UNIT_MISMATCH",
                        severity="warning",
                        message=(
                            "Planned and actual "
                            "administration units "
                            "cannot be compared."
                        ),
                        material_code=(
                            item.material_code
                        ),
                        treatment_component_id=(
                            item.treatment_component_id
                        ),
                    )
                )

            elif (
                item.status
                == "unquantified"
            ):
                alerts.append(
                    TreatmentSessionClinicalAlertRead(
                        code="UNQUANTIFIED_COMPONENT",
                        severity="info",
                        message=(
                            "Plan alignment cannot "
                            "be quantitatively "
                            "assessed for this "
                            "component."
                        ),
                        material_code=(
                            item.material_code
                        ),
                        treatment_component_id=(
                            item.treatment_component_id
                        ),
                    )
                )

        for item in (
            variance.unplanned_administrations
        ):
            deviation_count += 1

            alerts.append(
                TreatmentSessionClinicalAlertRead(
                    code="UNPLANNED_ADMINISTRATION",
                    severity="warning",
                    message=(
                        "An administration record "
                        "is not linked to a planned "
                        "treatment component."
                    ),
                    material_code=(
                        item.material_code
                    ),
                    session_component_id=(
                        item.session_component_id
                    ),
                )
            )

        traceability_issue_count = 0

        for component in actual_components:
            material = component.material

            if (
                material.requires_lot_tracking
                and not component.lot_number
                and not component.batch_number
            ):
                traceability_issue_count += 1

                alerts.append(
                    TreatmentSessionClinicalAlertRead(
                        code="TRACEABILITY_MISSING",
                        severity="warning",
                        message=(
                            "Material requires lot "
                            "tracking but no lot or "
                            "batch number is "
                            "recorded."
                        ),
                        material_code=(
                            material.code
                        ),
                        session_component_id=(
                            component.id
                        ),
                    )
                )

        has_plan = (
            variance.planned_count > 0
        )

        if not has_plan:
            alignment_status = "no_plan"

            alerts.append(
                TreatmentSessionClinicalAlertRead(
                    code="NO_TREATMENT_PLAN",
                    severity="info",
                    message=(
                        "No treatment components "
                        "are recorded in the plan "
                        "for this session's "
                        "treatment."
                    ),
                )
            )

        elif deviation_count > 0:
            alignment_status = (
                "deviation_present"
            )

        elif (
            variance.unquantified_count > 0
        ):
            alignment_status = (
                "not_assessable"
            )

        else:
            alignment_status = "aligned"

        administered_record_count = (
            variance.linked_administration_count
            + variance.unplanned_count
        )

        return (
            TreatmentSessionClinicalSummaryRead(
                session_id=(
                    treatment_session.id
                ),
                treatment_id=(
                    treatment_session.treatment_id
                ),
                session_number=(
                    treatment_session.session_number
                ),
                session_status=(
                    treatment_session.status
                ),
                operational_status=(
                    treatment_session
                    .operational_status
                ),
                has_plan=has_plan,
                plan_alignment_status=(
                    alignment_status
                ),
                has_deviations=(
                    deviation_count > 0
                ),
                administered_record_count=(
                    administered_record_count
                ),
                deviation_count=(
                    deviation_count
                ),
                traceability_issue_count=(
                    traceability_issue_count
                ),
                alert_count=len(alerts),
                alerts=alerts,
                variance=variance,
            )
        )
