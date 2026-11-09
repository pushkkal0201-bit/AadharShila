"""Local security regression and recovery validation; not a penetration test."""
import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import uuid

import httpx
import pytest

from aadharshila.connectors import GatewayConfig, GatewayConfigurationError, PartnerGatewayConnector, configured_adapter
from aadharshila.engine import evaluate
from aadharshila.recovery import backup_sqlite, restore_sqlite, validate_archive
from aadharshila.db import SessionLocal
from aadharshila.models import Assessment
from sqlalchemy import select


def test_production_never_auto_approves_simulated_evidence():
    from aadharshila.seed import CASES
    with SessionLocal() as db:
        sample=db.scalar(select(Assessment).where(Assessment.outcome=='APPROVE'))
        assert sample is not None
        frozen=json.loads(json.dumps(sample.snapshot['input']))
        policy=sample.snapshot['policy']
    frozen['operating_mode']='PRODUCTION'
    result=evaluate(frozen,policy)
    assert result['outcome']=='REFER'
    assert any(r['code']=='PRODUCTION_AUTHORIZATION_REQUIRED' for r in result['reasons'])
    assert any(r['code']=='NONLIVE_EVIDENCE' for r in result['reasons'])
    frozen['evidence']={k:{**v,'mode':'LIVE'} for k,v in frozen['evidence'].items()}
    assert evaluate(frozen,policy)['outcome']=='REFER'  # no lender approval even with LIVE claims


def test_borrower_endpoints_hide_screening(cases, client, login):
    login('borrower')
    app_id=cases['AS-1006']['id']
    detail=client.get('/api/v1/applications/'+app_id)
    assert detail.status_code==200
    assert 'potential_match' not in detail.text
    assessment_id=detail.json()['latest_assessment']['id']
    for path in [f'/api/v1/assessments/{assessment_id}',
                 f'/api/v1/assessments/{assessment_id}/decision',
                 f'/api/v1/assessments/{assessment_id}/explanation',
                 f'/api/v1/applications/{app_id}/assessments']:
        response=client.get(path)
        assert response.status_code==200,response.text
        assert 'SCREENING_POTENTIAL_MATCH' not in response.text
        assert 'potential_match' not in response.text
    evidence=client.get(f'/api/v1/applications/{app_id}/evidence').json()['evidence']
    assert 'screening' not in evidence


def partner_config(url='https://partner.example.org/evidence',mode='SANDBOX',hosts=frozenset({'partner.example.org'})):
    return GatewayConfig(url=url,token='private-test-token-12345',hmac_key='private-test-secret-'*3,
                         provider='registered-partner-gateway',mode=mode,allowed_hosts=hosts)


@pytest.mark.parametrize('url', ['http://partner.example.org/evidence',
                                   'https://localhost/evidence',
                                   'https://127.0.0.1/evidence',
                                   'https://partner.example.org:8443/evidence',
                                   'https://example.net/evidence',
                                   'https://user:pass@partner.example.org/evidence'])
def test_partner_config_rejects_unsafe_targets(url):
    with pytest.raises(GatewayConfigurationError):
        partner_config(url,hosts=frozenset({'partner.example.org','127.0.0.1','localhost'})).validate()


def test_partner_gateway_verifies_signed_fresh_correlated_response():
    request_id=str(uuid.uuid4())
    secret=partner_config().hmac_key
    content={'request_id':request_id,'verification':'VERIFIED','verified_at':datetime.now(timezone.utc).isoformat(),
             'data':{'amount':87000}}
    class Sample:
        reference='AS-SAMPLE'

    def respond(request):
        assert request.headers['Authorization']=='Bearer private-test-token-12345'
        assert request.method=='POST'
        assert json.loads(request.content)['application_reference']=='AS-SAMPLE'
        response_raw=json.dumps(content).encode()
        signature=hmac.new(secret.encode(),response_raw,hashlib.sha256).hexdigest()
        return httpx.Response(200,content=response_raw,headers={'X-Aadharshila-Signature':signature})
    result=PartnerGatewayConnector(partner_config(),httpx.MockTransport(respond)).fetch(None,Sample(),'bank_income',request_id)
    assert result.status=='SUCCESS' and result.verification=='VERIFIED' and result.mode=='SANDBOX'

    def unsigned(_):return httpx.Response(200,json=content)
    denied=PartnerGatewayConnector(partner_config(),httpx.MockTransport(unsigned)).fetch(None,Sample(),'bank_income',request_id)
    assert denied.status=='UNRESOLVED' and denied.error_category=='INVALID_SIGNATURE'
    assert denied.verification=='FAILED'

    def redirect(_):return httpx.Response(301,headers={'Location':'https://untrusted.example/redirect'})
    blocked=PartnerGatewayConnector(partner_config(),httpx.MockTransport(redirect)).fetch(None,Sample(),'bank_income',request_id)
    assert blocked.error_category=='REDIRECT_REJECTED'


