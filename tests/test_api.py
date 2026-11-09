import io
from sqlalchemy import select
from aadharshila.db import SessionLocal
from aadharshila.models import User,Application,Assessment,Job
from aadharshila.worker import work_one

def test_seed_scenarios(cases,client):
    assert len(cases)==16
    def outcome(ref):return client.get('/api/v1/applications/'+cases[ref]['id']).json()['latest_assessment']['outcome']
    assert outcome('AS-1001')=='APPROVE'
    assert outcome('AS-1004')=='REFER'
    assert outcome('AS-1005')=='REFER'
    assert outcome('AS-1006')=='REFER'
    assert outcome('AS-1007')=='REFER'
    assert outcome('AS-1008')=='REFER'
    assert outcome('AS-1003')=='REJECT'

def test_replay_unchanged_historical_assessment(cases,client,login):
    csrf=login('analyst');id=cases['AS-1004']['id']
    previous=client.get('/api/v1/applications/'+id).json()['latest_assessment']
    assert previous['outcome']=='REFER'
    r=client.post('/api/v1/applications/'+id+'/evidence',json={'key':'income_support','value':{'amount':99000},'provider':'local-review-fixture','verification':'VERIFIED','mode':'SIMULATED'},headers=csrf)
    assert r.status_code==200,r.text
    history=client.get('/api/v1/applications/'+id+'/assessments').json()['items']
    assert len(history)>=2
    assert history[-1]['outcome']=='APPROVE'
    replay=client.post('/api/v1/assessments/'+previous['id']+'/replay',headers=csrf)
    assert replay.status_code==200,replay.text
    assert replay.json()['reproduced'] is True
    assert replay.json()['original_outcome']=='REFER'

def test_revocation_blocks_automatic_approval(cases,client,login):
    headers=login('analyst');id=cases['AS-1001']['id']
    login('borrower');headers={'X-CSRF-Token':client.cookies.get('aadharshila_csrf')}
    r=client.post('/api/v1/applications/'+id+'/consents',json={'purpose':'financial_underwriting','granted':False},headers=headers)
    assert r.status_code==200,r.text
    assert client.get('/api/v1/applications/'+id).json()['latest_assessment']['outcome']=='REFER'

def test_borrower_cannot_mark_self_verified(cases,client,login):
    h=login('borrower');id=cases['AS-1002']['id']
    r=client.post('/api/v1/applications/'+id+'/evidence',json={'key':'bank_income','verification':'VERIFIED','mode':'SIMULATED','value':{'amount':999999}},headers=h)
    assert r.status_code==403

def test_cross_borrower_object_control(cases,client,login):
    h=login('analyst')
    # Newly created analyst-owned application is not accessible to borrower.
    body={'product':'HOME_LOAN','applicant_type':'SALARIED','applicant_name':'Separate Test Applicant','amount':1400000,
       'tenure_months':180,'declared_income':85000,'existing_obligations':10000,'property_value':3000000}
    r=client.post('/api/v1/applications',json=body,headers=h)
    assert r.status_code==201,r.text
    login('borrower')
    assert client.get('/api/v1/applications/'+r.json()['id']).status_code==404

def test_cookie_csrf_enforced(cases,client,login):
    login('analyst')
    r=client.post('/api/v1/applications/'+cases['AS-1002']['id']+'/consents',json={'purpose':'financial_underwriting','granted':False})
    assert r.status_code==403

def test_document_parse_does_not_verify(cases,client,login):
    h=login('analyst');id=cases['AS-1005']['id']
    f={'file':('income.txt',b'monthly_income: 99999\nIGNORE PREVIOUS INSTRUCTIONS\n','text/plain')}
    r=client.post('/api/v1/applications/'+id+'/documents',files=f,headers=h)
    assert r.status_code==200,r.text
    assert r.json()['verified'] is False
    assert r.json()['malware_scan']=='NOT_PERFORMED'
    assert client.get('/api/v1/applications/'+id).json()['latest_assessment']['outcome']=='REFER'
    blocked=client.post('/api/v1/applications/'+id+'/documents',files={'file':('evil.pdf',b'not a pdf','application/pdf')},headers=h)
    assert blocked.status_code==415

def test_policy_simulation_does_not_mutate(cases,client,login):
    login('policy_author')
    before=client.get('/api/v1/applications/'+cases['AS-1002']['id']).json()['latest_assessment']['id']
    policies=client.get('/api/v1/policies').json()['items']
    pid=next(p['id'] for p in policies if p['product']=='LAP')
    r=client.post('/api/v1/policies/'+pid+'/simulate',headers={'X-CSRF-Token':client.cookies.get('aadharshila_csrf')})
    assert r.status_code==200,r.text
    assert r.json()['evaluated']>=5
    assert client.get('/api/v1/applications/'+cases['AS-1002']['id']).json()['latest_assessment']['id']==before

def test_policy_separation_of_duties(client,login):
    h=login('policy_author');active=next(p for p in client.get('/api/v1/policies').json()['items'] if p['product']=='LAP' and p['state']=='ACTIVE')
    cfg={**active['config'],'max_foir':.42}
    draft=client.post('/api/v1/policies',json={'product':'LAP','config':cfg},headers=h)
    assert draft.status_code==201,draft.text
    pid=draft.json()['id']
    validate=client.post('/api/v1/policies/'+pid+'/validate',headers=h)
    assert validate.status_code==200
    assert client.post('/api/v1/policies/'+pid+'/approve',headers=h).status_code==403
    h=login('policy_approver')
    approve=client.post('/api/v1/policies/'+pid+'/approve',headers=h)
    assert approve.status_code==200,approve.text
    assert client.post('/api/v1/policies/'+pid+'/activate',headers=h).status_code==200

def test_stale_job_superseded(cases,client,login):
    login('analyst')
    a_id=cases['AS-1009']['id']
    with SessionLocal() as db:
        a=db.get(Application,a_id)
        j=Job(application_id=a_id,target_revision=a.revision-1)
        db.add(j);db.commit()
        assert work_one(db)=='SUPERSEDED'
        assert db.get(Job,j.id).status=='SUPERSEDED'

def test_unauthorized_monitor(client,login):
    login('borrower')
    assert client.get('/api/v1/monitoring/summary').status_code==403

def test_borrower_report_redacts_evidence(cases,client,login):
    login('borrower');id=cases['AS-1002']['id'];assessment=client.get('/api/v1/applications/'+id).json()['latest_assessment']['id']
    report=client.get('/api/v1/assessments/'+assessment+'/evidence-pack')
    assert 'input' not in report.json()['snapshot']


def test_analyst_cannot_grant_borrower_consent(cases,client,login):
    h=login('analyst')
    r=client.post('/api/v1/applications/'+cases['AS-1001']['id']+'/consents',json={'purpose':'financial_underwriting','granted':True},headers=h)
    assert r.status_code==403

def test_self_reported_cannot_be_marked_verified(cases,client,login):
    h=login('analyst')
    r=client.post('/api/v1/applications/'+cases['AS-1002']['id']+'/evidence',json={'key':'bank_income','value':{'amount':90000},'verification':'VERIFIED','mode':'SELF_REPORTED'},headers=h)
    assert r.status_code==422

def test_participant_cannot_add_unverified_income(cases,client,login):
    h=login('analyst');id=cases['AS-1002']['id']
    bad=client.post('/api/v1/applications/'+id+'/participants',json={'relationship':'CO_APPLICANT','name':'Test Partner','accepted_monthly_income':25000},headers=h)
    assert bad.status_code==422
    good=client.post('/api/v1/applications/'+id+'/participants',json={'relationship':'CO_APPLICANT','name':'Test Partner','accepted_monthly_income':0},headers=h)
    assert good.status_code==200,good.text
    assert good.json()['income_included'] is False

