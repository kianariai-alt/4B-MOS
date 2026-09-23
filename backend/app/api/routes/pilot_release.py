from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.pilot_release import (
    PilotManualGateAttestationCreate,
    PilotManualGateAttestationRead,
    PilotManualGateReviewCreate,
    PilotManualGateStatusRead,
)
from backend.app.services.pilot_release import (
    PilotManualGateAuthorizationError,
    PilotManualGateConflictError,
    PilotManualGateIntegrityError,
    PilotManualGateNotFoundError,
    PilotManualGateService,
)


router = APIRouter(
    prefix="/pilot-readiness/manual-gates",
    tags=["System"],
)


def _translate(error: Exception):
    if isinstance(error, PilotManualGateNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, PilotManualGateAuthorizationError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, (
        PilotManualGateConflictError,
        PilotManualGateIntegrityError,
    )):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise error


@router.get(
    "",
    response_model=list[PilotManualGateStatusRead],
)
def list_manual_gate_statuses(
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotManualGateService.list_statuses(db)
    except PilotManualGateIntegrityError as error:
        _translate(error)


@router.get(
    "/attestations",
    response_model=list[PilotManualGateAttestationRead],
)
def list_manual_gate_attestations(
    gate_name: str | None = None,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotManualGateService.list_attestations(
            db,
            gate_name=gate_name,
        )
    except PilotManualGateIntegrityError as error:
        _translate(error)


@router.get(
    "/attestations/{attestation_id}",
    response_model=PilotManualGateAttestationRead,
)
def get_manual_gate_attestation(
    attestation_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotManualGateService.get_attestation(db, attestation_id)
    except (
        PilotManualGateIntegrityError,
        PilotManualGateNotFoundError,
    ) as error:
        _translate(error)


@router.post(
    "/attestations",
    response_model=PilotManualGateAttestationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_gate_attestation(
    payload: PilotManualGateAttestationCreate,
    actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotManualGateService.create_attestation(
            db,
            payload,
            actor=actor,
            config=settings,
        )
    except (
        PilotManualGateAuthorizationError,
        PilotManualGateConflictError,
        PilotManualGateIntegrityError,
    ) as error:
        _translate(error)


@router.post(
    "/attestations/{attestation_id}/review",
    response_model=PilotManualGateAttestationRead,
)
def review_manual_gate_attestation(
    attestation_id: str,
    payload: PilotManualGateReviewCreate,
    actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotManualGateService.review_attestation(
            db,
            attestation_id,
            payload,
            actor=actor,
            config=settings,
        )
    except (
        PilotManualGateAuthorizationError,
        PilotManualGateConflictError,
        PilotManualGateIntegrityError,
        PilotManualGateNotFoundError,
    ) as error:
        _translate(error)
