from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.db.clinical_record_transactions import ClinicalRecordWriteConflictError
from backend.app.models.user import User
from backend.app.schemas.recording import RecordingStart, RecordingFinish, RecordingEventRead, RecordingAccess, RecordingCheck
from backend.app.services.recording import RecordingService, RecordingNotFoundError, RecordingAuthorizationError, RecordingConflictError
from backend.app.services.reception import ReceptionNotFoundError, ReceptionConflictError
router=APIRouter(prefix="/visits/{visit_id}/recordings",tags=["Windows Recording"])

def _call(fn,*args,**kwargs):
    try: return fn(*args,**kwargs)
    except (RecordingNotFoundError,ReceptionNotFoundError) as error: raise HTTPException(404,str(error)) from error
    except RecordingAuthorizationError as error: raise HTTPException(403,str(error)) from error
    except (RecordingConflictError,ReceptionConflictError,ClinicalRecordWriteConflictError) as error: raise HTTPException(409,str(error)) from error

@router.get("/access",response_model=RecordingAccess)
def access(visit_id:str,actor:User=Depends(require_roles("physician")),db:Session=Depends(get_db)):
    return _call(RecordingService.access,db,visit_id,actor=actor)

@router.post("/start",response_model=RecordingEventRead,status_code=201)
def start(visit_id:str,payload:RecordingStart,actor:User=Depends(require_roles("physician")),db:Session=Depends(get_db)):
    return _call(RecordingService.start,db,visit_id,payload,actor=actor)

@router.get("/{recording_id}/check",response_model=RecordingCheck)
def check(visit_id:str,recording_id:str,actor:User=Depends(require_roles("physician")),db:Session=Depends(get_db)):
    return _call(RecordingService.check,db,visit_id,recording_id,actor=actor)

@router.post("/finish",response_model=RecordingEventRead,status_code=201)
def finish(visit_id:str,payload:RecordingFinish,actor:User=Depends(require_roles("physician")),db:Session=Depends(get_db)):
    return _call(RecordingService.finish,db,visit_id,payload,actor=actor)
