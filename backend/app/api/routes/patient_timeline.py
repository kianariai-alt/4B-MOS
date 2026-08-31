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
from backend.app.schemas.patient_timeline import (
    PatientTimelineResponse,
)
from backend.app.services.patient_timeline import (
    PatientTimelineNotFoundError,
    PatientTimelineService,
)


router = APIRouter(
    tags=["Patient Timeline"],
)


TIMELINE_READ_ROLES = (
    "admin",
    "physician",
    "nurse",
)


@router.get(
    "/patients/{patient_id}/timeline",
    response_model=PatientTimelineResponse,
)
def get_patient_timeline(
    patient_id: str,
    _current_user: User = Depends(
        require_roles(
            *TIMELINE_READ_ROLES
        )
    ),
    db: Session = Depends(get_db),
) -> PatientTimelineResponse:
    try:
        return (
            PatientTimelineService
            .get_patient_timeline(
                db,
                patient_id,
            )
        )

    except PatientTimelineNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc