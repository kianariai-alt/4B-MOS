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
from backend.app.schemas.treatment_session_clinical_summary import (
    TreatmentSessionClinicalSummaryRead,
)
from backend.app.services.treatment_session import (
    TreatmentSessionNotFoundError,
)
from backend.app.services.treatment_session_clinical_summary import (
    TreatmentSessionClinicalSummaryService,
)
from backend.app.services.treatment_variance import (
    TreatmentVarianceIntegrityError,
)


router = APIRouter(
    tags=[
        "Treatment Session Clinical Summary",
    ],
)


READ_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
    "viewer",
)


@router.get(
    (
        "/treatment-sessions/"
        "{session_id}/clinical-summary"
    ),
    response_model=(
        TreatmentSessionClinicalSummaryRead
    ),
)
def get_treatment_session_clinical_summary(
    session_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentSessionClinicalSummaryRead:
    try:
        return (
            TreatmentSessionClinicalSummaryService
            .get_summary(
                db,
                session_id,
            )
        )

    except TreatmentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except TreatmentVarianceIntegrityError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc
