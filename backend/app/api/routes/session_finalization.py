from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.session_finalization import SessionFinalizationRead
from backend.app.services.session_finalization import (
    FinalizationIntegrityError, FinalizationNotFoundError, SessionFinalizationService,
)

router = APIRouter(tags=["Session Finalization Evidence"])


@router.get("/treatment-sessions/{session_id}/finalization", response_model=SessionFinalizationRead)
def get_finalization(
    session_id: str,
    _user: User = Depends(require_roles("admin", "physician", "nurse", "operator", "viewer")),
    db: Session = Depends(get_db),
):
    try:
        return SessionFinalizationService.get(db, session_id)
    except FinalizationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FinalizationIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
