from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.db.clinical_record_transactions import ClinicalRecordWriteConflictError
from backend.app.models.user import User
from backend.app.schemas.reception import (
    ConsentCreate,
    EvidenceRead,
    ReceptionCreate,
    ReceptionWorkspace,
)
from backend.app.services.reception import (
    ReceptionService,
    ReceptionNotFoundError,
    ReceptionConflictError,
    ReceptionAuthorizationError,
)

router = APIRouter(
    prefix="/visits/{visit_id}/reception", tags=["Reception and Consent"]
)
READ = ("admin", "operator", "physician", "nurse")
WRITE = ("admin", "operator", "physician")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ReceptionNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except (ReceptionConflictError, ClinicalRecordWriteConflictError) as error:
        raise HTTPException(409, str(error)) from error
    except ReceptionAuthorizationError as error:
        raise HTTPException(403, str(error)) from error


@router.get("", response_model=ReceptionWorkspace)
def workspace(
    visit_id: str,
    actor: User = Depends(require_roles(*READ)),
    db: Session = Depends(get_db),
):
    return _call(ReceptionService.workspace, db, visit_id)


@router.post("/intakes", response_model=EvidenceRead, status_code=201)
def intake(
    visit_id: str,
    payload: ReceptionCreate,
    actor: User = Depends(require_roles(*WRITE)),
    db: Session = Depends(get_db),
):
    return _call(ReceptionService.save_intake, db, visit_id, payload, actor=actor)


@router.get("/intakes", response_model=list[EvidenceRead])
def intakes(
    visit_id: str,
    actor: User = Depends(require_roles(*READ)),
    db: Session = Depends(get_db),
):
    return _call(ReceptionService.history, db, visit_id)


@router.post("/consents", response_model=EvidenceRead, status_code=201)
def consent(
    visit_id: str,
    payload: ConsentCreate,
    actor: User = Depends(require_roles(*WRITE)),
    db: Session = Depends(get_db),
):
    return _call(ReceptionService.record_consent, db, visit_id, payload, actor=actor)


@router.get("/consents", response_model=list[EvidenceRead])
def consents(
    visit_id: str,
    actor: User = Depends(require_roles(*READ)),
    db: Session = Depends(get_db),
):
    return _call(ReceptionService.history, db, visit_id, consent=True)
