from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.physician_copilot import PhysicianCopilotSnapshotRead
from backend.app.services.clinical_context import (
    ClinicalContextConflictError,
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
)
from backend.app.services.clinical_evidence import (
    ClinicalEvidenceConflictError,
    ClinicalEvidenceIntegrityError,
    ClinicalEvidenceNotFoundError,
)
from backend.app.services.clinical_safety import (
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyNotFoundError,
)
from backend.app.services.physician_copilot import (
    PhysicianCopilotIntegrityError,
    PhysicianCopilotService,
)
from backend.app.services.treatment_outcome import (
    TreatmentOutcomeIntegrityError,
    TreatmentOutcomeNotFoundError,
)


router = APIRouter(tags=["Physician Copilot"])
READ_ROLES = ("admin", "physician")

NOT_FOUND_ERRORS = (
    ClinicalContextNotFoundError,
    ClinicalEvidenceNotFoundError,
    ClinicalSafetyNotFoundError,
    TreatmentOutcomeNotFoundError,
)
COPILOT_ERRORS = (
    *NOT_FOUND_ERRORS,
    ClinicalContextConflictError,
    ClinicalContextIntegrityError,
    ClinicalEvidenceConflictError,
    ClinicalEvidenceIntegrityError,
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
    TreatmentOutcomeIntegrityError,
    PhysicianCopilotIntegrityError,
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
    "/visits/{visit_id}/physician-copilot",
    response_model=PhysicianCopilotSnapshotRead,
)
def get_physician_copilot_snapshot(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> PhysicianCopilotSnapshotRead:
    try:
        return PhysicianCopilotService.get_snapshot(db, visit_id)
    except COPILOT_ERRORS as error:
        _translate_error(error)
