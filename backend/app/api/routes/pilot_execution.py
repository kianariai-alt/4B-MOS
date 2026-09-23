"""Controlled pilot actions; every treatment still requires clinician judgment."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.pilot_execution import (
    PilotAcceptanceRead, PilotEnrollmentCreate, PilotEnrollmentRead,
    PilotOperationsRead, PilotStopCreate, PilotStopRead,
)
from backend.app.services.pilot_execution import (
    PilotExecutionAuthorizationError, PilotExecutionConflictError,
    PilotExecutionIntegrityError, PilotExecutionNotFoundError,
    PilotExecutionService,
)


router = APIRouter(prefix="/pilot-execution", tags=["Controlled Pilot"])


def _translate(error: Exception) -> None:
    if isinstance(error, PilotExecutionNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PilotExecutionAuthorizationError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, (PilotExecutionConflictError, PilotExecutionIntegrityError)):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise error


@router.get("/releases/{release_id}/operations", response_model=PilotOperationsRead)
def pilot_operations(
    release_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.operations(db, release_id)
    except Exception as error:
        _translate(error)


@router.post(
    "/releases/{release_id}/visits/{visit_id}/enroll",
    response_model=PilotEnrollmentRead,
    status_code=status.HTTP_201_CREATED,
)
def enroll_pilot_visit(
    release_id: str, visit_id: str, payload: PilotEnrollmentCreate,
    actor: User = Depends(require_roles("physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.enroll(db, release_id, visit_id, payload, actor=actor)
    except Exception as error:
        _translate(error)


@router.get("/visits/{visit_id}/enrollment", response_model=PilotEnrollmentRead | None)
def get_pilot_visit_enrollment(
    visit_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.get_enrollment(db, visit_id)
    except Exception as error:
        _translate(error)


@router.get(
    "/releases/{release_id}/enrollments",
    response_model=list[PilotEnrollmentRead],
)
def list_pilot_enrollments(
    release_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.list_enrollments(db, release_id)
    except Exception as error:
        _translate(error)


@router.post(
    "/releases/{release_id}/stop",
    response_model=PilotStopRead,
    status_code=status.HTTP_201_CREATED,
)
def stop_controlled_pilot(
    release_id: str, payload: PilotStopCreate,
    actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.stop(db, release_id, payload, actor=actor)
    except Exception as error:
        _translate(error)


@router.get("/releases/{release_id}/stop", response_model=PilotStopRead | None)
def get_pilot_stop(
    release_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.get_stop(db, release_id)
    except Exception as error:
        _translate(error)


@router.get("/releases/{release_id}/acceptance", response_model=PilotAcceptanceRead)
def pilot_acceptance_report(
    release_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotExecutionService.acceptance(db, release_id)
    except Exception as error:
        _translate(error)
