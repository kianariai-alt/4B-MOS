"""Synthetic visit-scoped recording consent and retry integration tests."""
from datetime import datetime, timezone
import uuid
import pytest
from sqlalchemy import select, text
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.models.recording import VisitRecordingEvent
from backend.tests.test_treatment_options_roadmap import create_role_headers, create_patient, create_visit

pytestmark=pytest.mark.usefixtures('authenticated_admin')

def setup(client,db):
    headers=create_role_headers(client,username='recording_physician',role='physician')
    doctor=db.scalar(select(User).where(User.username=='recording_physician'))
    patient=create_patient(client,code='REC-SYNTHETIC')
    visit=create_visit(client,patient['id'],complaint='Synthetic complaint')
    root=f"/api/v1/visits/{visit['id']}"
    response=client.post(root+'/reception/intakes',json=dict(patient_reported_complaint='Synthetic',assigned_physician_id=doctor.id,expected_version=0,request_key='assign-0001'))
    assert response.status_code==201,response.text
    return headers,doctor.id,visit['id'],root

def consent(client,root,state='granted',version=0,key='consent-0001'):
    response=client.post(root+'/reception/consents',json=dict(purpose='audio_recording',state=state,document_version='FA-1',evidence_reference='SYNTHETIC-RECORDING',confirmed_at=datetime.now(timezone.utc).isoformat(),expected_version=version,request_key=key))
    assert response.status_code==201,response.text
    return response.json()

def start_command(sha,**changes):
    return dict(recording_id=str(uuid.uuid4()),expected_version=0,request_key='record-start-0001',expected_consent_sha256=sha,**changes)

def finish_command(start,**changes):
    return dict(recording_id=start['recording_id'],expected_version=1,request_key='record-finish-0001',reason='finished',pcm_bytes=32000,encrypted_file_sha256='a'*64,**changes)

def test_unknown_consent_blocks_start_and_educational_is_independent(client,db_session):
    h,p,v,root=setup(client,db_session)
    access=client.get(root+'/recordings/access',headers=h).json()
    assert access['can_record'] is False and access['block_reason']=='consent_required'
    assert access['audio_upload_enabled'] is access['transcription_enabled'] is access['training_enabled'] is False
    assert client.post(root+'/recordings/start',headers=h,json=start_command('0'*64)).status_code==409
    c=consent(client,root)
    access=client.get(root+'/recordings/access',headers=h).json()
    assert access['can_record'] is True and access['consent_sha256']==c['sha256']
    workspace=client.get(root+'/reception').json()
    assert next(c for c in workspace['consents'] if c['purpose']=='educational_use')['state']=='unknown'

def test_owner_role_guards_and_no_context_leak(client,db_session):
    h,p,v,root=setup(client,db_session)
    for role in ('operator','nurse','admin','viewer'):
        other=create_role_headers(client,username='record_'+role,role=role)
        assert client.get(root+'/recordings/access',headers=other).status_code==403
    other=create_role_headers(client,username='record_other',role='physician')
    assert client.get(root+'/recordings/access',headers=other).status_code==403
    c=consent(client,root)
    assert client.post(root+'/recordings/start',headers=other,json=start_command(c['sha256'])).status_code==403

def test_start_finish_retry_version_and_overlap(client,db_session):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    command=start_command(c['sha256'])
    first=client.post(root+'/recordings/start',headers=h,json=command)
    assert first.status_code==201,first.text
    start=first.json()
    assert client.post(root+'/recordings/start',headers=h,json=command).json()['id']==start['id']
    assert client.post(root+'/recordings/start',headers=h,json={**command,'recording_id':str(uuid.uuid4())}).status_code==409
    assert client.post(root+'/recordings/start',headers=h,json={**command,'expected_version':1,'request_key':'start-another'}).status_code==409
    assert client.get(root+f"/recordings/{start['recording_id']}/check",headers=h).json()['can_continue'] is True
    finish=finish_command(start)
    end=client.post(root+'/recordings/finish',headers=h,json=finish)
    assert end.status_code==201,end.text
    assert client.post(root+'/recordings/finish',headers=h,json=finish).json()['id']==end.json()['id']
    assert client.get(root+f"/recordings/{start['recording_id']}/check",headers=h).json()['reason']=='session_changed'
    assert client.get(root+'/recordings/access',headers=h).json()['can_record'] is True
    assert client.post(root+'/recordings/start',headers=h,json={**command,'expected_version':2,'request_key':'start-reuse-id'}).status_code==409

def test_withdrawal_stops_continuation_but_finish_is_allowed(client,db_session):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    command=start_command(c['sha256'])
    start=client.post(root+'/recordings/start',headers=h,json=command).json()
    consent(client,root,state='withdrawn',version=1,key='consent-withdrawn')
    # Exact retries are receipts, never renewed permission to activate a mic.
    assert client.post(root+'/recordings/start',headers=h,json=command).json()['id']==start['id']
    check=client.get(root+f"/recordings/{start['recording_id']}/check",headers=h).json()
    assert check['can_continue'] is False and check['reason']=='consent_changed'
    assert client.post(root+'/recordings/finish',headers=h,json={**finish_command(start),'reason':'consent_changed'}).status_code==201
    assert client.post(root+'/recordings/start',headers=h,json={**command,'expected_version':2,'request_key':'start-after-withdrawal','recording_id':str(uuid.uuid4())}).status_code==409

def test_stale_consent_hash_cannot_start(client,db_session):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    consent(client,root,version=1,key='consent-new-version')
    assert client.post(root+'/recordings/start',headers=h,json=start_command(c['sha256'])).status_code==409

def test_closed_or_reassigned_visit_can_be_finished_by_original_doctor(client,db_session):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    start=client.post(root+'/recordings/start',headers=h,json=start_command(c['sha256'])).json()
    other=create_role_headers(client,username='new_recording_doctor',role='physician')
    new_id=db_session.scalar(select(User).where(User.username=='new_recording_doctor')).id
    assert client.post(root+'/reception/intakes',json=dict(patient_reported_complaint='Synthetic',assigned_physician_id=new_id,expected_version=1,request_key='assign-0002')).status_code==201
    assert client.get(root+'/recordings/access',headers=h).status_code==403
    assert client.get(root+'/recordings/access',headers=other).json()['active_recording'] is None
    assert client.get(root+f"/recordings/{start['recording_id']}/check",headers=h).json()['reason']=='session_changed'
    assert client.post(root+'/recordings/finish',headers=other,json=finish_command(start)).status_code==403
    db_session.execute(text("UPDATE visits SET status='closed' WHERE id=:id"),{'id':v});db_session.commit()
    assert client.post(root+'/recordings/finish',headers=h,json=finish_command(start)).status_code==201

@pytest.mark.parametrize('changes',[{'pcm_bytes':-2},{'pcm_bytes':True},{'pcm_bytes':460800002},{'reason':'train_model'},{'audio':'secret'}])
def test_invalid_finish_schema(client,db_session,changes):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    start=client.post(root+'/recordings/start',headers=h,json=start_command(c['sha256'])).json()
    assert client.post(root+'/recordings/finish',headers=h,json={**finish_command(start),**changes}).status_code==422

def test_odd_bytes_or_missing_hash_rejected(client,db_session):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    start=client.post(root+'/recordings/start',headers=h,json=start_command(c['sha256'])).json()
    assert client.post(root+'/recordings/finish',headers=h,json={**finish_command(start),'pcm_bytes':3}).status_code==409
    assert client.post(root+'/recordings/finish',headers=h,json={**finish_command(start),'encrypted_file_sha256':None}).status_code==409

def test_capture_evidence_immutable_and_corruption_detected(client,db_session):
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    start=client.post(root+'/recordings/start',headers=h,json=start_command(c['sha256'])).json()
    row=db_session.get(VisitRecordingEvent,start['id']);row.action='finish'
    with pytest.raises(ValueError,match='append-only'):db_session.commit()
    db_session.rollback()
    db_session.execute(text('UPDATE visit_recording_events SET sha256=:sha WHERE id=:id'),dict(sha='0'*64,id=start['id']));db_session.commit()
    assert client.get(root+'/recordings/access',headers=h).status_code==409

def test_audit_failure_rolls_back_start(client,db_session,monkeypatch):
    from backend.app.services.recording import RecordingService
    from backend.app.schemas.recording import RecordingStart
    from backend.app.repositories.audit_log import AuditLogRepository
    h,p,v,root=setup(client,db_session);c=consent(client,root)
    def fail(*args,**kwargs):raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(AuditLogRepository,'create',fail)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):
        RecordingService.start(db_session,v,RecordingStart(**start_command(c['sha256'])),actor=db_session.get(User,p))
    assert db_session.scalar(select(VisitRecordingEvent)) is None
