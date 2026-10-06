"""Synthetic PCM only: transfer, consent, encryption and review integration."""
import base64, hashlib, uuid, json
import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.recording_media import RecordingAudioTransfer,RecordingAudioChunk,RecordingTextEvent
from backend.app.services.recording_media import RecordingMediaService as Service,MediaConflictError
from backend.tests.test_recording import setup,consent,start_command,finish_command
from backend.tests.test_treatment_options_roadmap import create_role_headers
pytestmark=pytest.mark.usefixtures('authenticated_admin')

@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings,'AUDIO_PIPELINE_ENABLED',True)
    monkeypatch.setattr(settings,'AUDIO_ENCRYPTION_KEY',SecretStr(base64.b64encode(b'k'*32).decode()))
    monkeypatch.setattr('backend.app.services.recording_media._speech_ready',lambda:True)

def prepared(client,db,size=32000):
    h,doctor,v,root=setup(client,db);c=consent(client,root)
    start=client.post(root+'/recordings/start',headers=h,json=start_command(c['sha256'])).json()
    pcm=(b'\x01\x02'*(size//2))
    finish={**finish_command(start),'pcm_bytes':len(pcm)}
    assert client.post(root+'/recordings/finish',headers=h,json=finish).status_code==201
    url=root+'/recordings/'+start['recording_id']+'/media'
    command=dict(request_key='audio-init-0001',pcm_bytes=len(pcm),pcm_sha256=hashlib.sha256(pcm).hexdigest(),encrypted_file_sha256='a'*64)
    return h,doctor,v,root,start['recording_id'],url,pcm,command

def send(client,h,url,pcm):
    return client.put(url+'/chunks/0',headers={**h,'Content-Type':'application/octet-stream','X-PCM-SHA256':hashlib.sha256(pcm).hexdigest()},content=pcm)

def received(client,db):
    h,d,v,root,r,url,pcm,cmd=prepared(client,db)
    assert client.post(url+'/initialize',headers=h,json=cmd).status_code==201
    assert send(client,h,url,pcm).status_code==200
    complete=dict(request_key='audio-complete-0001',expected_pcm_sha256=cmd['pcm_sha256'])
    assert client.post(url+'/complete',headers=h,json=complete).status_code==200
    return h,d,v,root,r,url,pcm,cmd

def draft(client,db):
    h,d,v,root,r,url,pcm,cmd=received(client,db)
    response=client.post(url+'/transcribe',headers=h,json=dict(expected_version=1,request_key='speech-queue-0001'))
    assert response.status_code==202,response.text
    claim=Service.claim(db,v,r)
    assert bytes(Service.read_pcm(db,claim))==pcm
    content=dict(text='متن ساختگی برای آزمون',language='fa',engine='faster-whisper',model_id='synthetic',model_fingerprint='1'*64,segments=[dict(start=0,end=.9,text='متن ساختگی برای آزمون',speaker='unknown')],speaker_identification_verified=False)
    Service.finish_job(db,v,r,claim,content)
    return h,d,v,root,r,url,claim,content

def test_resumable_idempotent_encrypted_and_no_training(client,db_session):
    h,d,v,root,r,url,pcm,cmd=prepared(client,db_session)
    first=client.post(url+'/initialize',headers=h,json=cmd)
    assert first.status_code==201,first.text
    assert client.post(url+'/initialize',headers=h,json=cmd).json()['transfer_id']==first.json()['transfer_id']
    assert client.post(url+'/initialize',headers=h,json={**cmd,'pcm_sha256':'0'*64}).status_code==409
    assert client.post(url+'/complete',headers=h,json=dict(request_key='complete-too-early',expected_pcm_sha256=cmd['pcm_sha256'])).status_code==409
    assert send(client,h,url,pcm).status_code==200
    assert send(client,h,url,pcm).json()['next_chunk_index']==1
    assert send(client,h,url,b'\x00'*len(pcm)).status_code==409
    chunk=db_session.scalar(select(RecordingAudioChunk))
    assert pcm not in chunk.encrypted_data and len(chunk.encrypted_data)==len(pcm)+28
    complete=dict(request_key='audio-complete-0001',expected_pcm_sha256=cmd['pcm_sha256'])
    for _ in range(2):
        result=client.post(url+'/complete',headers=h,json=complete)
        assert result.status_code==200,result.text
        assert result.json()['audio_received'] is True
        assert result.json()['training_enabled'] is result.json()['authorizes_diagnosis'] is False
    assert result.headers['cache-control']=='no-store'
    assert len(list(db_session.scalars(select(RecordingTextEvent))))==1

def test_chunk_limits_and_bad_hash(client,db_session):
    h,d,v,root,r,url,pcm,cmd=prepared(client,db_session)
    client.post(url+'/initialize',headers=h,json=cmd)
    assert client.put(url+'/chunks/0',headers={**h,'Content-Type':'application/octet-stream','X-PCM-SHA256':'0'*64},content=pcm).status_code==409
    assert send(client,h,url,b'0'*262146).status_code==413
    assert client.put(url+'/chunks/-1',headers=h,content=pcm).status_code==422
    assert client.put(url+'/chunks/0',headers=h,content=pcm).status_code==415
    assert db_session.scalar(select(RecordingAudioChunk)) is None

def test_revoked_consent_blocks_upload_and_worker_publish(client,db_session):
    h,d,v,root,r,url,pcm,cmd=received(client,db_session)
    client.post(url+'/transcribe',headers=h,json=dict(expected_version=1,request_key='speech-queue-0001'))
    claim=Service.claim(db_session,v,r)
    consent(client,root,state='withdrawn',version=1,key='withdraw-for-media')
    assert send(client,h,url,pcm).status_code==403
    assert client.get(url,headers=h).status_code==403
    Service.finish_job(db_session,v,r,claim,error_code='engine_failed')
    rows=list(db_session.scalars(select(RecordingTextEvent).order_by(RecordingTextEvent.version)))
    assert rows[-1].action=='failed' and rows[-1].payload['details']['code']=='authorization_changed'
    assert not any(row.action=='draft' for row in rows)

def test_doctor_review_preserves_draft_and_encrypts_text(client,db_session):
    h,d,v,root,r,url,claim,content=draft(client,db_session)
    workspace=client.get(url+'/text',headers=h).json()
    assert workspace['latest_draft']['reviewed_by_physician'] is False
    review=dict(expected_version=4,request_key='text-review-0001',expected_draft_sha256=workspace['latest_draft']['sha256'],edited_text='متن اصلاح شده و ساختگی پزشک',statement_fa='متن را با گفتگوی ویزیت تطبیق دادم و اصلاح کردم.')
    result=client.post(url+'/review',headers=h,json=review)
    assert result.status_code==201,result.text
    assert result.json()['latest_review']['reviewed_by_physician'] is True
    assert result.json()['latest_draft']['content']==content
    assert client.post(url+'/review',headers=h,json=review).json()['version']==5
    assert client.post(url+'/review',headers=h,json={**review,'edited_text':'متن دیگر'}).status_code==409
    for row in db_session.scalars(select(RecordingTextEvent)):
        assert 'متن' not in json.dumps(row.payload,ensure_ascii=False)
        if row.encrypted_data:assert content['text'].encode() not in row.encrypted_data
    with pytest.raises(MediaConflictError,match='Stale'):
        Service.finish_job(db_session,v,r,claim,content)

def test_other_physician_and_roles_cannot_read(client,db_session):
    h,d,v,root,r,url,pcm,cmd=received(client,db_session)
    for role in ('physician','admin','operator','viewer'):
        other=create_role_headers(client,username='media-'+role,role=role)
        assert client.get(url+'/text',headers=other).status_code==403

def test_tampered_ciphertext_fails_closed(client,db_session):
    h,d,v,root,r,url,pcm,cmd=received(client,db_session)
    row=db_session.scalar(select(RecordingAudioChunk))
    db_session.execute(text('UPDATE recording_audio_chunks SET encrypted_data=:blob WHERE id=:id'),dict(blob=b'broken',id=row.id));db_session.commit()
    client.post(url+'/transcribe',headers=h,json=dict(expected_version=1,request_key='speech-queue-0001'))
    claim=Service.claim(db_session,v,r)
    from backend.app.services.audio_crypto import AudioIntegrityError
    with pytest.raises(AudioIntegrityError):Service.read_pcm(db_session,claim)

def test_disabled_configuration_never_accepts_audio(client,db_session,monkeypatch):
    h,d,v,root,r,url,pcm,cmd=prepared(client,db_session)
    monkeypatch.setattr(settings,'AUDIO_PIPELINE_ENABLED',False)
    assert client.get(url,headers=h).json()['audio_upload_enabled'] is False
    assert client.post(url+'/initialize',headers=h,json=cmd).status_code==503

def test_multi_chunk_resume_and_out_of_order(client,db_session):
    h,d,v,root,r,url,pcm,cmd=prepared(client,db_session,size=300000)
    client.post(url+'/initialize',headers=h,json=cmd)
    def put(index,data):return client.put(url+f'/chunks/{index}',headers={**h,'Content-Type':'application/octet-stream','X-PCM-SHA256':hashlib.sha256(data).hexdigest()},content=data)
    assert put(1,pcm[262144:]).status_code==409
    assert put(0,pcm[:262144]).json()['received_pcm_bytes']==262144
    assert client.get(url,headers=h).json()['next_chunk_index']==1
    assert put(1,pcm[262144:]).status_code==200
    assert client.post(url+'/complete',headers=h,json=dict(request_key='audio-complete-0001',expected_pcm_sha256=cmd['pcm_sha256'])).json()['audio_received'] is True

def test_queue_idempotency_and_single_worker_claim(client,db_session):
    h,d,v,root,r,url,pcm,cmd=received(client,db_session)
    command=dict(expected_version=1,request_key='speech-queue-0001')
    first=client.post(url+'/transcribe',headers=h,json=command)
    assert first.status_code==202
    assert client.post(url+'/transcribe',headers=h,json=command).json()['version']==2
    claim=Service.claim(db_session,v,r)
    assert claim is not None and Service.claim(db_session,v,r) is None
    assert client.post(url+'/transcribe',headers=h,json=dict(expected_version=3,request_key='speech-queue-0002')).status_code==409
    Service.finish_job(db_session,v,r,claim,error_code='engine_failed')
    assert client.get(url,headers=h).json()['state']=='failed'
    assert client.post(url+'/transcribe',headers=h,json=dict(expected_version=4,request_key='speech-queue-0002')).status_code==202

def test_bad_engine_result_is_failed_not_a_draft(client,db_session):
    h,d,v,root,r,url,pcm,cmd=received(client,db_session)
    client.post(url+'/transcribe',headers=h,json=dict(expected_version=1,request_key='speech-queue-0001'))
    claim=Service.claim(db_session,v,r)
    Service.finish_job(db_session,v,r,claim,{'text':'invalid result'})
    assert client.get(url,headers=h).json()['failure_code']=='engine_failed'
    assert client.get(url+'/text',headers=h).json()['latest_draft'] is None

def test_media_immutable_and_audit_rollback(client,db_session,monkeypatch):
    from backend.app.repositories.audit_log import AuditLogRepository
    from backend.app.schemas.recording_media import InitializeAudio
    h,d,v,root,r,url,pcm,cmd=prepared(client,db_session)
    def fail(*a,**kw):raise RuntimeError('synthetic audit error')
    with monkeypatch.context() as m:
        m.setattr(AuditLogRepository,'create',fail)
        with pytest.raises(RuntimeError,match='synthetic'):
            Service.initialize(db_session,v,r,InitializeAudio(**cmd),actor=db_session.get(User,d))
    assert db_session.scalar(select(RecordingAudioTransfer)) is None
    assert client.post(url+'/initialize',headers=h,json=cmd).status_code==201
    row=db_session.scalar(select(RecordingAudioTransfer));row.key_id='tampered'
    with pytest.raises(ValueError,match='append-only'):db_session.commit()
    db_session.rollback()

def test_regrant_does_not_reauthorize_old_recording(client,db_session):
    h,d,v,root,r,url,pcm,cmd=received(client,db_session)
    consent(client,root,state='withdrawn',version=1,key='withdraw-for-media')
    consent(client,root,state='granted',version=2,key='new-media-grant')
    assert client.get(url,headers=h).status_code==403


def test_revision_metrics_requires_review_and_current_access(client,db_session):
    h,d,v,root,r,url,claim,content=draft(client,db_session)
    assert client.get(url+'/text/revision-metrics',headers=h).status_code==409
    workspace=client.get(url+'/text',headers=h).json()
    review=dict(expected_version=4,request_key='metrics-review-0001',expected_draft_sha256=workspace['latest_draft']['sha256'],edited_text='متن ساختگی برای آزمون ۵',statement_fa='متن را با گفتگوی ویزیت تطبیق دادم و اصلاح کردم.')
    assert client.post(url+'/review',headers=h,json=review).status_code==201
    before=list(db_session.scalars(select(RecordingTextEvent)))
    result=client.get(url+'/text/revision-metrics',headers=h)
    assert result.status_code==200,result.text
    body=result.json()
    assert body['comparison_kind']=='physician_revision_distance'
    assert body['reference_verified_against_audio'] is False
    assert body['comparison']['numeric_sequence_changed'] is True
    assert body['comparison']['word_edit_distance']==1
    assert 'متن' not in result.text
    assert result.headers['cache-control']=='no-store'
    assert len(list(db_session.scalars(select(RecordingTextEvent))))==len(before)
    other=create_role_headers(client,username='metrics-other',role='physician')
    assert client.get(url+'/text/revision-metrics',headers=other).status_code==403
    consent(client,root,state='withdrawn',version=1,key='metrics-withdraw')
    assert client.get(url+'/text/revision-metrics',headers=h).status_code==403
