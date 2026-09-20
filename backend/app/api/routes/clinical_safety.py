from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.clinical_record_transactions import (
    ClinicalRecordWriteConflictError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.audit_log import AuditLogRead
from backend.app.schemas.clinical_safety import (
    SafetyEvaluationRead,
    SafetyEvaluationRequest,
    SafetyRuleCreate,
    SafetyRuleRead,
    SafetyRuleReview,
    SafetyRuleStatus,
    SafetyRuleSupersede,
    SafetyRuleUpdate,
    SafetySeverity,
)
from backend.app.services.clinical_safety import (
    ClinicalSafetyAuthorizationError,
    ClinicalSafetyConflictError,
    ClinicalSafetyEvaluationService,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyNotFoundError,
    ClinicalSafetyRuleService,
    ClinicalSafetyRuleUnavailableError,
)


router = APIRouter(tags=["Clinical Safety Rules"])

READ_RULE_ROLES = ("admin", "physician", "nurse", "operator", "viewer")
AUTHOR_ROLES = ("admin", "physician")
REVIEW_ROLES = ("admin", "physician")
EVALUATE_ROLES = ("admin", "physician")
READ_EVALUATION_ROLES = ("admin", "physician", "nurse")
AUDIT_ROLES = ("admin", "physician", "nurse")


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


SAFETY_ERRORS = (
    ClinicalSafetyNotFoundError,
    ClinicalSafetyAuthorizationError,
    ClinicalSafetyConflictError,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyRuleUnavailableError,
    ClinicalRecordWriteConflictError,
)


@router.post(
    "/safety/rules",
    response_model=SafetyRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_safety_rule(
    payload: SafetyRuleCreate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.create(db, payload, actor=actor)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get("/safety/rules", response_model=list[SafetyRuleRead])
def list_safety_rules(
    rule_status: SafetyRuleStatus | None = Query(default=None, alias="status"),
    clinical_domain: str | None = Query(default=None, min_length=2, max_length=100),
    severity: SafetySeverity | None = None,
    rule_key: str | None = Query(
        default=None,
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    ),
    search: str | None = Query(default=None, min_length=2, max_length=200),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _actor: User = Depends(require_roles(*READ_RULE_ROLES)),
    db: Session = Depends(get_db),
) -> list[SafetyRuleRead]:
    try:
        return ClinicalSafetyRuleService.list(
            db,
            status=rule_status,
            clinical_domain=clinical_domain,
            severity=severity,
            rule_key=rule_key.upper() if rule_key else None,
            search=search,
            skip=skip,
            limit=limit,
        )
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get("/safety/rules/active", response_model=list[SafetyRuleRead])
def list_active_safety_rules(
    as_of: date = Query(default_factory=date.today),
    _actor: User = Depends(require_roles(*READ_RULE_ROLES)),
    db: Session = Depends(get_db),
) -> list[SafetyRuleRead]:
    try:
        return ClinicalSafetyRuleService.list_active(db, as_of=as_of)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get(
    "/safety/rules/{rule_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_safety_rule_audit_logs(
    rule_id: str,
    _actor: User = Depends(require_roles(*AUDIT_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in ClinicalSafetyRuleService.list_audit_logs(db, rule_id)
        ]
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get("/safety/rules/{rule_id}", response_model=SafetyRuleRead)
def get_safety_rule(
    rule_id: str,
    _actor: User = Depends(require_roles(*READ_RULE_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.get(db, rule_id)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.put("/safety/rules/{rule_id}", response_model=SafetyRuleRead)
def update_safety_rule(
    rule_id: str,
    payload: SafetyRuleUpdate,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.update(db, rule_id, payload, actor=actor)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.post("/safety/rules/{rule_id}/submit", response_model=SafetyRuleRead)
def submit_safety_rule(
    rule_id: str,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.submit(db, rule_id, actor=actor)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.post("/safety/rules/{rule_id}/review", response_model=SafetyRuleRead)
def review_safety_rule(
    rule_id: str,
    payload: SafetyRuleReview,
    actor: User = Depends(require_roles(*REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.review(
            db,
            rule_id,
            payload,
            actor=actor,
        )
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.post(
    "/safety/rules/{rule_id}/supersede",
    response_model=SafetyRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def supersede_safety_rule(
    rule_id: str,
    payload: SafetyRuleSupersede,
    actor: User = Depends(require_roles(*AUTHOR_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.supersede(
            db,
            rule_id,
            payload,
            actor=actor,
        )
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.post("/safety/rules/{rule_id}/retire", response_model=SafetyRuleRead)
def retire_safety_rule(
    rule_id: str,
    actor: User = Depends(require_roles(*REVIEW_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyRuleRead:
    try:
        return ClinicalSafetyRuleService.retire(db, rule_id, actor=actor)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.post(
    "/visits/{visit_id}/safety-evaluations",
    response_model=SafetyEvaluationRead,
    status_code=status.HTTP_201_CREATED,
)
def evaluate_visit_safety(
    visit_id: str,
    payload: SafetyEvaluationRequest | None = None,
    actor: User = Depends(require_roles(*EVALUATE_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyEvaluationRead:
    try:
        return ClinicalSafetyEvaluationService.evaluate(
            db,
            visit_id,
            payload or SafetyEvaluationRequest(),
            actor=actor,
        )
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/safety-evaluations",
    response_model=list[SafetyEvaluationRead],
)
def list_visit_safety_evaluations(
    visit_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _actor: User = Depends(require_roles(*READ_EVALUATION_ROLES)),
    db: Session = Depends(get_db),
) -> list[SafetyEvaluationRead]:
    try:
        return ClinicalSafetyEvaluationService.list_by_visit(
            db,
            visit_id,
            skip=skip,
            limit=limit,
        )
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get(
    "/visits/{visit_id}/safety-evaluations/latest",
    response_model=SafetyEvaluationRead,
)
def get_latest_visit_safety_evaluation(
    visit_id: str,
    _actor: User = Depends(require_roles(*READ_EVALUATION_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyEvaluationRead:
    try:
        return ClinicalSafetyEvaluationService.get_latest_by_visit(db, visit_id)
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get(
    "/safety/evaluations/{evaluation_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_safety_evaluation_audit_logs(
    evaluation_id: str,
    _actor: User = Depends(require_roles(*AUDIT_ROLES)),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    try:
        return [
            AuditLogRead.model_validate(item)
            for item in ClinicalSafetyEvaluationService.list_audit_logs(
                db,
                evaluation_id,
            )
        ]
    except SAFETY_ERRORS as error:
        _translate_error(error)


@router.get(
    "/safety/evaluations/{evaluation_id}",
    response_model=SafetyEvaluationRead,
)
def get_safety_evaluation(
    evaluation_id: str,
    _actor: User = Depends(require_roles(*READ_EVALUATION_ROLES)),
    db: Session = Depends(get_db),
) -> SafetyEvaluationRead:
    try:
        return ClinicalSafetyEvaluationService.get(db, evaluation_id)
    except SAFETY_ERRORS as error:
        _translate_error(error)
