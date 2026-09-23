from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.pilot_release import (
    PilotVisitEnrollmentCreate,
    PilotVisitEnrollmentRead,
)
from backend.app.services.pilot_enrollment import (
    PilotEnrollmentAuthorizationError,
    PilotEnrollmentConflictError,
    PilotEnrollmentIntegrityError,
    PilotEnrollmentNotFoundError,
    PilotVisitEnrollmentService,
)


router = APIRouter(tags=["System"])


READ_ROLES = ("admin", "physician", "nurse")


def _translate(error: Exception):
    if isinstance(error, PilotEnrollmentNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PilotEnrollmentAuthorizationError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(
        error,
        (
            PilotEnrollmentConflictError,
            PilotEnrollmentIntegrityError,
            ClinicalRecordWriteConflictError,
        ),
    ):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise error


@router.post(
    "/visits/{visit_id}/pilot-enrollments",
    response_model=PilotVisitEnrollmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pilot_visit_enrollment(
    visit_id: str,
    payload: PilotVisitEnrollmentCreate,
    actor: User = Depends(require_roles("physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotVisitEnrollmentService.create(
            db,
            visit_id,
            payload,
            actor=actor,
        )
    except (
        PilotEnrollmentNotFoundError,
        PilotEnrollmentAuthorizationError,
        PilotEnrollmentConflictError,
        PilotEnrollmentIntegrityError,
        ClinicalRecordWriteConflictError,
    ) as error:
        _translate(error)


@router.get(
    "/visits/{visit_id}/pilot-enrollment",
    response_model=PilotVisitEnrollmentRead | None,
)
def get_latest_pilot_visit_enrollment(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return PilotVisitEnrollmentService.get_latest(db, visit_id)
    except PilotEnrollmentIntegrityError as error:
        _translate(error)


@router.get(
    "/visits/{visit_id}/pilot-enrollments",
    response_model=list[PilotVisitEnrollmentRead],
)
def list_pilot_visit_enrollments(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return PilotVisitEnrollmentService.list_by_visit(db, visit_id)
    except (
        PilotEnrollmentNotFoundError,
        PilotEnrollmentIntegrityError,
    ) as error:
        _translate(error)


@router.get(
    "/pilot-enrollments",
    response_model=list[PilotVisitEnrollmentRead],
)
def list_all_pilot_visit_enrollments(
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotVisitEnrollmentService.list(db)
    except PilotEnrollmentIntegrityError as error:
        _translate(error)
