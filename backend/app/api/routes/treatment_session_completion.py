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
from backend.app.schemas.treatment_session_completion import (
    TreatmentSessionCompletionCheckRead,
)
from backend.app.services.treatment_session import (
    TreatmentSessionNotFoundError,
)
from backend.app.services.treatment_session_completion import (
    TreatmentSessionCompletionGuardService,
)


router = APIRouter(
    tags=["Session Completion Safety"],
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
        "{session_id}/completion-check"
    ),
    response_model=(
        TreatmentSessionCompletionCheckRead
    ),
)
def get_session_completion_check(
    session_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentSessionCompletionCheckRead:
    try:
        return (
            TreatmentSessionCompletionGuardService
            .evaluate(
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
