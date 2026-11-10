"""Production governance signatures and live-evidence trust regression tests."""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from aadharshila.production_gate import (
    REQUIREMENTS, canonical, evaluate_bundle, evaluate_configured, policy_fingerprint)
from aadharshila.engine import evaluate
from aadharshila.db import SessionLocal
from aadharshila.models import Evidence, ProviderInvocation
from aadharshila.service import collect_snapshot

POLICY={'product':'HOME_LOAN','version':77,'annual_rate_percent':8.5,
        'max_foir':.5,'max_ltv':.8,'min_income':20000,
        'max_tenure_months':360,'income_tolerance':.15,'property_tolerance':.20}


def signed_release(now=None):
    now=now or datetime.now(timezone.utc)
    anchors=[]; records=[]
    for idx,(name,role) in enumerate(REQUIREMENTS.items()):
        signer=Ed25519PrivateKey.generate()
        issuer_id=f'independent-issuer-{idx}'
        public=signer.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                                format=serialization.PublicFormat.Raw)
        anchors.append({'issuer_id':issuer_id,'role':role,
                        'public_key_base64':base64.b64encode(public).decode()})
        claim={'requirement':name,'issuer_id':issuer_id,'organization_id':'regulated-lender-0001',
               'product':'HOME_LOAN','policy_sha256':policy_fingerprint(POLICY),
               'environment':'production','scope':'automated_mortgage_underwriting',
               'valid_from':(now-timedelta(days=1)).isoformat(),
               'valid_until':(now+timedelta(days=50)).isoformat()}
        records.append({'claim':claim,
                        'signature_base64':base64.b64encode(signer.sign(canonical(claim))).decode()})
    return {'attestations':records},{'issuers':anchors}


def test_six_independent_exact_scoped_attestations_pass():
    bundle,trust=signed_release()
    report=evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                           product='HOME_LOAN',policy=POLICY)
    assert report['valid'] is True
    assert set(report['requirements'])==set(REQUIREMENTS)
    assert set(report['requirements'].values())=={'VERIFIED_SIGNATURE'}


def test_modified_or_other_organization_and_policy_fail_closed():
    bundle,trust=signed_release()
    assert not evaluate_bundle(bundle,trust,organization_id='another-lender',
                               product='HOME_LOAN',policy=POLICY)['valid']
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='LAP',policy=POLICY)['valid']
    altered={**POLICY,'annual_rate_percent':9.1}
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=altered)['valid']
    bundle['attestations'][0]['claim']['scope']='unlimited_access'
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY)['valid']


def test_missing_expired_invalid_signature_and_reused_signer_fail_closed():
    bundle,trust=signed_release(now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY,
                               at=datetime(2026,11,10,tzinfo=timezone.utc))['valid']
    bundle,trust=signed_release()
    bundle['attestations'][0]['signature_base64']='broken-string'
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY)['valid']
    bundle,trust=signed_release()
    bundle['attestations'].pop()
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY)['valid']
    bundle,trust=signed_release()
    trust['issuers'][-1]['public_key_base64']=trust['issuers'][0]['public_key_base64']
    assert not evaluate_bundle(bundle,trust,organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY)['valid']


