from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.patient_summary import (
    PatientClinicalSummaryResponse,
)
from backend.app.services.patient_summary import (
    PatientSummaryNotFoundError,
    PatientSummaryService,
)


router = APIRouter(
    tags=["Patient Clinical Summary"],
)


SUMMARY_READ_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
    "viewer",
)


@router.get(
    (
        "/patients/{patient_id}"
        "/clinical-summary"
    ),
    response_model=(
        PatientClinicalSummaryResponse
    ),
)
def get_patient_clinical_summary(
    patient_id: str,
    _current_user: User = Depends(
        require_roles(
            *SUMMARY_READ_ROLES
        )
    ),
    db: Session = Depends(get_db),
) -> PatientClinicalSummaryResponse:
    try:
        return (
            PatientSummaryService
            .get_summary(
                db,
                patient_id,
            )
        )

    except PatientSummaryNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc