"""Resumable encrypted media, durable job leases and physician text review."""
from datetime import datetime, timezone, timedelta
import hashlib, json, uuid
from sqlalchemy import select
from pydantic import ValidationError
from backend.app.core.config import settings
from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.recording_media import RecordingAudioTransfer, RecordingAudioChunk, RecordingTextEvent
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services.audit_context import actor_data
from backend.app.services.session_finalization import evidence_digest
from backend.app.services import recording
from backend.app.services.reception import ReceptionService
from backend.app.services.audio_crypto import enabled, key, encrypt, decrypt, digest, AudioIntegrityError, AudioConfigurationError
from backend.app.schemas.recording_media import MediaStatus, MediaWorkspace, DraftRead, ReviewRead, TranscriptContent

CHUNK_BYTES=262144
class MediaNotFoundError(Exception):pass
class MediaAuthorizationError(Exception):pass
class MediaConflictError(Exception):pass

def _authorize(db,visit_id,recording_id,actor,*,configuration=True):
    if configuration:key()
    recording._actor(db,actor)
    rows,_=recording._rows(db,visit_id)
    start=next((r for r in rows if r.recording_id==recording_id and r.action=='start'),None)
    finish=next((r for r in rows if r.recording_id==recording_id and r.action=='finish'),None)
    if start is None:raise MediaNotFoundError('Recording not found.')
    if start.recorded_by!=actor.id:raise MediaAuthorizationError('Only the recording physician can access media.')
    consent=recording._assigned(db,visit_id,actor)
    if consent.state!='granted' or consent.latest_event.sha256!=start.payload['consent_sha256']:
        raise MediaAuthorizationError('Original recording consent is no longer current and granted.')
    if finish is None or finish.payload['command']['reason']!='finished':
        raise MediaConflictError('Only normally completed recordings can be transferred.')
    return start,finish

def _time(row):return row.created_at.replace(tzinfo=timezone.utc).isoformat()
def _verify(row,fields):
    body=row.payload
    if not isinstance(body,dict) or evidence_digest(body)!=row.sha256 or any(body.get(k)!=getattr(row,k) for k in fields):
        raise MediaConflictError('Media metadata integrity failed.')
    if hasattr(row,'created_at') and body.get('created_at')!=_time(row):raise MediaConflictError('Media timestamp integrity failed.')
    return body

def _transfer(db,visit_id,recording_id,required=True):
    row=db.scalar(select(RecordingAudioTransfer).where(RecordingAudioTransfer.recording_id==recording_id,RecordingAudioTransfer.visit_id==visit_id))
    if row is None:
        if required:raise MediaNotFoundError('Audio transfer not initialized.')
        return None
    _verify(row,('id','visit_id','recording_id','start_event_id','recorded_by','pcm_bytes','key_id'))
    return row

def _chunks(db,transfer):
    rows=list(db.scalars(select(RecordingAudioChunk).where(RecordingAudioChunk.transfer_id==transfer.id).order_by(RecordingAudioChunk.chunk_index)))
    for index,row in enumerate(rows):
        _verify(row,('id','transfer_id','chunk_index','pcm_bytes','pcm_sha256'))
        length=min(CHUNK_BYTES,transfer.pcm_bytes-index*CHUNK_BYTES)
        if row.chunk_index!=index or row.pcm_bytes!=length or length<=0:raise MediaConflictError('Audio chunk sequence is inconsistent.')
    return rows

def _events(db,transfer):
    rows=list(db.scalars(select(RecordingTextEvent).where(RecordingTextEvent.transfer_id==transfer.id).order_by(RecordingTextEvent.version)))
    for version,row in enumerate(rows,1):
        _verify(row,('id','transfer_id','version','action','request_key','recorded_by'))
        if row.version!=version:raise MediaConflictError('Text history sequence is inconsistent.')
    if rows and rows[0].action!='audio_received':raise MediaConflictError('Audio receipt is missing from text history.')
    return rows