def test_missing_partner_configuration_in_production_is_unavailable(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    for key in ('BANK_INCOME','IDENTITY'):
        monkeypatch.delenv('AADHARSHILA_PARTNER_'+key+'_URL',raising=False)
    obj,reason=configured_adapter('bank_income')
    assert obj is None and reason=='PROVIDER_NOT_CONFIGURED'


def test_sqlite_backup_restore_with_documents_and_tamper_detection(tmp_path):
    source_db=tmp_path/'source.sqlite'
    source_docs=tmp_path/'original-docs';source_docs.mkdir()
    doc_id=str(uuid.uuid4())
    raw=b'monthly_income: 90000\n'
    original=source_docs/f'{doc_id}.txt';original.write_bytes(raw)
    with sqlite3.connect(source_db) as db:
        db.execute('CREATE TABLE applications(id TEXT PRIMARY KEY)')
        db.execute('INSERT INTO applications VALUES (?)',('case1',))
        db.execute('CREATE TABLE documents(id TEXT, path TEXT, media_type TEXT, byte_count INTEGER, sha256 TEXT)')
        db.execute('INSERT INTO documents VALUES (?,?,?,?,?)',
                   (doc_id,str(original),'text/plain',len(raw),hashlib.sha256(raw).hexdigest()))
    backup=tmp_path/'snapshot.zip'
    result=backup_sqlite(source_db,source_docs,backup)
    assert result['application_count']==1 and len(result['documents'])==1
    restored_db=tmp_path/'recovered'/'app.sqlite'
    restored_docs=tmp_path/'recovered'/'documents'
    recovered=restore_sqlite(backup,restored_db,restored_docs)
    assert recovered['integrity']=='VERIFIED_LOCALLY'
    assert (restored_docs/f'{doc_id}.txt').read_bytes()==raw
    with pytest.raises(FileExistsError):
        restore_sqlite(backup,restored_db,restored_docs)
    with sqlite3.connect(restored_db) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    # Corrupted document content cannot be archived as valid.
    original.write_bytes(b'tampered')
    with pytest.raises(ValueError):
        backup_sqlite(source_db,source_docs,tmp_path/'bad.zip')


def test_partner_gateway_application_call_records_signed_response(cases,client,login,monkeypatch):
    from aadharshila.connectors import PartnerGatewayConnector
    from aadharshila.models import Evidence, ProviderInvocation
    from aadharshila import connectors
    secret=partner_config().hmac_key
    case=cases['AS-1001']['id']
    def respond(request):
        payload=json.loads(request.content)
        body=json.dumps({'request_id':payload['request_id'],'verification':'VERIFIED',
                         'verified_at':datetime.now(timezone.utc).isoformat(),
                         'data':{'amount':125000}}).encode()
        return httpx.Response(200,content=body,headers={
            'X-Aadharshila-Signature':hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()})
    monkeypatch.setattr(connectors,'configured_adapter',lambda key:
                        (PartnerGatewayConnector(partner_config(),httpx.MockTransport(respond)),None))
    borrower_auth=login('borrower')
    consent=client.post(f'/api/v1/applications/{case}/consents',json={
        'purpose':'financial_underwriting','granted':True},headers=borrower_auth)
    assert consent.status_code==200,consent.text
    auth=login('analyst')
    response=client.post(f'/api/v1/applications/{case}/providers/bank_income/run',headers=auth)
    assert response.status_code==200,response.text
    data=response.json()
    assert data['mode']=='SANDBOX' and data['status']=='SUCCESS'
    with SessionLocal() as db:
        invocation=db.scalar(select(ProviderInvocation).where(ProviderInvocation.request_id==data['request_id']))
        assert invocation.mode=='SANDBOX' and invocation.error_category is None
        recorded=db.scalar(select(Evidence).where(Evidence.application_id==case,Evidence.provider==partner_config().provider)
            .order_by(Evidence.revision.desc()))
        assert recorded.value['amount']==125000 and recorded.mode=='SANDBOX'


def test_operational_readiness_is_not_a_fake_certification(cases,client,login):
    login('analyst')
    response=client.get('/api/v1/operations/readiness')
    assert response.status_code==200
    assert response.json()['automatic_real_underwriting']=='BLOCKED_BY_GOVERNANCE_GATE'
    assert response.json()['production_authorizations']['independent_security_review']=='NOT_ATTESTED'
    login('borrower')
    assert client.get('/api/v1/operations/readiness').status_code==403
