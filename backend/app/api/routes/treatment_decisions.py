from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.treatment_decision import (
    TreatmentDecisionCreate,
    TreatmentDecisionRead,
)
from backend.app.services.treatment_decision import (
    TreatmentDecisionAuthorizationError,
    TreatmentDecisionConflictError,
    TreatmentDecisionIntegrityError,
    TreatmentDecisionNotFoundError,
    TreatmentDecisionService,
)


router = APIRouter(tags=["Treatment Decisions"])
CREATE_ROLES = ("physician",)
READ_ROLES = ("admin", "physician", "nurse")

DECISION_ERRORS = (
    TreatmentDecisionAuthorizationError,
    TreatmentDecisionConflictError,
    TreatmentDecisionIntegrityError,
    TreatmentDecisionNotFoundError,
    ClinicalRecordWriteConflictError,
)


def _translate_error(error: Exception) -> None:
    if isinstance(error, TreatmentDecisionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    if isinstance(error, TreatmentDecisionAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


@router.post(
    "/visits/{visit_id}/treatment-decisions",
    response_model=TreatmentDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_treatment_decision(
    visit_id: str,
    payload: TreatmentDecisionCreate,
    actor: User = Depends(require_roles(*CREATE_ROLES)),
    db: Session = Depends(get_db),
) -> TreatmentDecisionRead:
    try:
        return TreatmentDecisionService.create(
            db,
            visit_id,
            payload,
            actor=actor,
        )
    except DECISION_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/treatment-decisions",
    response_model=list[TreatmentDecisionRead],
)
def list_treatment_decisions(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[TreatmentDecisionRead]:
    try:
        return TreatmentDecisionService.list_for_visit(db, visit_id)
    except DECISION_ERRORS as error:
        _translate_error(error)


@router.get(
    "/treatment-decisions/{decision_id}",
    response_model=TreatmentDecisionRead,
)
def get_treatment_decision(
    decision_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> TreatmentDecisionRead:
    try:
        return TreatmentDecisionService.get(db, decision_id)
    except DECISION_ERRORS as error:
        _translate_error(error)


@router.get(
    "/treatment-decisions/{decision_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_treatment_decision_audit_logs(
    decision_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in TreatmentDecisionService.list_audit_logs(
                db,
                decision_id,
            )
        ]
    except DECISION_ERRORS as error:
        _translate_error(error)
