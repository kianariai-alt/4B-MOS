"""Synthetic coverage of bank ownership, lifecycle and screening boundary."""
import pytest
from sqlalchemy import select, text
from backend.app.models.user import User
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.tests.test_treatment_options_roadmap import create_role_headers, create_patient, create_visit

pytestmark = pytest.mark.usefixtures('authenticated_admin')

def setup(client, db):
    headers = create_role_headers(client, username='bank_physician', role='physician')
    physician = db.scalar(select(User).where(User.username=='bank_physician'))
    return headers, physician.id, f'/api/v1/physicians/{physician.id}/question-bank'

def draft(**changes):
    return dict(title_fa='گنجینه اولیه', scope_fa='مصاحبه عمومی', questions=[dict(id='first',text_fa='شکایت اصلی چیست؟',purpose_fa='ثبت شرح حال')],expected_version=0,request_key='draft-0001',**changes)

def review(event, version, key):
    return dict(expected_version=version, expected_bank_sha256=event['sha256'], request_key=key, statement_fa='پرسش‌های این نسخه را بررسی و تأیید کرده‌ام.')

def test_lifecycle_retry_and_conflicts(client,db_session):
    h,p,root=setup(client,db_session)
    assert client.get(root,headers=h).json()['active_bank'] is None
    data=draft()
    r=client.post(root+'/drafts',headers=h,json=data)
    assert r.status_code==201,r.text
    first=r.json()
    assert client.post(root+'/drafts',headers=h,json=data).json()['id']==first['id']
    assert client.post(root+'/drafts',headers=h,json={**data,'title_fa':'تغییر محتوا'}).status_code==409
    bad=review(first,1,'approve-0001');bad['expected_bank_sha256']='0'*64
    assert client.post(root+'/approve',headers=h,json=bad).status_code==409
    approved=client.post(root+'/approve',headers=h,json=review(first,1,'approve-0001')).json()
    assert approved['action']=='approve'
    new={**data,'expected_version':2,'request_key':'draft-0002'}
    second=client.post(root+'/drafts',headers=h,json=new).json()
    ws=client.get(root,headers=h).json()
    assert ws['active_bank']['id']==approved['id'] and ws['latest']['id']==second['id']
    assert ws['is_trained_model'] is ws['authorizes_diagnosis'] is False
    retired=client.post(root+'/retire',headers=h,json=review(approved,3,'retire-0001'))
    assert retired.status_code==201,retired.text
    assert client.get(root,headers=h).json()['has_approved_bank'] is False
    assert client.post(root+'/approve',headers=h,json=review(second,4,'approve-0002')).status_code==409

def test_owner_only_and_private_draft(client,db_session):
    h,p,root=setup(client,db_session)
    other=create_role_headers(client,username='other_physician',role='physician')
    assert client.get(root,headers=other).status_code==403
    assert client.post(root+'/drafts',headers=other,json=draft()).status_code==403
    assert client.post(root+'/drafts',json=draft()).status_code==403
    operator=create_role_headers(client,username='bank_operator',role='operator')
    assert client.get(root,headers=operator).status_code==403

@pytest.mark.parametrize('questions',[
    [dict(id='a',text_fa='سؤال اول',purpose_fa='شرح حال',depends_on_id='later',show_when_answer_in=['yes'])],
    [dict(id='a',text_fa='سؤال اول',purpose_fa='شرح حال',answer_type='single_choice',choices=['تنها'])],
    [dict(id='a',text_fa='سؤال اول',purpose_fa='شرح حال',allow_decline=False)],
    [dict(id='a',text_fa='سؤال اول',purpose_fa='شرح حال')]*2,
])
def test_invalid_questions(client,db_session,questions):
    h,p,root=setup(client,db_session)
    assert client.post(root+'/drafts',headers=h,json={**draft(),'questions':questions}).status_code==422

def test_assigned_visit_only_sees_approved_bank(client,db_session):
    h,p,root=setup(client,db_session)
    patient=create_patient(client,code='BANK-SYNTHETIC')
    visit=create_visit(client,patient['id'],complaint='Synthetic')
    vr=f"/api/v1/visits/{visit['id']}"
    op=create_role_headers(client,username='screen_operator',role='operator')
    assert client.get(vr+'/screening-question-bank',headers=op).json()['questions']==[]
    r=client.post(vr+'/reception/intakes',headers=op,json=dict(patient_reported_complaint='Synthetic',assigned_physician_id=p,expected_version=0,request_key='intake-0001'))
    assert r.status_code==201,r.text
    d=client.post(root+'/drafts',headers=h,json=draft()).json()
    assert client.get(vr+'/screening-question-bank',headers=op).json()['questions']==[]
    a=client.post(root+'/approve',headers=h,json=review(d,1,'approve-0001')).json()
    result=client.get(vr+'/screening-question-bank',headers=op).json()
    assert result['bank_id']==a['id'] and len(result['questions'])==1
    assert 'command' not in result and result['authorizes_diagnosis'] is False
    viewer=create_role_headers(client,username='bank_viewer',role='viewer')
    assert client.get(vr+'/screening-question-bank',headers=viewer).status_code==403

def test_immutable_and_tampered_history(client,db_session):
    h,p,root=setup(client,db_session)
    d=client.post(root+'/drafts',headers=h,json=draft()).json()
    row=db_session.get(PhysicianQuestionEvent,d['id'])
    row.action='retire'
    with pytest.raises(ValueError,match='append-only'): db_session.commit()
    db_session.rollback()
    db_session.execute(text("UPDATE physician_question_events SET sha256=:sha WHERE id=:id"),dict(sha='0'*64,id=d['id']))
    db_session.commit()
    assert client.get(root,headers=h).status_code==409

def test_audit_failure_rolls_back_question_write(client,db_session,monkeypatch):
    from backend.app.repositories.audit_log import AuditLogRepository
    from backend.app.services.physician_questions import PhysicianQuestionService
    from backend.app.schemas.physician_questions import DraftCreate
    h,p,root=setup(client,db_session)
    actor=db_session.get(User,p)
    def fail(*args,**kwargs): raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(AuditLogRepository,'create',fail)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):
        PhysicianQuestionService.save_draft(db_session,p,DraftCreate(**draft()),actor=actor)
    assert db_session.scalar(select(PhysicianQuestionEvent)) is None

def test_valid_conditional_order(client,db_session):
    h,p,root=setup(client,db_session)
    questions=[dict(id='a',text_fa='سؤال اول',purpose_fa='شرح حال',answer_type='yes_no'),dict(id='b',text_fa='سؤال دوم',purpose_fa='تکمیل اطلاعات',depends_on_id='a',show_when_answer_in=['yes'])]
    assert client.post(root+'/drafts',headers=h,json={**draft(),'questions':questions}).status_code==201
    questions[1]['show_when_answer_in']=['invalid']
    assert client.post(root+'/drafts',headers=h,json={**draft(),'questions':questions}).status_code==422
