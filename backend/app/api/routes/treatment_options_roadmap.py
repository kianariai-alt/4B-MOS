from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.treatment_options_roadmap import (
    TreatmentOptionsRoadmapRead,
)
from backend.app.services.clinical_safety import (
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyNotFoundError,
)
from backend.app.services.treatment_options_roadmap import (
    TreatmentOptionsRoadmapService,
    TreatmentRoadmapConflictError,
    TreatmentRoadmapIntegrityError,
    TreatmentRoadmapNotFoundError,
)


router = APIRouter(tags=["Treatment Options Roadmap"])
READ_ROLES = ("admin", "physician")

NOT_FOUND_ERRORS = (
    TreatmentRoadmapNotFoundError,
    ClinicalSafetyNotFoundError,
)
ROADMAP_ERRORS = (
    *NOT_FOUND_ERRORS,
    TreatmentRoadmapConflictError,
    TreatmentRoadmapIntegrityError,
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
)


def _translate_error(error: Exception) -> None:
    if isinstance(error, NOT_FOUND_ERRORS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


@router.get(
    "/visits/{visit_id}/treatment-options-roadmap",
    response_model=TreatmentOptionsRoadmapRead,
)
def get_treatment_options_roadmap(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> TreatmentOptionsRoadmapRead:
    try:
        return TreatmentOptionsRoadmapService.get_roadmap(
            db,
            visit_id,
        )
    except ROADMAP_ERRORS as error:
        _translate_error(error)