def _audit(db,row,actor):
    AuditLogRepository.create(db,entity_type=row.__tablename__,entity_id=row.id,event_type='created',event_data={'sha256':row.sha256},**actor_data(actor),commit=False)

def _blob(row,context,key_id):
    if row.encrypted_data is None or digest(row.encrypted_data)!=row.payload['cipher_sha256']:
        raise AudioIntegrityError('Encrypted media checksum failed.')
    return decrypt(row.encrypted_data,context,key_id)

def _chunk_context(transfer,index,pcm_sha,length):
    return {'transfer_id':transfer.id,'visit_id':transfer.visit_id,'recording_id':transfer.recording_id,'chunk_index':index,'pcm_sha256':pcm_sha,'pcm_bytes':length,'purpose':'audio-pcm-v1'}

def _plaintext_chunks(db,transfer):
    for chunk in _chunks(db,transfer):
        plain=_blob(chunk,_chunk_context(transfer,chunk.chunk_index,chunk.pcm_sha256,chunk.pcm_bytes),transfer.key_id)
        if len(plain)!=chunk.pcm_bytes or digest(plain)!=chunk.pcm_sha256:raise AudioIntegrityError('PCM chunk integrity failed.')
        yield plain

def _content(row,transfer):
    context={'event_id':row.id,'transfer_id':transfer.id,'version':row.version,'purpose':row.action}
    if row.payload.get('cipher_context')!=context:raise AudioIntegrityError('Text ciphertext context mismatch.')
    return json.loads(_blob(row,context,transfer.key_id))

def _append(db,transfer,rows,action,request_key,actor,command,*,content=None,details=None):
    identifier=str(uuid.uuid4());now=datetime.now(timezone.utc)
    context={'event_id':identifier,'transfer_id':transfer.id,'version':len(rows)+1,'purpose':action}
    blob=encrypt(json.dumps(content,ensure_ascii=False,separators=(',',':')).encode(),context,transfer.key_id) if content is not None else None
    body=dict(id=identifier,transfer_id=transfer.id,version=len(rows)+1,action=action,request_key=request_key,recorded_by=actor.id,created_at=now.isoformat(),command_sha256=evidence_digest(command),details=details or {},cipher_sha256=digest(blob) if blob else None,cipher_context=context if blob else None)
    row=RecordingTextEvent(**{k:body[k] for k in ('id','transfer_id','version','action','request_key','recorded_by')},created_at=now,payload=body,encrypted_data=blob,sha256=evidence_digest(body))
    db.add(row);db.flush();_audit(db,row,actor)
    return row

def _retry(rows,payload,actor,action):
    for row in rows:
        if row.request_key==payload.request_key:
            if row.action!=action or row.recorded_by!=actor.id or row.payload['command_sha256']!=evidence_digest(payload.model_dump(mode='json')):
                raise MediaConflictError('Request key already used for another command.')
            return row
    if hasattr(payload,'expected_version') and payload.expected_version!=len(rows):raise MediaConflictError('Text version changed; reload before submitting.')
    return None

def _job_state(rows):
    latest=next((r for r in reversed(rows) if r.action in {'queued','started','failed','draft'}),None)
    return latest

def _speech_ready():
    from backend.app.services.speech_engine import speech_ready
    return speech_ready()

def _status(db,recording_id,transfer):
    status=MediaStatus(recording_id=recording_id,audio_upload_enabled=enabled(),transcription_enabled=enabled() and _speech_ready())
    if transfer is None:return status
    chunks=_chunks(db,transfer);rows=_events(db,transfer)
    status.transfer_id=transfer.id;status.transfer_sha256=transfer.sha256;status.next_chunk_index=len(chunks);status.received_pcm_bytes=sum(r.pcm_bytes for r in chunks);status.expected_pcm_bytes=transfer.pcm_bytes;status.version=len(rows);status.audio_received=bool(rows)
    state=_job_state(rows)
    status.state='uploading' if not rows else 'audio_received'
    if state:
        status.state={'queued':'queued','started':'running','failed':'failed','draft':'draft'}[state.action]
        if state.action=='failed':status.failure_code=state.payload['details']['code']
    if rows and rows[-1].action=='review':status.state='reviewed'
    return status

class RecordingMediaService:
    @staticmethod
    def status(db,visit_id,recording_id,*,actor):
        _authorize(db,visit_id,recording_id,actor,configuration=False)
        return _status(db,recording_id,_transfer(db,visit_id,recording_id,False))

    @staticmethod
    def workspace(db,visit_id,recording_id,*,actor):
        _authorize(db,visit_id,recording_id,actor)
        transfer=_transfer(db,visit_id,recording_id,False)
        result=MediaWorkspace(**_status(db,recording_id,transfer).model_dump())
        if transfer is None:return result
        rows=_events(db,transfer)
        draft=next((r for r in reversed(rows) if r.action=='draft'),None)
        review=next((r for r in reversed(rows) if r.action=='review'),None)
        if draft:
            result.latest_draft=DraftRead(id=draft.id,sha256=draft.sha256,created_at=_time(draft),content=TranscriptContent(**_content(draft,transfer)))
        if review:
            content=_content(review,transfer)
            result.latest_review=ReviewRead(id=review.id,sha256=review.sha256,created_at=_time(review),draft_sha256=review.payload['details']['draft_sha256'],recorded_by=review.recorded_by,**content)
        return result

    @staticmethod
    @clinical_record_write
    def initialize(db,visit_id,recording_id,payload,*,actor):
        start,finish=_authorize(db,visit_id,recording_id,actor)
        command=payload.model_dump(mode='json');existing=_transfer(db,visit_id,recording_id,False)
        if existing:
            if existing.recorded_by!=actor.id or existing.payload['command']!=command:raise MediaConflictError('Audio transfer already initialized with different metadata.')
            return _status(db,recording_id,existing)
        f=finish.payload['command']
        if f['pcm_bytes']!=payload.pcm_bytes or f['encrypted_file_sha256']!=payload.encrypted_file_sha256:
            raise MediaConflictError('Local capture metadata does not match its finish receipt.')
        now=datetime.now(timezone.utc)
        body=dict(id=str(uuid.uuid4()),visit_id=visit_id,recording_id=recording_id,start_event_id=start.id,recorded_by=actor.id,pcm_bytes=payload.pcm_bytes,key_id=settings.AUDIO_KEY_ID,created_at=now.isoformat(),command=command,start_sha256=start.sha256,finish_sha256=finish.sha256)
        row=RecordingAudioTransfer(**{k:body[k] for k in ('id','visit_id','recording_id','start_event_id','recorded_by','pcm_bytes','key_id')},created_at=now,payload=body,sha256=evidence_digest(body))
        db.add(row);db.flush();_audit(db,row,actor)
        return _status(db,recording_id,row)

    @staticmethod
    @clinical_record_write
    def put_chunk(db,visit_id,recording_id,index,pcm,pcm_sha,*,actor):
        _authorize(db,visit_id,recording_id,actor)
        transfer=_transfer(db,visit_id,recording_id);chunks=_chunks(db,transfer)
        if digest(pcm)!=pcm_sha:raise MediaConflictError('Chunk checksum mismatch.')
        expected=min(CHUNK_BYTES,transfer.pcm_bytes-index*CHUNK_BYTES)
        if expected<=0 or len(pcm)!=expected:raise MediaConflictError('Chunk length is invalid.')
        if index<len(chunks):
            if chunks[index].pcm_sha256!=pcm_sha:raise MediaConflictError('Chunk index already contains different audio.')
            # Verify stored ciphertext even for an exact retry.
            _blob(chunks[index],_chunk_context(transfer,index,pcm_sha,len(pcm)),transfer.key_id)
            return _status(db,recording_id,transfer)
        if index!=len(chunks) or _events(db,transfer):raise MediaConflictError('Chunks must arrive in order before completion.')
        context=_chunk_context(transfer,index,pcm_sha,len(pcm));blob=encrypt(pcm,context,transfer.key_id)
        body=dict(id=str(uuid.uuid4()),transfer_id=transfer.id,chunk_index=index,pcm_bytes=len(pcm),pcm_sha256=pcm_sha,cipher_sha256=digest(blob))
        row=RecordingAudioChunk(**{k:body[k] for k in ('id','transfer_id','chunk_index','pcm_bytes','pcm_sha256')},encrypted_data=blob,payload=body,sha256=evidence_digest(body))
        db.add(row);db.flush();_audit(db,row,actor)
        return _status(db,recording_id,transfer)

    @staticmethod
    @clinical_record_write
    def complete(db,visit_id,recording_id,payload,*,actor):
        _authorize(db,visit_id,recording_id,actor);transfer=_transfer(db,visit_id,recording_id);rows=_events(db,transfer)
        retry=_retry(rows,payload,actor,'audio_received')
        if retry:return _status(db,recording_id,transfer)
        if rows:raise MediaConflictError('Audio already received.')
        if payload.expected_pcm_sha256!=transfer.payload['command']['pcm_sha256']:raise MediaConflictError('Whole-audio checksum does not match initialization.')
        sha=hashlib.sha256();size=0
        for pcm in _plaintext_chunks(db,transfer):sha.update(pcm);size+=len(pcm)
        if size!=transfer.pcm_bytes or sha.hexdigest()!=payload.expected_pcm_sha256:raise MediaConflictError('Audio is incomplete or its whole checksum is invalid.')
        _append(db,transfer,rows,'audio_received',payload.request_key,actor,payload.model_dump(mode='json'))
        return _status(db,recording_id,transfer)

    @staticmethod
    @clinical_record_write
    def enqueue(db,visit_id,recording_id,payload,*,actor):
        _authorize(db,visit_id,recording_id,actor);transfer=_transfer(db,visit_id,recording_id);rows=_events(db,transfer)
        retry=_retry(rows,payload,actor,'queued')
        if retry:return _status(db,recording_id,transfer)
        if not rows:raise MediaConflictError('Complete audio before transcription.')
        if not _speech_ready():raise AudioConfigurationError('Local Persian speech model is not ready.')
        current=_job_state(rows)
        if current and current.action=='queued':raise MediaConflictError('Transcription already queued.')
        if current and current.action=='started':
            if datetime.fromisoformat(current.payload['details']['expires_at'])>datetime.now(timezone.utc):raise MediaConflictError('Transcription already running.')
            failed=_append(db,transfer,rows,'failed',str(uuid.uuid4()),actor,{},details={'job_id':current.payload['details']['job_id'],'code':'lease_expired'});rows.append(failed)
        if current and current.action=='draft':raise MediaConflictError('A transcript exists; review it instead of replacing it.')
        _append(db,transfer,rows,'queued',payload.request_key,actor,payload.model_dump(mode='json'),details={'job_id':str(uuid.uuid4())})
        return _status(db,recording_id,transfer)

    @staticmethod
    @clinical_record_write
    def claim(db,visit_id,recording_id):
        transfer=_transfer(db,visit_id,recording_id);rows=_events(db,transfer);current=_job_state(rows)
        if current is None or current.action!='queued':return None
        actor=db.get(User,transfer.recorded_by);job=current.payload['details']['job_id']
        try:_authorize(db,visit_id,recording_id,actor)
        except (recording.RecordingAuthorizationError,MediaAuthorizationError):
            _append(db,transfer,rows,'failed',str(uuid.uuid4()),actor,{},details={'job_id':job,'code':'authorization_changed'});return None
        lease=str(uuid.uuid4())
        event=_append(db,transfer,rows,'started',str(uuid.uuid4()),actor,{},details={'job_id':job,'lease_id':lease,'expires_at':(datetime.now(timezone.utc)+timedelta(seconds=settings.SPEECH_LEASE_SECONDS)).isoformat()})
        return {'visit_id':visit_id,'recording_id':recording_id,'transfer_id':transfer.id,'lease_id':lease,'job_id':job,'claim_sha256':event.sha256}

    @staticmethod
    def read_pcm(db,claim):
        transfer=_transfer(db,claim['visit_id'],claim['recording_id']);actor=db.get(User,transfer.recorded_by)
        _authorize(db,transfer.visit_id,transfer.recording_id,actor)
        current=_job_state(_events(db,transfer))
        if current is None or current.sha256!=claim['claim_sha256']:raise MediaConflictError('Worker lease changed.')
        pcm=bytearray();sha=hashlib.sha256()
        for chunk in _plaintext_chunks(db,transfer):pcm.extend(chunk);sha.update(chunk)
        if len(pcm)!=transfer.pcm_bytes or sha.hexdigest()!=transfer.payload['command']['pcm_sha256']:raise AudioIntegrityError('Complete audio integrity failed.')
        return pcm

    @staticmethod
    @clinical_record_write
    def finish_job(db,visit_id,recording_id,claim,content=None,error_code=None):
        transfer=_transfer(db,visit_id,recording_id);rows=_events(db,transfer);current=_job_state(rows)
        if current is None or current.action!='started' or current.sha256!=claim['claim_sha256']:raise MediaConflictError('Stale worker cannot publish a result.')
        actor=db.get(User,transfer.recorded_by)
        try:_authorize(db,visit_id,recording_id,actor)
        except (recording.RecordingAuthorizationError,MediaAuthorizationError):error_code='authorization_changed'
        if not error_code:
            try:
                transcript=TranscriptContent.model_validate(content)
                if any(s.end>transfer.pcm_bytes/32000+.5 for s in transcript.segments):error_code='engine_failed'
            except ValidationError:error_code='engine_failed'
        if error_code:
            if error_code not in {'authorization_changed','engine_failed','audio_integrity','model_unavailable'}:raise ValueError('Unknown speech failure code.')
            _append(db,transfer,rows,'failed',str(uuid.uuid4()),actor,{},details={'job_id':claim['job_id'],'code':error_code})
        else:
            _append(db,transfer,rows,'draft',str(uuid.uuid4()),actor,{},content=transcript.model_dump(mode='json'),details={'job_id':claim['job_id']})
        return True

    @staticmethod
    @clinical_record_write
    def review(db,visit_id,recording_id,payload,*,actor):
        _authorize(db,visit_id,recording_id,actor);transfer=_transfer(db,visit_id,recording_id);rows=_events(db,transfer)
        retry=_retry(rows,payload,actor,'review')
        if retry:return RecordingMediaService.workspace(db,visit_id,recording_id,actor=actor)
        draft=next((r for r in reversed(rows) if r.action=='draft'),None)
        if draft is None or draft.sha256!=payload.expected_draft_sha256:raise MediaConflictError('Review must refer to the exact latest draft.')
        _content(draft,transfer)
        _append(db,transfer,rows,'review',payload.request_key,actor,payload.model_dump(mode='json'),content={'edited_text':payload.edited_text,'statement_fa':payload.statement_fa},details={'draft_sha256':draft.sha256})
        return RecordingMediaService.workspace(db,visit_id,recording_id,actor=actor)


    @staticmethod
    def revision_metrics(db,visit_id,recording_id,*,actor):
        from backend.app.schemas.speech_evaluation import RevisionMetricsRead
        from backend.app.services.speech_evaluation import compare_text, MAX_TEXT_CHARACTERS
        workspace=RecordingMediaService.workspace(db,visit_id,recording_id,actor=actor)
        draft,review=workspace.latest_draft,workspace.latest_review
        if draft is None or review is None or review.draft_sha256!=draft.sha256:
            raise MediaConflictError('A matching physician review and draft are required.')
        if max(len(draft.content.text),len(review.edited_text))>MAX_TEXT_CHARACTERS:
            raise MediaConflictError('Text exceeds the bounded comparison limit.')
        try:comparison=compare_text(review.edited_text,draft.content.text)
        except ValueError as error:raise MediaConflictError('Text exceeds the bounded normalized comparison limit.') from error
        return RevisionMetricsRead(recording_id=recording_id,draft_sha256=draft.sha256,
            review_sha256=review.sha256,comparison=comparison)
