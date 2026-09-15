from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.session_amendment import (
    SessionAmendmentCreate,
    SessionAmendmentRead,
    SessionAmendmentReviewCreate,
)
from backend.app.services.session_amendment import (
    SessionAmendmentAuthorizationError,
    SessionAmendmentConflictError,
    SessionAmendmentIntegrityError,
    SessionAmendmentNotFoundError,
    SessionAmendmentService,
)
from backend.app.services.session_finalization import (
    FinalizationIntegrityError,
    FinalizationNotFoundError,
)


router = APIRouter(tags=["Session Amendments"])

READ_ROLES = ("admin", "physician", "nurse", "operator", "viewer")
AUTHOR_ROLES = ("admin", "physician", "nurse")
REVIEW_ROLES = ("admin", "physician")


def _translate_error(error: Exception) -> None:
    if isinstance(error, (FinalizationNotFoundError, SessionAmendmentNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, SessionAmendmentAuthorizationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/treatment-sessions/{session_id}/amendments",
    response_model=SessionAmendmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_session_amendment(
    session_id: str,
    payload: SessionAmendmentCreate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> SessionAmendmentRead:
    try:
        return SessionAmendmentService.create(db, session_id, payload, actor=actor)
    except (
        FinalizationNotFoundError,
        FinalizationIntegrityError,
        SessionAmendmentAuthorizationError,
        SessionAmendmentConflictError,
        SessionAmendmentIntegrityError,
    ) as error:
        _translate_error(error)


@router.get(
    "/treatment-sessions/{session_id}/amendments",
    response_model=list[SessionAmendmentRead],
)
def list_session_amendments(
    session_id: str,
    _user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[SessionAmendmentRead]:
    try:
        return SessionAmendmentService.list_for_session(db, session_id)
    except (
        FinalizationNotFoundError,
        FinalizationIntegrityError,
        SessionAmendmentIntegrityError,
    ) as error:
        _translate_error(error)


@router.get(
    "/treatment-sessions/{session_id}/amendments/{amendment_id}",
    response_model=SessionAmendmentRead,
)
def get_session_amendment(
    session_id: str,
    amendment_id: str,
    _user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> SessionAmendmentRead:
    try:
        return SessionAmendmentService.get(db, session_id, amendment_id)
    except (
        FinalizationNotFoundError,
        FinalizationIntegrityError,
        SessionAmendmentNotFoundError,
        SessionAmendmentIntegrityError,
    ) as error:
        _translate_error(error)


@router.post(
    "/treatment-sessions/{session_id}/amendments/{amendment_id}/review",
    response_model=SessionAmendmentRead,
    status_code=status.HTTP_201_CREATED,
)
def review_session_amendment(
    session_id: str,
    amendment_id: str,
    payload: SessionAmendmentReviewCreate,
    actor: User = Depends(require_roles(*REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> SessionAmendmentRead:
    try:
        return SessionAmendmentService.review(
            db,
            session_id,
            amendment_id,
            payload,
            actor=actor,
        )
    except (
        FinalizationNotFoundError,
        FinalizationIntegrityError,
        SessionAmendmentNotFoundError,
        SessionAmendmentAuthorizationError,
        SessionAmendmentConflictError,
        SessionAmendmentIntegrityError,
    ) as error:
        _translate_error(error)
