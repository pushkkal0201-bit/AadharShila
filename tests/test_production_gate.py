"""Signed-release and authenticated-evidence checks."""
import os, sys, base64, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from aadharshila.production_gate import REQUIREMENTS,canonical,policy_fingerprint,evaluate_bundle,evaluate_configured
from aadharshila.engine import evaluate

POLICY={'product':'HOME_LOAN','version':1,'annual_rate_percent':8.5,'max_foir':.5,'max_ltv':.8,
        'min_income':20000,'max_tenure_months':360,'income_tolerance':.15,'property_tolerance':.20}

def release():
    now=datetime.now(timezone.utc);trust=[];records=[]
    for idx,(name,role) in enumerate(REQUIREMENTS.items()):
        signer=Ed25519PrivateKey.generate();issuer=f'approved-issuer-{idx}'
        raw=signer.public_key().public_bytes(encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)
        trust.append({'issuer_id':issuer,'role':role,'public_key_base64':base64.b64encode(raw).decode()})
        claim={'requirement':name,'issuer_id':issuer,'organization_id':'lender-001','product':'HOME_LOAN',
               'policy_sha256':policy_fingerprint(POLICY),'environment':'production',
               'scope':'automated_mortgage_underwriting',
               'valid_from':(now-timedelta(days=1)).isoformat(),
               'valid_until':(now+timedelta(days=50)).isoformat()}
        records.append({'claim':claim,'signature_base64':base64.b64encode(signer.sign(canonical(claim))).decode()})
    return {'attestations':records},{'issuers':trust}

def verify(bundle,trust,org='lender-001',policy=POLICY):
    return evaluate_bundle(bundle,trust,organization_id=org,product='HOME_LOAN',policy=policy)

def test_independent_signatures_have_strict_scope():
    b,t=release()
    assert verify(b,t)['valid'] is True
    assert not verify(b,t,org='another-lender')['valid']
    assert not verify(b,t,policy={**POLICY,'max_foir':.4})['valid']

def test_forgery_missing_signer_and_key_reuse_are_rejected():
    b,t=release();b['attestations'][0]['claim']['scope']='forged'
    assert not verify(b,t)['valid']
    b,t=release();b['attestations'].pop()
    assert not verify(b,t)['valid']
    b,t=release();t['issuers'][-1]['public_key_base64']=t['issuers'][0]['public_key_base64']
    assert not verify(b,t)['valid']

def test_missing_real_approvals_fail_closed(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('AADHARSHILA_RELEASE_BUNDLE',raising=False)
    monkeypatch.delenv('AADHARSHILA_TRUST_STORE',raising=False)
    assert not evaluate_configured(organization_id='lender-001',product='HOME_LOAN',policy=POLICY)['valid']

def test_live_label_cannot_bypass_provider_provenance_or_governance():
    ev={k:{'verification':'VERIFIED','mode':'LIVE','value':v,'expired':False,'live_authenticated':False}
        for k,v in {'identity':{},'bank_income':{'amount':100000},'income_support':{'amount':99000},
                     'bureau':{},'ownership':{},'legal':{},'valuation':{'amount':3500000},'screening':{}}.items()}
    snapshot={'application':{'product':'HOME_LOAN','amount':1500000,'tenure_months':240,'declared_income':100000,
                'existing_obligations':10000,'property_value':3500000,'revision':1},
              'evidence':ev,'consents':['financial_underwriting'],'operating_mode':'PRODUCTION',
              'production_authorization':{'valid':True}}
    assert evaluate(snapshot,POLICY)['outcome']=='REFER'
    for value in ev.values():value['live_authenticated']=True
    snapshot['production_authorization']={'valid':False}
    assert evaluate(snapshot,POLICY)['outcome']=='REFER'
    snapshot['production_authorization']={'valid':True}
    assert evaluate(snapshot,POLICY)['outcome']=='APPROVE'

def test_sqlite_refused_in_production_mode(tmp_path):
    env={**os.environ,'APP_ENV':'production',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'unsafe.sqlite'),
         'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    response=subprocess.run([sys.executable,'-c','import aadharshila.db'],
                             capture_output=True,text=True,env=env,timeout=15)
    assert response.returncode!=0
    assert 'Production requires externally managed PostgreSQL' in response.stderr
