from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.medical_knowledge import (
    KnowledgeFactCreate,
    KnowledgeFactRead,
    KnowledgeFactReview,
    KnowledgeFactStatus,
    KnowledgeFactSupersede,
    KnowledgeFactUpdate,
    KnowledgeTherapyType,
)
from backend.app.services.medical_knowledge import (
    MedicalKnowledgeAuthorizationError,
    MedicalKnowledgeConflictError,
    MedicalKnowledgeIntegrityError,
    MedicalKnowledgeNotFoundError,
    MedicalKnowledgeService,
)


router = APIRouter(
    prefix="/knowledge/facts",
    tags=["Medical Knowledge"],
)

READ_ROLES = ("admin", "physician", "nurse", "operator", "viewer")
AUTHOR_ROLES = ("admin", "physician")
REVIEW_ROLES = ("admin", "physician")
AUDIT_ROLES = ("admin", "physician", "nurse")


def _translate_error(error: Exception) -> None:
    if isinstance(error, MedicalKnowledgeNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    if isinstance(error, MedicalKnowledgeAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


@router.post(
    "",
    response_model=KnowledgeFactRead,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_fact(
    payload: KnowledgeFactCreate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.create(db, payload, actor=actor)
    except (
        MedicalKnowledgeAuthorizationError,
        MedicalKnowledgeConflictError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.get(
    "",
    response_model=list[KnowledgeFactRead],
)
def list_knowledge_facts(
    fact_status: KnowledgeFactStatus | None = Query(
        default=None,
        alias="status",
    ),
    clinical_domain: str | None = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    therapy_type: KnowledgeTherapyType | None = Query(default=None),
    fact_key: str | None = Query(
        default=None,
        min_length=3,
        max_length=100,
    ),
    search: str | None = Query(
        default=None,
        min_length=2,
        max_length=200,
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[KnowledgeFactRead]:
    try:
        return MedicalKnowledgeService.list(
            db,
            status=fact_status,
            clinical_domain=clinical_domain,
            therapy_type=therapy_type,
            fact_key=fact_key,
            search=search,
            skip=skip,
            limit=limit,
        )
    except MedicalKnowledgeIntegrityError as error:
        _translate_error(error)


@router.get(
    "/approved",
    response_model=list[KnowledgeFactRead],
)
def list_approved_knowledge_facts(
    as_of: date | None = Query(default=None),
    clinical_domain: str | None = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    therapy_type: KnowledgeTherapyType | None = Query(default=None),
    search: str | None = Query(
        default=None,
        min_length=2,
        max_length=200,
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[KnowledgeFactRead]:
    try:
        return MedicalKnowledgeService.list_approved(
            db,
            as_of=as_of or date.today(),
            clinical_domain=clinical_domain,
            therapy_type=therapy_type,
            search=search,
            skip=skip,
            limit=limit,
        )
    except MedicalKnowledgeIntegrityError as error:
        _translate_error(error)


@router.get(
    "/{fact_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_knowledge_fact_audit_logs(
    fact_id: str,
    _actor: User = Depends(require_roles(*AUDIT_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in MedicalKnowledgeService.list_audit_logs(db, fact_id)
        ]
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.get(
    "/{fact_id}",
    response_model=KnowledgeFactRead,
)
def get_knowledge_fact(
    fact_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.get(db, fact_id)
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.patch(
    "/{fact_id}",
    response_model=KnowledgeFactRead,
)
def update_knowledge_fact(
    fact_id: str,
    payload: KnowledgeFactUpdate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.update(
            db,
            fact_id,
            payload,
            actor=actor,
        )
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeAuthorizationError,
        MedicalKnowledgeConflictError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.post(
    "/{fact_id}/submit",
    response_model=KnowledgeFactRead,
)
def submit_knowledge_fact(
    fact_id: str,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.submit(db, fact_id, actor=actor)
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeAuthorizationError,
        MedicalKnowledgeConflictError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.post(
    "/{fact_id}/review",
    response_model=KnowledgeFactRead,
)
def review_knowledge_fact(
    fact_id: str,
    payload: KnowledgeFactReview,
    actor: User = Depends(require_roles(*REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.review(
            db,
            fact_id,
            payload,
            actor=actor,
        )
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeAuthorizationError,
        MedicalKnowledgeConflictError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.post(
    "/{fact_id}/supersede",
    response_model=KnowledgeFactRead,
    status_code=status.HTTP_201_CREATED,
)
def supersede_knowledge_fact(
    fact_id: str,
    payload: KnowledgeFactSupersede,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.supersede(
            db,
            fact_id,
            payload,
            actor=actor,
        )
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeAuthorizationError,
        MedicalKnowledgeConflictError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)


@router.post(
    "/{fact_id}/retire",
    response_model=KnowledgeFactRead,
)
def retire_knowledge_fact(
    fact_id: str,
    actor: User = Depends(require_roles(*REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> KnowledgeFactRead:
    try:
        return MedicalKnowledgeService.retire(db, fact_id, actor=actor)
    except (
        MedicalKnowledgeNotFoundError,
        MedicalKnowledgeAuthorizationError,
        MedicalKnowledgeConflictError,
        MedicalKnowledgeIntegrityError,
    ) as error:
        _translate_error(error)