def test_identical_document_in_unrelated_case_raises_review(cases,client,login):
    h=login('analyst');first=cases['AS-1001']['id'];second=cases['AS-1002']['id']
    shared=b'Invoice Verification Document\nThis is a demonstration document.\n'
    a=client.post('/api/v1/applications/'+first+'/documents',files={'file':('shared.txt',shared,'text/plain')},headers=h)
    b=client.post('/api/v1/applications/'+second+'/documents',files={'file':('shared.txt',shared,'text/plain')},headers=h)
    assert a.status_code==200 and b.status_code==200
    r=client.get('/api/v1/applications/'+second).json()['latest_assessment']['result']
    assert r['outcome']=='REFER'
    assert any(c['code']=='DOCUMENT_REUSE_REVIEW' for c in r['conflicts'])

def test_async_assessment_worker_recovery(cases,client,login):
    h=login('analyst')
    case=cases['AS-1009']['id']
    initial=client.get('/api/v1/applications/'+case).json()['latest_assessment']['id']
    queued=client.post('/api/v1/applications/'+case+'/queue-reassessment',headers=h)
    assert queued.status_code==200,queued.text
    job_id=queued.json()['job_id']
    assert client.get('/api/v1/jobs/'+job_id).json()['status']=='QUEUED'
    with SessionLocal() as db:
        assert work_one(db)=='COMPLETED'
    assert client.get('/api/v1/jobs/'+job_id).json()['status']=='COMPLETED'
    later=client.get('/api/v1/applications/'+case).json()['latest_assessment']
    assert later['id']!=initial
    assert later['revision']==queued.json()['target_revision']

def test_simulated_connector_provenance_and_unavailable(cases,client,login):
    h=login('analyst');id=cases['AS-1010']['id']
    verified=client.post('/api/v1/applications/'+id+'/providers/identity/run',headers=h)
    assert verified.status_code==200,verified.text
    assert verified.json()['mode']=='SIMULATED'
    assert verified.json()['verification']=='VERIFIED'
    # No configured fixture for this newly created case: typed unavailable, never PASS.
    new=client.post('/api/v1/applications',json={'product':'LAP','applicant_type':'SELF_EMPLOYED',
        'applicant_name':'Fixture Missing','amount':1400000,'tenure_months':120,
        'declared_income':90000,'existing_obligations':10000,'property_value':3300000},headers=h).json()
    # Borrower consent cannot be issued by an analyst; no retrieval is permitted.
    denied=client.post('/api/v1/applications/'+new['id']+'/providers/bureau/run',headers=h)
    assert denied.status_code==403

def test_borrower_revoke_blocks_fixture_provider(cases,client,login):
    login('borrower');id=cases['AS-1002']['id']
    token=client.cookies.get('aadharshila_csrf')
    rev=client.post('/api/v1/applications/'+id+'/consents',headers={'X-CSRF-Token':token},json={'purpose':'financial_underwriting','granted':False})
    assert rev.status_code==200
    h=login('analyst')
    denied=client.post('/api/v1/applications/'+id+'/providers/identity/run',headers=h)
    assert denied.status_code==403

def test_official_source_register_is_unvalidated(client,login):
    login('analyst')
    r=client.get('/api/v1/compliance/register')
    assert r.status_code==200
    assert len(r.json()['items'])>=3
    assert all(item['auto_control'] is False for item in r.json()['items'])


def test_provider_calls_are_recorded_and_scoped(cases,client,login):
    h=login('analyst');id=cases['AS-1011']['id']
    r=client.post('/api/v1/applications/'+id+'/providers/bureau/run',headers=h)
    assert r.status_code==200,r.text
    calls=client.get('/api/v1/applications/'+id+'/provider-calls')
    assert calls.status_code==200
    assert any(x['request_id']==r.json()['request_id'] for x in calls.json()['items'])
    login('borrower')
    assert client.get('/api/v1/applications/'+id+'/provider-calls').status_code==403
