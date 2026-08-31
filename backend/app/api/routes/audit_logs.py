from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import (
    AuditLogRead,
)
from backend.app.services.audit_log import (
    AuditEntityNotFoundError,
    AuditLogService,
)


router = APIRouter(
    tags=["Audit History"],
)


AUDIT_READ_ROLES = (
    "admin",
    "physician",
    "nurse",
)


def _serialize_logs(
    audit_logs,
) -> list[AuditLogRead]:
    return [
        AuditLogRead.model_validate(item)
        for item in audit_logs
    ]


@router.get(
    "/patients/{patient_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_patient_audit_logs(
    patient_id: str,
    _current_user: User = Depends(
        require_roles(*AUDIT_READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        audit_logs = (
            AuditLogService.list_for_patient(
                db,
                patient_id,
            )
        )

        return _serialize_logs(
            audit_logs
        )

    except AuditEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/visits/{visit_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_visit_audit_logs(
    visit_id: str,
    _current_user: User = Depends(
        require_roles(*AUDIT_READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        audit_logs = (
            AuditLogService.list_for_visit(
                db,
                visit_id,
            )
        )

        return _serialize_logs(
            audit_logs
        )

    except AuditEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/treatments/{treatment_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_treatment_audit_logs(
    treatment_id: str,
    _current_user: User = Depends(
        require_roles(*AUDIT_READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        audit_logs = (
            AuditLogService.list_for_treatment(
                db,
                treatment_id,
            )
        )

        return _serialize_logs(
            audit_logs
        )

    except AuditEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/protocols/{protocol_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_protocol_audit_logs(
    protocol_id: str,
    _current_user: User = Depends(
        require_roles(*AUDIT_READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        audit_logs = (
            AuditLogService.list_for_protocol(
                db,
                protocol_id,
            )
        )

        return _serialize_logs(
            audit_logs
        )

    except AuditEntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc