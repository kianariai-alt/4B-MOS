from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.treatment_outcome import (
    TreatmentOutcomeCreate,
    TreatmentOutcomeRead,
)
from backend.app.services.treatment_outcome import (
    TreatmentOutcomeAuthorizationError,
    TreatmentOutcomeConflictError,
    TreatmentOutcomeIntegrityError,
    TreatmentOutcomeNotFoundError,
    TreatmentOutcomeService,
)


router = APIRouter(tags=["Treatment Outcomes"])
CREATE_ROLES = ("physician",)
READ_ROLES = ("admin", "physician", "nurse")

OUTCOME_ERRORS = (
    TreatmentOutcomeAuthorizationError,
    TreatmentOutcomeConflictError,
    TreatmentOutcomeIntegrityError,
    TreatmentOutcomeNotFoundError,
    ClinicalRecordWriteConflictError,
)


def _translate_error(error: Exception) -> None:
    if isinstance(error, TreatmentOutcomeNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    if isinstance(error, TreatmentOutcomeAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


@router.post(
    "/treatments/{treatment_id}/outcomes",
    response_model=TreatmentOutcomeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_treatment_outcome(
    treatment_id: str,
    payload: TreatmentOutcomeCreate,
    actor: User = Depends(require_roles(*CREATE_ROLES)),
    db: Session = Depends(get_db),
) -> TreatmentOutcomeRead:
    try:
        return TreatmentOutcomeService.create(
            db,
            treatment_id,
            payload,
            actor=actor,
        )
    except OUTCOME_ERRORS as error:
        _translate_error(error)


@router.get(
    "/treatments/{treatment_id}/outcomes",
    response_model=list[TreatmentOutcomeRead],
)
def list_treatment_outcomes(
    treatment_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[TreatmentOutcomeRead]:
    try:
        return TreatmentOutcomeService.list_for_treatment(
            db,
            treatment_id,
        )
    except OUTCOME_ERRORS as error:
        _translate_error(error)


@router.get(
    "/treatment-outcomes/{outcome_id}",
    response_model=TreatmentOutcomeRead,
)
def get_treatment_outcome(
    outcome_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> TreatmentOutcomeRead:
    try:
        return TreatmentOutcomeService.get(db, outcome_id)
    except OUTCOME_ERRORS as error:
        _translate_error(error)


@router.get(
    "/treatment-outcomes/{outcome_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_treatment_outcome_audit_logs(
    outcome_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in TreatmentOutcomeService.list_audit_logs(
                db,
                outcome_id,
            )
        ]
    except OUTCOME_ERRORS as error:
        _translate_error(error)
