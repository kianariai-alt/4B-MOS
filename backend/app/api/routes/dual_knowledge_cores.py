"""Authorized read-only manifest for dual orthopedic and imaging knowledge cores."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.dual_knowledge_cores import DualKnowledgeManifest
from backend.app.services.dual_knowledge_cores import DualKnowledgeCoreService
from backend.app.services.medical_knowledge import MedicalKnowledgeIntegrityError


router = APIRouter(prefix="/knowledge/cores", tags=["Dual Knowledge Cores"])


@router.get("/manifest", response_model=DualKnowledgeManifest)
def get_dual_knowledge_manifest(
    as_of: date | None = Query(default=None),
    _actor: User = Depends(require_roles("admin", "physician")),
    db: Session = Depends(get_db),
) -> DualKnowledgeManifest:
    try:
        return DualKnowledgeCoreService.get_manifest(db, as_of=as_of or date.today())
    except MedicalKnowledgeIntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Medical knowledge integrity validation failed.",
        ) from error
