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
    PilotLaunchPackageCreate,
    PilotLaunchPackagePreviewRead,
    PilotLaunchPackageRead,
    PilotReleaseEndorsementCreate,
    PilotReleaseDecisionCreate,
    PilotReleaseStatusRead,
)
from backend.app.services.pilot_release import (
    PilotManualGateAuthorizationError,
    PilotManualGateConflictError,
    PilotManualGateIntegrityError,
    PilotManualGateNotFoundError,
    PilotManualGateService,
)
from backend.app.services.pilot_launch import (
    PilotLaunchPackageAuthorizationError,
    PilotLaunchPackageConflictError,
    PilotLaunchPackageIntegrityError,
    PilotLaunchPackageNotFoundError,
    PilotLaunchPackageService,
)
from backend.app.services.pilot_release_decision import (
    PilotReleaseDecisionAuthorizationError,
    PilotReleaseDecisionConflictError,
    PilotReleaseDecisionIntegrityError,
    PilotReleaseDecisionNotFoundError,
    PilotReleaseDecisionService,
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



@router.get(
    "/launch-package-preview",
    response_model=PilotLaunchPackagePreviewRead,
)
def preview_pilot_launch_package(
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotLaunchPackageService.preview(db, settings)
    except PilotLaunchPackageIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/launch-packages",
    response_model=list[PilotLaunchPackageRead],
)
def list_pilot_launch_packages(
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotLaunchPackageService.list(db)
    except PilotLaunchPackageIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/launch-packages/{package_id}",
    response_model=PilotLaunchPackageRead,
)
def get_pilot_launch_package(
    package_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotLaunchPackageService.get(db, package_id)
    except PilotLaunchPackageNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PilotLaunchPackageIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/launch-packages",
    response_model=PilotLaunchPackageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pilot_launch_package(
    payload: PilotLaunchPackageCreate,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    try:
        return PilotLaunchPackageService.create(
            db,
            payload,
            actor=actor,
            config=settings,
        )
    except PilotLaunchPackageAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (
        PilotLaunchPackageConflictError,
        PilotLaunchPackageIntegrityError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error



@router.get(
    "/launch-packages/{package_id}/release-status",
    response_model=PilotReleaseStatusRead,
)
def get_pilot_release_status(
    package_id: str,
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotReleaseDecisionService.get_status(
            db,
            package_id,
            settings,
        )
    except PilotReleaseDecisionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PilotReleaseDecisionIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/launch-packages/{package_id}/endorsement",
    response_model=PilotReleaseStatusRead,
)
def create_pilot_release_endorsement(
    package_id: str,
    payload: PilotReleaseEndorsementCreate,
    actor: User = Depends(require_roles("physician")),
    db: Session = Depends(get_db),
):
    try:
        return PilotReleaseDecisionService.create_endorsement(
            db,
            package_id,
            payload,
            actor=actor,
            config=settings,
        )
    except PilotReleaseDecisionAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except PilotReleaseDecisionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (
        PilotReleaseDecisionConflictError,
        PilotReleaseDecisionIntegrityError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/launch-packages/{package_id}/decision",
    response_model=PilotReleaseStatusRead,
)
def create_pilot_release_decision(
    package_id: str,
    payload: PilotReleaseDecisionCreate,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    try:
        return PilotReleaseDecisionService.create_decision(
            db,
            package_id,
            payload,
            actor=actor,
            config=settings,
        )
    except PilotReleaseDecisionAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except PilotReleaseDecisionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (
        PilotReleaseDecisionConflictError,
        PilotReleaseDecisionIntegrityError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
