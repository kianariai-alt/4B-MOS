from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.clinical_context import (
    ClinicalContextSnapshotRead,
    ClinicalIntakeContent,
    ClinicalIntakeCreate,
    ClinicalIntakeRead,
    ClinicalIntakeSupersede,
    EnterClinicalRecordInError,
    ParaclinicalReportContent,
    ParaclinicalReportCreate,
    ParaclinicalReportRead,
    ParaclinicalReportSupersede,
)
from backend.app.services.clinical_context import (
    ClinicalContextAuthorizationError,
    ClinicalContextConflictError,
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_safety import clinical_context_digest


router = APIRouter(tags=["Structured Clinical Context"])

READ_ROLES = ("admin", "physician", "nurse", "operator", "viewer")
AUTHOR_ROLES = ("admin", "physician", "nurse", "operator")
FINALIZE_ROLES = ("admin", "physician")
AUDIT_ROLES = ("admin", "physician", "nurse")


def _translate_error(error: Exception) -> None:
    if isinstance(error, ClinicalContextNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    if isinstance(error, ClinicalContextAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    ) from error


CLINICAL_ERRORS = (
    ClinicalContextNotFoundError,
    ClinicalContextAuthorizationError,
    ClinicalContextConflictError,
    ClinicalContextIntegrityError,
    ClinicalRecordWriteConflictError,
)


@router.post(
    "/visits/{visit_id}/clinical-intakes",
    response_model=ClinicalIntakeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_clinical_intake(
    visit_id: str,
    payload: ClinicalIntakeCreate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalIntakeRead:
    try:
        return ClinicalContextService.create_intake(
            db,
            visit_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)

@router.get(
    "/visits/{visit_id}/clinical-intakes",
    response_model=list[ClinicalIntakeRead],
)
def list_clinical_intakes(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[ClinicalIntakeRead]:
    try:
        return ClinicalContextService.list_intakes(db, visit_id)
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/clinical-context",
    response_model=ClinicalContextSnapshotRead,
)
def get_current_clinical_context(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalContextSnapshotRead:
    try:
        context = ClinicalContextService.get_current_context(db, visit_id)
        return ClinicalContextSnapshotRead(
            **context.model_dump(),
            clinical_context_sha256=clinical_context_digest(context),
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.get(
    "/clinical-intakes/{intake_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_clinical_intake_audit_logs(
    intake_id: str,
    _actor: User = Depends(require_roles(*AUDIT_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(record)
            for record in ClinicalContextService.list_intake_audit_logs(
                db,
                intake_id,
            )
        ]
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.get(
    "/clinical-intakes/{intake_id}",
    response_model=ClinicalIntakeRead,
)
def get_clinical_intake(
    intake_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalIntakeRead:
    try:
        return ClinicalContextService.get_intake(db, intake_id)
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.put(
    "/clinical-intakes/{intake_id}",
    response_model=ClinicalIntakeRead,
)
def replace_clinical_intake(
    intake_id: str,
    payload: ClinicalIntakeContent,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalIntakeRead:
    try:
        return ClinicalContextService.update_intake(
            db,
            intake_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/clinical-intakes/{intake_id}/finalize",
    response_model=ClinicalIntakeRead,
)
def finalize_clinical_intake(
    intake_id: str,
    actor: User = Depends(require_roles(*FINALIZE_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalIntakeRead:
    try:
        return ClinicalContextService.finalize_intake(
            db,
            intake_id,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/clinical-intakes/{intake_id}/supersede",
    response_model=ClinicalIntakeRead,
    status_code=status.HTTP_201_CREATED,
)
def supersede_clinical_intake(
    intake_id: str,
    payload: ClinicalIntakeSupersede,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalIntakeRead:
    try:
        return ClinicalContextService.supersede_intake(
            db,
            intake_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/clinical-intakes/{intake_id}/entered-in-error",
    response_model=ClinicalIntakeRead,
)
def enter_clinical_intake_in_error(
    intake_id: str,
    payload: EnterClinicalRecordInError,
    actor: User = Depends(require_roles(*FINALIZE_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalIntakeRead:
    try:
        return ClinicalContextService.enter_intake_in_error(
            db,
            intake_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/visits/{visit_id}/paraclinical-reports",
    response_model=ParaclinicalReportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_paraclinical_report(
    visit_id: str,
    payload: ParaclinicalReportCreate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> ParaclinicalReportRead:
    try:
        return ClinicalContextService.create_report(
            db,
            visit_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/paraclinical-reports",
    response_model=list[ParaclinicalReportRead],
)
def list_paraclinical_reports(
    visit_id: str,
    report_key: str | None = Query(
        default=None,
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    ),
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[ParaclinicalReportRead]:
    try:
        return ClinicalContextService.list_reports(
            db,
            visit_id,
            report_key=report_key,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.get(
    "/paraclinical-reports/{report_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_paraclinical_report_audit_logs(
    report_id: str,
    _actor: User = Depends(require_roles(*AUDIT_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(record)
            for record in ClinicalContextService.list_report_audit_logs(
                db,
                report_id,
            )
        ]
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.get(
    "/paraclinical-reports/{report_id}",
    response_model=ParaclinicalReportRead,
)
def get_paraclinical_report(
    report_id: str,
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> ParaclinicalReportRead:
    try:
        return ClinicalContextService.get_report(db, report_id)
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.put(
    "/paraclinical-reports/{report_id}",
    response_model=ParaclinicalReportRead,
)
def replace_paraclinical_report(
    report_id: str,
    payload: ParaclinicalReportContent,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> ParaclinicalReportRead:
    try:
        return ClinicalContextService.update_report(
            db,
            report_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/paraclinical-reports/{report_id}/finalize",
    response_model=ParaclinicalReportRead,
)
def finalize_paraclinical_report(
    report_id: str,
    actor: User = Depends(require_roles(*FINALIZE_ROLES)),
    db: Session = Depends(get_db),
) -> ParaclinicalReportRead:
    try:
        return ClinicalContextService.finalize_report(
            db,
            report_id,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/paraclinical-reports/{report_id}/supersede",
    response_model=ParaclinicalReportRead,
    status_code=status.HTTP_201_CREATED,
)
def supersede_paraclinical_report(
    report_id: str,
    payload: ParaclinicalReportSupersede,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> ParaclinicalReportRead:
    try:
        return ClinicalContextService.supersede_report(
            db,
            report_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)


@router.post(
    "/paraclinical-reports/{report_id}/entered-in-error",
    response_model=ParaclinicalReportRead,
)
def enter_paraclinical_report_in_error(
    report_id: str,
    payload: EnterClinicalRecordInError,
    actor: User = Depends(require_roles(*FINALIZE_ROLES)),
    db: Session = Depends(get_db),
) -> ParaclinicalReportRead:
    try:
        return ClinicalContextService.enter_report_in_error(
            db,
            report_id,
            payload,
            actor=actor,
        )
    except CLINICAL_ERRORS as error:
        _translate_error(error)
