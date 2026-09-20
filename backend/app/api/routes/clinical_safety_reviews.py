from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.clinical_safety_review import (
    SafetyFindingReviewCreate,
    SafetyFindingReviewRead,
    SafetyFindingReviewTimelineRead,
)
from backend.app.services.clinical_safety import (
    ClinicalSafetyAuthorizationError,
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyNotFoundError,
)
from backend.app.services.clinical_safety_review import (
    ClinicalSafetyFindingReviewService,
)


router = APIRouter(tags=["Clinical Safety Finding Reviews"])

REVIEW_EVENT_ROLES = ("physician", "nurse")
READ_REVIEW_ROLES = ("admin", "physician", "nurse")


def _translate_error(error: Exception) -> None:
    if isinstance(error, ClinicalSafetyNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    if isinstance(error, ClinicalSafetyAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


REVIEW_ERRORS = (
    ClinicalSafetyNotFoundError,
    ClinicalSafetyAuthorizationError,
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
    ClinicalRecordWriteConflictError,
)


@router.post(
    "/visits/{visit_id}/safety-findings/{finding_id}/reviews",
    response_model=SafetyFindingReviewTimelineRead,
    status_code=status.HTTP_201_CREATED,
)
def create_safety_finding_review(
    visit_id: str,
    finding_id: str,
    payload: SafetyFindingReviewCreate,
    actor: User = Depends(require_roles(*REVIEW_EVENT_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyFindingReviewTimelineRead:
    try:
        return ClinicalSafetyFindingReviewService.create(
            db,
            visit_id,
            finding_id,
            payload,
            actor=actor,
        )
    except REVIEW_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/safety-findings/{finding_id}/reviews",
    response_model=SafetyFindingReviewTimelineRead,
)
def get_safety_finding_review_timeline(
    visit_id: str,
    finding_id: str,
    _actor: User = Depends(require_roles(*READ_REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyFindingReviewTimelineRead:
    try:
        return ClinicalSafetyFindingReviewService.get_timeline(
            db,
            visit_id,
            finding_id,
        )
    except REVIEW_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/safety-findings/{finding_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_safety_finding_review_audit_logs(
    visit_id: str,
    finding_id: str,
    _actor: User = Depends(require_roles(*READ_REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in ClinicalSafetyFindingReviewService.list_audit_logs(
                db,
                visit_id,
                finding_id,
            )
        ]
    except REVIEW_ERRORS as error:
        _translate_error(error)


@router.get(
    "/safety/finding-reviews/{review_id}",
    response_model=SafetyFindingReviewRead,
)
def get_safety_finding_review(
    review_id: str,
    _actor: User = Depends(require_roles(*READ_REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyFindingReviewRead:
    try:
        return ClinicalSafetyFindingReviewService.get(db, review_id)
    except REVIEW_ERRORS as error:
        _translate_error(error)
