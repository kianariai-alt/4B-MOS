from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.treatment_session import (
    TreatmentSessionCreate,
    TreatmentSessionRead,
    TreatmentSessionUpdate,
)
from backend.app.services.treatment_session import (
    TreatmentForSessionNotFoundError,
    TreatmentSessionConflictError,
    TreatmentSessionNotFoundError,
    TreatmentSessionService,
)


router = APIRouter(
    tags=["Treatment Sessions"],
)


@router.post(
    "/treatments/{treatment_id}/sessions",
    response_model=TreatmentSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_treatment_session(
    treatment_id: str,
    payload: TreatmentSessionCreate,
    db: Session = Depends(get_db),
) -> TreatmentSessionRead:
    try:
        treatment_session = (
            TreatmentSessionService.create_session(
                db,
                treatment_id,
                payload,
            )
        )

        return TreatmentSessionRead.model_validate(
            treatment_session
        )

    except TreatmentForSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except TreatmentSessionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/treatments/{treatment_id}/sessions",
    response_model=list[TreatmentSessionRead],
)
def list_treatment_sessions(
    treatment_id: str,
    db: Session = Depends(get_db),
) -> list[TreatmentSessionRead]:
    try:
        sessions = TreatmentSessionService.list_sessions(
            db,
            treatment_id,
        )

        return [
            TreatmentSessionRead.model_validate(item)
            for item in sessions
        ]

    except TreatmentForSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/treatment-sessions/{session_id}",
    response_model=TreatmentSessionRead,
)
def get_treatment_session(
    session_id: str,
    db: Session = Depends(get_db),
) -> TreatmentSessionRead:
    try:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        return TreatmentSessionRead.model_validate(
            treatment_session
        )

    except TreatmentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/treatment-sessions/{session_id}",
    response_model=TreatmentSessionRead,
)
def update_treatment_session(
    session_id: str,
    payload: TreatmentSessionUpdate,
    db: Session = Depends(get_db),
) -> TreatmentSessionRead:
    try:
        treatment_session = (
            TreatmentSessionService.update_session(
                db,
                session_id,
                payload,
            )
        )

        return TreatmentSessionRead.model_validate(
            treatment_session
        )

    except TreatmentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except TreatmentSessionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc