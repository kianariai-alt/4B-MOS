import re
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.db.clinical_record_transactions import ClinicalRecordWriteConflictError
from backend.app.models.user import User
from backend.app.schemas.recording_media import InitializeAudio, CompleteAudio, TextCommand, ReviewText, MediaStatus, MediaWorkspace
from backend.app.services.recording_media import RecordingMediaService as Service, MediaNotFoundError, MediaAuthorizationError, MediaConflictError, CHUNK_BYTES
from backend.app.services.recording import RecordingNotFoundError, RecordingAuthorizationError, RecordingConflictError
from backend.app.services.reception import ReceptionNotFoundError, ReceptionConflictError
from backend.app.services.audio_crypto import AudioConfigurationError, AudioIntegrityError
router=APIRouter(prefix='/visits/{visit_id}/recordings/{recording_id}/media',tags=['Recording Media'])

def call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except (MediaNotFoundError,RecordingNotFoundError,ReceptionNotFoundError) as e:raise HTTPException(404,str(e)) from e
    except (MediaAuthorizationError,RecordingAuthorizationError) as e:raise HTTPException(403,str(e)) from e
    except (MediaConflictError,RecordingConflictError,ReceptionConflictError,ClinicalRecordWriteConflictError,AudioIntegrityError) as e:raise HTTPException(409,str(e)) from e
    except AudioConfigurationError as e:raise HTTPException(503,str(e)) from e

@router.get('',response_model=MediaStatus)
def status(visit_id:str,recording_id:str,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.status,db,visit_id,recording_id,actor=actor)

@router.get('/text',response_model=MediaWorkspace)
def workspace(visit_id:str,recording_id:str,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.workspace,db,visit_id,recording_id,actor=actor)

@router.post('/initialize',response_model=MediaStatus,status_code=201)
def initialize(visit_id:str,recording_id:str,payload:InitializeAudio,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.initialize,db,visit_id,recording_id,payload,actor=actor)

@router.put('/chunks/{index}',response_model=MediaStatus)
async def chunk(visit_id:str,recording_id:str,index:int,request:Request,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    if index<0:raise HTTPException(422,'Invalid chunk index.')
    if request.headers.get('content-type','').split(';')[0]!='application/octet-stream':raise HTTPException(415,'PCM octet stream required.')
    sha=request.headers.get('x-pcm-sha256','')
    if re.fullmatch('[0-9a-f]{64}',sha) is None:raise HTTPException(422,'Chunk checksum required.')
    pcm=bytearray()
    try:
        async for part in request.stream():
            if len(pcm)+len(part)>CHUNK_BYTES:raise HTTPException(413,'Chunk too large.')
            pcm.extend(part)
        return call(Service.put_chunk,db,visit_id,recording_id,index,bytes(pcm),sha,actor=actor)
    finally:pcm[:]=b'\0'*len(pcm)

@router.post('/complete',response_model=MediaStatus)
def complete(visit_id:str,recording_id:str,payload:CompleteAudio,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.complete,db,visit_id,recording_id,payload,actor=actor)

@router.post('/transcribe',response_model=MediaStatus,status_code=202)
def transcribe(visit_id:str,recording_id:str,payload:TextCommand,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.enqueue,db,visit_id,recording_id,payload,actor=actor)

@router.post('/review',response_model=MediaWorkspace,status_code=201)
def review(visit_id:str,recording_id:str,payload:ReviewText,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.review,db,visit_id,recording_id,payload,actor=actor)


from backend.app.schemas.speech_evaluation import RevisionMetricsRead

@router.get('/text/revision-metrics',response_model=RevisionMetricsRead)
def revision_metrics(visit_id:str,recording_id:str,actor:User=Depends(require_roles('physician')),db:Session=Depends(get_db)):
    return call(Service.revision_metrics,db,visit_id,recording_id,actor=actor)
