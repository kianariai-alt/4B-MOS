from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.db.account_transactions import AccountWriteConflictError
from backend.app.models.user import User
from backend.app.schemas.physician_questions import DraftCreate, BankReview, BankEventRead, BankWorkspaceRead, VisitQuestionBankRead
from backend.app.services.physician_questions import PhysicianQuestionService, QuestionBankNotFoundError, QuestionBankAuthorizationError, QuestionBankConflictError
from backend.app.services.reception import ReceptionNotFoundError, ReceptionConflictError

router = APIRouter(prefix="/physicians/{physician_id}/question-bank", tags=["Physician Question Bank"])
screening_router = APIRouter(tags=["Physician Question Bank"])

def _call(fn, *args, **kwargs):
    try: return fn(*args, **kwargs)
    except (QuestionBankNotFoundError, ReceptionNotFoundError) as error: raise HTTPException(404, str(error)) from error
    except QuestionBankAuthorizationError as error: raise HTTPException(403, str(error)) from error
    except (QuestionBankConflictError, ReceptionConflictError, AccountWriteConflictError) as error: raise HTTPException(409, str(error)) from error

@router.get("", response_model=BankWorkspaceRead)
def workspace(physician_id: str, actor: User = Depends(require_roles("admin", "physician")), db: Session = Depends(get_db)):
    return _call(PhysicianQuestionService.workspace, db, physician_id, actor=actor)

@router.post("/drafts", response_model=BankEventRead, status_code=201)
def draft(physician_id: str, payload: DraftCreate, actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    return _call(PhysicianQuestionService.save_draft, db, physician_id, payload, actor=actor)

@router.post("/approve", response_model=BankEventRead, status_code=201)
def approve(physician_id: str, payload: BankReview, actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    return _call(PhysicianQuestionService.review, db, physician_id, payload, actor=actor, action="approve")

@router.post("/retire", response_model=BankEventRead, status_code=201)
def retire(physician_id: str, payload: BankReview, actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    return _call(PhysicianQuestionService.review, db, physician_id, payload, actor=actor, action="retire")

@screening_router.get("/visits/{visit_id}/screening-question-bank", response_model=VisitQuestionBankRead)
def visit_bank(visit_id: str, actor: User = Depends(require_roles("admin", "operator", "physician", "nurse")), db: Session = Depends(get_db)):
    return _call(PhysicianQuestionService.approved_questions_for_visit, db, visit_id, actor=actor)
