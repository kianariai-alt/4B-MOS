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
from backend.app.services.session_finalization import FinalizationIntegrityError
from backend.app.schemas.session_workflow import (
    SessionWorkflowUpdate,
)
from backend.app.schemas.treatment_session import (
    TreatmentSessionRead,
)
from backend.app.services.session_workflow import (
    SessionWorkflowConflictError,
    SessionWorkflowNotFoundError,
    SessionWorkflowService,
)


router = APIRouter(
    tags=["Session Workflow"],
)


WORKFLOW_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
)


@router.patch(
    (
        "/treatment-sessions/"
        "{session_id}/workflow"
    ),
    response_model=TreatmentSessionRead,
)
def update_session_workflow(
    session_id: str,
    payload: SessionWorkflowUpdate,
    current_user: User = Depends(
        require_roles(
            *WORKFLOW_ROLES
        )
    ),
    db: Session = Depends(get_db),
) -> TreatmentSessionRead:
    try:
        treatment_session = (
            SessionWorkflowService
            .transition(
                db,
                session_id,
                payload.operational_status,
                actor=current_user,
            )
        )

        return (
            TreatmentSessionRead
            .model_validate(
                treatment_session
            )
        )

    except SessionWorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except (SessionWorkflowConflictError, FinalizationIntegrityError) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc
