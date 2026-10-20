"""Experimental, role-gated sidecar to the existing Physician Copilot."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.api.routes.physician_copilot import COPILOT_ERRORS
from backend.app.core.config import settings
from backend.app.db.clinical_record_transactions import ClinicalRecordWriteConflictError
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.clinical_integration import (
    CONTRACT_VERSION, CoreOutput, DecisionSupportResult, IntegrationAuditEvent,
    IntegrationCopilotView, IntegrationReviewCreate, IntegrationRunCreate,
    IntegrationRunRead, PhysicianReview,
)
from backend.app.services.clinical_integration.adapters import local_adapters
from backend.app.services.clinical_integration.service import (
    ClinicalIntegrationService, IntegrationAuthorizationError, IntegrationConflictError,
    IntegrationIntegrityError, IntegrationNotFoundError,
)
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError, MedicalKnowledgeNotFoundError
from backend.app.services.clinical_safety import ClinicalSafetyRuleUnavailableError
from backend.app.schemas.clinical_intelligence import IntegratedClinicalSnapshot
from backend.app.schemas.clinical_decision_exchange import DecisionModelResult
from backend.app.services.clinical_integration.read_only import get_clinical_intelligence
from sqlalchemy.exc import SQLAlchemyError


def require_enabled(response: Response):
    if not settings.CLINICAL_INTEGRATION_ENABLED:
        raise HTTPException(status_code=404, detail="Clinical integration preview is disabled.")
    response.headers["Cache-Control"] = "no-store"


def get_integration_adapters():
    return local_adapters()


def get_decision_adapter():
    # No model or synthetic adapter is registered for real patient records.
    return None


router = APIRouter(tags=["Clinical Integration Preview"], dependencies=[Depends(require_enabled)])
ERRORS = (
    *COPILOT_ERRORS, ClinicalRecordWriteConflictError,
    MedicalKnowledgeIntegrityError, MedicalKnowledgeNotFoundError,
    IntegrationAuthorizationError, IntegrationConflictError, IntegrationIntegrityError,
    IntegrationNotFoundError,
    ValidationError, ClinicalSafetyRuleUnavailableError,
)


def translate(error):
    if isinstance(error, IntegrationNotFoundError):
        raise HTTPException(status_code=404, detail="Integration resource was not found.") from error
    if isinstance(error, IntegrationAuthorizationError):
        raise HTTPException(status_code=403, detail="Physician authorization required.") from error
    raise HTTPException(status_code=409, detail="Integration dependencies changed or failed validation; reload for review.") from error


@router.get("/visits/{visit_id}/clinical-intelligence", response_model=IntegratedClinicalSnapshot)
def clinical_intelligence(
    visit_id: str, actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db), adapters=Depends(get_integration_adapters),
    decision_adapter=Depends(get_decision_adapter),
):
    try:
        return get_clinical_intelligence(db, visit_id, actor=actor, adapters=adapters,
                                         decision_adapter=decision_adapter)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Integration dependencies are unavailable.") from error
    except (*ERRORS, ValueError) as error:
        translate(error)


@router.get("/clinical-integration/contract")
def contract(_actor: User = Depends(require_roles("admin", "physician"))):
    return {
        "contract_version": CONTRACT_VERSION,
        "core_output": CoreOutput.model_json_schema(),
        "decision_support_result": DecisionSupportResult.model_json_schema(),
        "decision_model_result": DecisionModelResult.model_json_schema(),
        "integrated_clinical_snapshot": IntegratedClinicalSnapshot.model_json_schema(),
    }


@router.post("/visits/{visit_id}/clinical-integration/runs", response_model=IntegrationRunRead, status_code=201)
def create_run(
    visit_id: str, payload: IntegrationRunCreate,
    actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db), adapters=Depends(get_integration_adapters),
):
    try:
        return ClinicalIntegrationService.create(db, visit_id, payload, actor=actor, adapters=adapters)
    except ERRORS as error:
        translate(error)


@router.get("/visits/{visit_id}/clinical-integration/runs/{run_id}", response_model=IntegrationRunRead)
def get_run(
    visit_id: str, run_id: str, actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db), adapters=Depends(get_integration_adapters),
):
    try:
        return ClinicalIntegrationService.get(db, visit_id, run_id, actor=actor, adapters=adapters)
    except ERRORS as error:
        translate(error)


@router.post("/visits/{visit_id}/clinical-integration/runs/{run_id}/reviews", response_model=PhysicianReview, status_code=201)
def review_run(
    visit_id: str, run_id: str, payload: IntegrationReviewCreate,
    actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db),
    adapters=Depends(get_integration_adapters),
):
    try:
        return ClinicalIntegrationService.review(db, visit_id, run_id, payload, actor=actor, adapters=adapters)
    except ERRORS as error:
        translate(error)


@router.get("/visits/{visit_id}/clinical-integration/runs/{run_id}/audit-events", response_model=tuple[IntegrationAuditEvent, ...])
def audit_run(
    visit_id: str, run_id: str, actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
):
    try:
        return ClinicalIntegrationService.audit(db, visit_id, run_id, actor=actor)
    except ERRORS as error:
        translate(error)


@router.get("/visits/{visit_id}/physician-copilot/integration", response_model=IntegrationCopilotView)
def copilot_integration(
    visit_id: str, actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db), adapters=Depends(get_integration_adapters),
):
    try:
        return ClinicalIntegrationService.copilot_view(db, visit_id, actor=actor, adapters=adapters)
    except ERRORS as error:
        translate(error)
