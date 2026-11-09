"""Regression coverage for portable operations and evidence lifecycle endpoints."""
from pathlib import Path
import uuid
from sqlalchemy import select
from aadharshila.db import SessionLocal
from aadharshila.models import Application, Document, User


def test_validated_patch_rejects_unsafe_changes(cases, client, login):
    h=login('analyst'); case=cases['AS-1002']['id']
    for fields in ({'amount':-5},{'tenure_months':0},{'property_value':None},
                   {'extra_internal_field':'bypass'},{'amount':1e18},{}):
        r=client.patch(f'/api/v1/applications/{case}',json=fields,headers=h)
        assert r.status_code==422,(fields,r.text)
    previous=client.get(f'/api/v1/applications/{case}').json()['application']['revision']
    valid=client.patch(f'/api/v1/applications/{case}',json={'employment':'Updated employer'},headers=h)
    assert valid.status_code==200,valid.text
    assert valid.json()['revision']==previous+1


def test_history_delta_and_ranked_evidence_requests(cases,client,login):
    h=login('analyst');case=cases['AS-1004']['id']
    # Earlier integration tests can resolve this synthetic case; recreate the conflict explicitly.
    conflict=client.post(f'/api/v1/applications/{case}/evidence',json={'key':'income_support','value':{'amount':20000},'verification':'VERIFIED','mode':'SIMULATED','provider':'local-review-fixture'},headers=h)
    assert conflict.status_code==200,conflict.text
    early=client.get(f'/api/v1/applications/{case}').json()['latest_assessment']
    assert early['outcome']=='REFER'
    recs=client.get(f'/api/v1/applications/{case}/next-evidence')
    assert recs.status_code==200,recs.text
    assert any(item['reason_code']=='INCOME_CONTRADICTION' for item in recs.json()['items'])
    changed=client.post(f'/api/v1/applications/{case}/evidence',json={'key':'income_support','value':{'amount':99000},'verification':'VERIFIED','mode':'SIMULATED','provider':'local-review-fixture'},headers=h)
    assert changed.status_code==200,changed.text
    delta=client.get(f'/api/v1/applications/{case}/assessment-diff')
    assert delta.status_code==200,delta.text
    data=delta.json()
    assert data['older']['assessment_id']==early['id']
    assert data['newer']['revision']>data['older']['revision']
    assert any(c['reason_code']=='INCOME_CONTRADICTION' for c in data['reason_changes'])
    before=client.post(f"/api/v1/assessments/{early['id']}/replay",headers=h)
    assert before.json()['reproduced'] is True
    bad=client.get(f'/api/v1/applications/{case}/assessment-diff?older_id={uuid.uuid4()}')
    assert bad.status_code==404


def test_borrower_cannot_see_internal_diff(cases,client,login):
    h=login('analyst');case=cases['AS-1002']['id']
    client.post(f'/api/v1/applications/{case}/queue-reassessment',headers=h)
    # Another assessment version is required before a delta can be computed.
    from aadharshila.worker import work_one
    with SessionLocal() as db:work_one(db)
    login('borrower')
    res=client.get(f'/api/v1/applications/{case}/assessment-diff')
    assert res.status_code==200,res.text
    assert 'reason_changes' not in res.json()
    assert 'financial_changes' not in res.json()


def test_document_download_scoped_and_hash_checked(cases,client,login):
    h=login('analyst');case=cases['AS-1001']['id'];content=b'monthly_income: 110000\n'
    r=client.post(f'/api/v1/applications/{case}/documents',files={'file':('finance.txt',content,'text/plain')},headers=h)
    assert r.status_code==200,r.text
    document_id=r.json()['id']
    url=f'/api/v1/applications/{case}/documents/{document_id}/download'
    got=client.get(url)
    assert got.status_code==200 and got.content==content
    assert got.headers['cache-control']=='no-store'
    wrong=client.get(f"/api/v1/applications/{cases['AS-1002']['id']}/documents/{document_id}/download")
    assert wrong.status_code==404
    with SessionLocal() as db:
        document=db.get(Document,document_id)
        Path(document.path).write_bytes(b'changed externally')
    assert client.get(url).status_code==409
    # A different borrower cannot access a document owned by the demo borrower.
    from aadharshila.security import hash_password
    with SessionLocal() as db:
        staff=db.scalar(select(User).where(User.username=='analyst'))
        db.add(User(org_id=staff.org_id,username='borrower_'+uuid.uuid4().hex[:8],password_hash=hash_password('Demo@12345'),role='BORROWER',active=True))
        db.flush()
        other=db.scalars(select(User).where(User.role=='BORROWER',User.username!='borrower')).all()[-1]
        other_name=other.username
        db.commit()
    login(other_name)
    assert client.get(url).status_code==404


def test_development_scripts_present_and_portable():
    root=Path(__file__).resolve().parents[1]
    for name in ('setup','run','test','worker'):
        assert (root/f'{name}.bat').exists()
        script=(root/'scripts'/'windows'/f'{name}.ps1').read_text()
        assert "Join-Path $PSScriptRoot '../..'" in script
        assert "D:\\Projects\\Aadharshila" not in script
    assert (root/'.github/workflows/quality.yml').exists()


def test_borrower_report_and_audit_redact_screening_details(cases,client,login):
    login('borrower');case=cases['AS-1006']['id']
    assessment=client.get(f'/api/v1/applications/{case}').json()['latest_assessment']['id']
    result=client.get(f'/api/v1/assessments/{assessment}/evidence-pack').json()
    assert 'SCREENING_POTENTIAL_MATCH' not in str(result)
    assert 'evidence' not in result['snapshot']
    report=client.get(f'/api/v1/assessments/{assessment}/evidence-pack?format=html')
    assert 'SCREENING_POTENTIAL_MATCH' not in report.text
    history=client.get(f'/api/v1/applications/{case}/audit').json()
    assert all('detail' not in item for item in history['items'])
