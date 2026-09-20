from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.clinical_evidence import (
    ClinicalEvidenceBriefCreate,
    ClinicalEvidenceBriefRead,
)
from backend.app.services.clinical_evidence import (
    ClinicalEvidenceAuthorizationError,
    ClinicalEvidenceBriefService,
    ClinicalEvidenceConflictError,
    ClinicalEvidenceIntegrityError,
    ClinicalEvidenceNotFoundError,
)


router = APIRouter(tags=["Clinical Evidence Briefs"])

CREATE_ROLES = ("physician",)
READ_ROLES = ("admin", "physician", "nurse")


def _translate_error(error: Exception) -> None:
    if isinstance(error, ClinicalEvidenceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    if isinstance(error, ClinicalEvidenceAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


EVIDENCE_ERRORS = (
    ClinicalEvidenceNotFoundError,
    ClinicalEvidenceAuthorizationError,
    ClinicalEvidenceConflictError,
    ClinicalEvidenceIntegrityError,
    ClinicalRecordWriteConflictError,
)


@router.post(
    "/visits/{visit_id}/evidence-briefs",
    response_model=ClinicalEvidenceBriefRead,
    status_code=status.HTTP_201_CREATED,
)
def create_clinical_evidence_brief(
    visit_id: str,
    payload: ClinicalEvidenceBriefCreate,
    actor: User = Depends(require_roles(*CREATE_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalEvidenceBriefRead:
    try:
        return ClinicalEvidenceBriefService.create(
            db,
            visit_id,
            payload,
            actor=actor,
        )
    except EVIDENCE_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/evidence-briefs",
    response_model=list[ClinicalEvidenceBriefRead],
)
def list_clinical_evidence_briefs(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[ClinicalEvidenceBriefRead]:
    try:
        return ClinicalEvidenceBriefService.list_for_visit(db, visit_id)
    except EVIDENCE_ERRORS as error:
        _translate_error(error)


@router.get(
    "/evidence-briefs/{brief_id}",
    response_model=ClinicalEvidenceBriefRead,
)
def get_clinical_evidence_brief(
    brief_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalEvidenceBriefRead:
    try:
        return ClinicalEvidenceBriefService.get(db, brief_id)
    except EVIDENCE_ERRORS as error:
        _translate_error(error)


@router.get(
    "/evidence-briefs/{brief_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_clinical_evidence_brief_audit_logs(
    brief_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in ClinicalEvidenceBriefService.list_audit_logs(
                db,
                brief_id,
            )
        ]
    except EVIDENCE_ERRORS as error:
        _translate_error(error)
