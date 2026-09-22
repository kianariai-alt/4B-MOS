from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.protocol_governance import (
    ProtocolGovernanceCaseCreate,
    ProtocolGovernanceCaseRead,
    ProtocolGovernanceLineageRead,
    ProtocolGovernanceRecoveryCaseCreate,
    ProtocolGovernanceRecoveryExecute,
    ProtocolGovernanceRecoveryRead,
    ProtocolGovernanceReleaseExecute,
    ProtocolGovernanceReleaseRead,
    ProtocolGovernanceReviewCreate,
    ProtocolGovernanceSignalRead,
)
from backend.app.services.protocol_governance import (
    ProtocolGovernanceAuthorizationError,
    ProtocolGovernanceConflictError,
    ProtocolGovernanceIntegrityError,
    ProtocolGovernanceNotFoundError,
    ProtocolGovernanceService,
)


router = APIRouter(tags=["Protocol Governance"])
READ_ROLES = ("admin", "physician")


def _translate(error: Exception) -> None:
    if isinstance(error, ProtocolGovernanceNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ProtocolGovernanceAuthorizationError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/learning/governance/signals",
    response_model=list[ProtocolGovernanceSignalRead],
)
def list_protocol_governance_signals(
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.list_signals(db)
    except (
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceConflictError,
    ) as error:
        _translate(error)


@router.post(
    "/protocol-governance/cases",
    response_model=ProtocolGovernanceCaseRead,
    status_code=status.HTTP_201_CREATED,
)
def create_protocol_governance_case(
    payload: ProtocolGovernanceCaseCreate,
    actor: User = Depends(require_roles("physician")),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.create_case(
            db,
            payload,
            actor=actor,
        )
    except (
        ProtocolGovernanceAuthorizationError,
        ProtocolGovernanceConflictError,
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceNotFoundError,
    ) as error:
        _translate(error)


@router.get(
    "/protocol-governance/cases",
    response_model=list[ProtocolGovernanceCaseRead],
)
def list_protocol_governance_cases(
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.list_cases(db)
    except ProtocolGovernanceIntegrityError as error:
        _translate(error)


@router.get(
    "/protocol-governance/cases/{case_id}",
    response_model=ProtocolGovernanceCaseRead,
)
def get_protocol_governance_case(
    case_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.get_case(db, case_id)
    except (
        ProtocolGovernanceNotFoundError,
        ProtocolGovernanceIntegrityError,
    ) as error:
        _translate(error)


@router.post(
    "/protocol-governance/cases/{case_id}/reviews",
    response_model=ProtocolGovernanceCaseRead,
)
def review_protocol_governance_case(
    case_id: str,
    payload: ProtocolGovernanceReviewCreate,
    actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.add_review(
            db,
            case_id,
            payload,
            actor=actor,
        )
    except (
        ProtocolGovernanceAuthorizationError,
        ProtocolGovernanceConflictError,
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceNotFoundError,
    ) as error:
        _translate(error)



@router.post(
    "/protocol-governance/cases/{case_id}/release",
    response_model=ProtocolGovernanceCaseRead,
)
def execute_protocol_governance_release(
    case_id: str,
    payload: ProtocolGovernanceReleaseExecute,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.execute_release(
            db,
            case_id,
            payload,
            actor=actor,
        )
    except (
        ProtocolGovernanceAuthorizationError,
        ProtocolGovernanceConflictError,
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceNotFoundError,
    ) as error:
        _translate(error)


@router.get(
    "/protocol-governance/releases",
    response_model=list[ProtocolGovernanceReleaseRead],
)
def list_protocol_governance_releases(
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.list_releases(db)
    except ProtocolGovernanceIntegrityError as error:
        _translate(error)



@router.post(
    "/protocol-governance/releases/{release_id}/recovery-cases",
    response_model=ProtocolGovernanceCaseRead,
    status_code=status.HTTP_201_CREATED,
)
def create_protocol_governance_recovery_case(
    release_id: str,
    payload: ProtocolGovernanceRecoveryCaseCreate,
    actor: User = Depends(require_roles("physician")),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.create_recovery_case(
            db,
            release_id,
            payload,
            actor=actor,
        )
    except (
        ProtocolGovernanceAuthorizationError,
        ProtocolGovernanceConflictError,
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceNotFoundError,
    ) as error:
        _translate(error)


@router.post(
    "/protocol-governance/cases/{case_id}/recovery",
    response_model=ProtocolGovernanceCaseRead,
)
def execute_protocol_governance_recovery(
    case_id: str,
    payload: ProtocolGovernanceRecoveryExecute,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.execute_recovery(
            db,
            case_id,
            payload,
            actor=actor,
        )
    except (
        ProtocolGovernanceAuthorizationError,
        ProtocolGovernanceConflictError,
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceNotFoundError,
    ) as error:
        _translate(error)


@router.get(
    "/protocol-governance/recoveries",
    response_model=list[ProtocolGovernanceRecoveryRead],
)
def list_protocol_governance_recoveries(
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.list_recoveries(db)
    except ProtocolGovernanceIntegrityError as error:
        _translate(error)


@router.get(
    "/protocol-governance/protocols/{protocol_id}/lineage",
    response_model=ProtocolGovernanceLineageRead,
)
def get_protocol_governance_lineage(
    protocol_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return ProtocolGovernanceService.get_lineage(db, protocol_id)
    except (
        ProtocolGovernanceIntegrityError,
        ProtocolGovernanceNotFoundError,
    ) as error:
        _translate(error)