def test_no_silent_production_authorization(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('AADHARSHILA_RELEASE_BUNDLE',raising=False)
    monkeypatch.delenv('AADHARSHILA_TRUST_STORE',raising=False)
    report=evaluate_configured(organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY)
    assert not report['valid']
    assert 'RELEASE_BUNDLE_OR_TRUST_STORE_MISSING' in report['issues']
    bundle,trust=signed_release()
    a=tmp_path/'bundle.json'; b=tmp_path/'trust.json'
    a.write_text(json.dumps(bundle));b.write_text(json.dumps(trust))
    monkeypatch.setenv('AADHARSHILA_RELEASE_BUNDLE',str(a))
    monkeypatch.setenv('AADHARSHILA_TRUST_STORE',str(b))
    assert evaluate_configured(organization_id='regulated-lender-0001',
                               product='HOME_LOAN',policy=POLICY)['valid'] is True


def production_snapshot(authenticated=True):
    evidence={k:{'verification':'VERIFIED','value':val,'expired':False,'mode':'LIVE',
                 'live_authenticated':authenticated} for k,val in {
        'identity':{},'bank_income':{'amount':120000},'income_support':{'amount':118000},
        'bureau':{},'ownership':{},'legal':{},'valuation':{'amount':3500000},'screening':{}}.items()}
    return {'application':{'product':'HOME_LOAN','amount':1500000,'tenure_months':240,
            'declared_income':120000,'existing_obligations':10000,'property_value':3500000,'revision':1},
            'evidence':evidence,'consents':['financial_underwriting'],
            'operating_mode':'PRODUCTION','production_authorization':{'valid':True}}


def test_live_label_alone_never_passes_production_evidence():
    snapshot=production_snapshot(authenticated=False)
    outcome=evaluate(snapshot,POLICY)
    assert outcome['outcome']=='REFER'
    assert any(r['code']=='NONLIVE_EVIDENCE' for r in outcome['reasons'])
    snapshot=production_snapshot(authenticated=True)
    snapshot['production_authorization']={'valid':False}
    assert evaluate(snapshot,POLICY)['outcome']=='REFER'
    # The pure calculation can evaluate an *already verified* signed-release snapshot.
    snapshot['production_authorization']={'valid':True}
    assert evaluate(snapshot,POLICY)['outcome']=='APPROVE'


def test_snapshot_links_live_evidence_to_matching_signed_provider_invocation(cases,client,login):
    case_id=cases['AS-1001']['id']
    login('analyst')
    with SessionLocal() as db:
        case=db.get(__import__('aadharshila.models',fromlist=['Application']).Application,case_id)
        e=Evidence(application_id=case_id,key='ownership',value={'owner':'demo'},
                   provider='approved-partner-test',mode='LIVE',verification='VERIFIED',
                   revision=case.revision+1)
        db.add(e);db.flush()
        snapshot=collect_snapshot(db,case)
        assert snapshot['evidence']['ownership']['live_authenticated'] is False
        p=ProviderInvocation(application_id=case_id,evidence_key='ownership',provider_name='approved-partner-test',
                             mode='LIVE',status='SUCCESS',response_metadata={'signature_validated':True,
                             'verification':'VERIFIED', 'payload_sha256':hashlib.sha256(json.dumps({'owner':'demo'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()})
        db.add(p);db.flush()
        e.provider_invocation_id=p.id
        db.flush()
        snapshot=collect_snapshot(db,case)
        assert snapshot['evidence']['ownership']['live_authenticated'] is True
        p.provider_name='other-partner'
        db.flush()
        assert collect_snapshot(db,case)['evidence']['ownership']['live_authenticated'] is False
        db.rollback()  # do not alter shared fixture test records


def test_production_sqlite_backend_refused_at_import(tmp_path):
    import os, subprocess, sys
    env={**os.environ,'APP_ENV':'production',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'forbidden.sqlite'),
         'PYTHONPATH':str(__import__('pathlib').Path(__file__).resolve().parents[1]/'src')}
    run=subprocess.run([sys.executable,'-c','import aadharshila.db'],env=env,
                       capture_output=True,text=True,timeout=15)
    assert run.returncode != 0
    assert 'Production requires externally managed PostgreSQL' in run.stderr


def test_gateway_record_has_linked_invocation_and_sandbox_is_not_live(cases,client,login,monkeypatch):
    import json, hashlib, hmac, uuid, httpx
    from aadharshila.connectors import PartnerGatewayConnector,GatewayConfig
    from aadharshila import connectors
    from sqlalchemy import select
    case_id=cases['AS-1001']['id']
    borrower=login('borrower')
    res=client.post(f'/api/v1/applications/{case_id}/consents',headers=borrower,
            json={'purpose':'financial_underwriting','granted':True})
    assert res.status_code==200
    cfg=GatewayConfig(url='https://partner.example.org/evidence',token='private-test-token-12345',
                      hmac_key='private-test-secret-'*3,provider='registered-partner-gateway',
                      mode='SANDBOX',allowed_hosts=frozenset({'partner.example.org'}))
    def respond(req):
        request_id=json.loads(req.content)['request_id']
        raw=json.dumps({'request_id':request_id,'verification':'VERIFIED',
                        'verified_at':datetime.now(timezone.utc).isoformat(),
                        'data':{'amount':115000}}).encode()
        sig=hmac.new(cfg.hmac_key.encode(),raw,hashlib.sha256).hexdigest()
        return httpx.Response(200,content=raw,headers={'X-Aadharshila-Signature':sig})
    monkeypatch.setattr(connectors,'configured_adapter',lambda key:
                        (PartnerGatewayConnector(cfg,httpx.MockTransport(respond)),None))
    analyst=login('analyst')
    res=client.post(f'/api/v1/applications/{case_id}/providers/bank_income/run',headers=analyst)
    assert res.status_code==200,res.text
    with SessionLocal() as db:
        item=db.scalar(select(Evidence).where(Evidence.application_id==case_id,
                Evidence.provider==cfg.provider).order_by(Evidence.revision.desc()))
        assert item.provider_invocation_id is not None
        invocation=db.get(ProviderInvocation,item.provider_invocation_id)
        assert invocation.response_metadata['signature_validated'] is True
        assert item.mode=='SANDBOX'
        assert collect_snapshot(db,db.get(__import__('aadharshila.models',fromlist=['Application']).Application,case_id))['evidence']['bank_income']['live_authenticated'] is False
