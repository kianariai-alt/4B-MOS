from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.session_worklist import (
    SessionWorklistResponse,
)
from backend.app.services.session_worklist import (
    SessionWorklistService,
)


router = APIRouter(
    prefix="/dashboard",
    tags=["Session Worklist"],
)


WORKLIST_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
)


@router.get(
    "/worklist",
    response_model=(
        SessionWorklistResponse
    ),
)
def get_session_worklist(
    days: int = Query(
        default=7,
        ge=1,
        le=30,
    ),
    _current_user: User = Depends(
        require_roles(
            *WORKLIST_ROLES
        )
    ),
    db: Session = Depends(get_db),
) -> SessionWorklistResponse:
    return (
        SessionWorklistService
        .get_worklist(
            db,
            days=days,
        )
    )