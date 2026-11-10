"""New document, income, identity and non-binding-loan workflow regression tests."""
from __future__ import annotations
import base64, io, json, os, socket, threading
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import jwt, pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from aadharshila.income import TransactionBatch, reconcile
from aadharshila.documents_pipeline import clamav_scan, extract_pdf, DocumentSafetyError
from aadharshila.federated_auth import validate_federated_token, FederatedAuthenticationError
from aadharshila.engine import evaluate


def txn(month,amount,category='SALARY', direction='CREDIT',reference='',counterparty_id='employer-A'):
    return {'transaction_id':f'{month}-{amount}-{category}-{direction}-{reference}', 'account_id':'bank-A',
            'posting_date':f'2026-{month:02d}-10','amount':amount,'direction':direction,
            'category':category,'reference':reference,'counterparty_id':counterparty_id,'verified':True}

def normal_batch():
    tx=[txn(m,85000) for m in range(1,7)]
    tx += [txn(4,400000,'OWN_TRANSFER'),txn(3,200000,'LOAN_PROCEEDS')]
    return TransactionBatch(transactions=tx,applicant_type='SALARIED',as_of=date(2026,7,10))

def test_excludes_non_income_transfers_and_loans():
    r=reconcile(normal_batch())
    assert r['accepted_monthly_income']==85000
    assert r['excluded_credits']['OWN_TRANSFER']==400000
    assert r['excluded_credits']['LOAN_PROCEEDS']==200000
    assert r['status']=='CALCULATED'

def test_unverified_rows_not_counted_and_trigger_review():
    b=normal_batch()
    b.transactions[1].verified=False
    r=reconcile(b)
    assert 'UNVERIFIED_TRANSACTIONS_EXCLUDED' in r['findings']
    assert r['accepted_monthly_income']==0

def test_under_three_months_cannot_establish_income():
    b=normal_batch();b.transactions=[t for t in b.transactions if t.posting_date.month in (1,2)]
    r=reconcile(b)
    assert r['accepted_monthly_income']==0
    assert 'INSUFFICIENT_INCOME_COVERAGE' in r['findings']

def test_deduplicated_verified_obligations():
    b=normal_batch()
    first=txn(3,9000,'EMI','DEBIT','LOAN-123','LENDER-X')
    second={**first,'transaction_id':'same-obligation-different-bank','account_id':'bank-B'}
    from aadharshila.income import Transaction
    b.transactions.extend([Transaction.model_validate(first),Transaction.model_validate(second)])
    r=reconcile(b)
    assert r['observed_monthly_obligations']==9000
    assert 'DUPLICATE_OBLIGATION' in r['findings']

def test_engine_transaction_fail_closed():
    policy={'product':'HOME_LOAN','annual_rate_percent':9,'max_foir':0.5,'max_ltv':0.8,
            'min_income':10000,'max_tenure_months':300,'income_tolerance':0.15,
            'property_tolerance':0.15,'version':1}
    keys=['identity','bank_income','income_support','bureau','ownership','legal','valuation','screening']
    ev={x:{'verification':'VERIFIED','mode':'SIMULATED','value':{'amount':1000000 if x=='valuation' else 85000}} for x in keys}
    snap={'application':{'product':'HOME_LOAN','applicant_type':'SALARIED','amount':100000,
           'tenure_months':120,'property_value':1000000,'existing_obligations':1000,'revision':1},
           'evidence':ev,'consents':['financial_underwriting']}
    ev['bank_transactions']={'verification':'UNRESOLVED','value':normal_batch().model_dump(mode='json')}
    result=evaluate(snap,policy)
    assert result['outcome']=='REFER'
    assert any(r['code']=='TRANSACTION_RECONCILIATION_UNRESOLVED' for r in result['reasons'])

def test_ocr_off_is_not_a_false_verification():
    from pypdf import PdfWriter
    w=PdfWriter();w.add_blank_page(width=200,height=200)
    b=io.BytesIO();w.write(b)
    out=extract_pdf(b.getvalue(),ocr_enabled=False)
    assert out['status']=='NEEDS_OCR'
    assert out['signature']=='NOT_PERFORMED'
    assert out['ocr']=='NOT_PERFORMED'

def test_clamav_not_performed_without_socket(monkeypatch):
    monkeypatch.delenv('CLAMAV_UNIX_SOCKET',raising=False)
    assert clamav_scan(b'a')=='NOT_PERFORMED'

def test_clamav_scanner_fail_closed():
    with pytest.raises(DocumentSafetyError,match='MALWARE_SCANNER_UNAVAILABLE'):
        clamav_scan(b'content','/not/a/real/scanner.sock')

@pytest.mark.skipif(os.name=='nt',reason='ClamAV Unix-socket contract requires POSIX; use a Linux scanner container on Windows')
def test_clamav_protocol_reports_clean(tmp_path):
    socket_path=str(tmp_path/'clamd.sock')
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    server.bind(socket_path);server.listen(1)
    got=[]
    def accept():
        connection,_=server.accept()
        with connection:
            payload=b''
            while True:
                data=connection.recv(4096)
                payload+=data
                if payload.endswith(b'\x00\x00\x00\x00'):break
            got.append(payload)
            connection.sendall(b'stream: OK\x00')
        server.close()
    thr=threading.Thread(target=accept,daemon=True);thr.start()
    assert clamav_scan(b'hello',socket_path)=='CLEAN'
    thr.join(timeout=2)
    assert b'zINSTREAM\x00' in got[0]

def test_federated_auth_requires_pinned_mfa_claims(tmp_path,monkeypatch):
    from jwt.algorithms import RSAAlgorithm
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public_key=key.public_key()
    jwk=json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk['kid']='key-1';jwk['use']='sig';jwk['alg']='RS256'
    trust=tmp_path/'idp-jwks.json';trust.write_text(json.dumps({'keys':[jwk]}))
    monkeypatch.setenv('OIDC_JWKS_PATH',str(trust))
    monkeypatch.setenv('OIDC_ISSUER','https://idp.lender.example')
    monkeypatch.setenv('OIDC_AUDIENCE','aadharshila')
    monkeypatch.setenv('OIDC_REQUIRE_MFA','true')
    now=datetime.now(timezone.utc)
    claims={'iss':'https://idp.lender.example','aud':'aadharshila','sub':'staff-42',
            'iat':now,'exp':now+timedelta(minutes=5),'amr':['pwd','mfa']}
    token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'key-1'})
    assert validate_federated_token(token)['sub']=='staff-42'
    with pytest.raises(FederatedAuthenticationError):
        validate_federated_token(jwt.encode({**claims,'iss':'https://untrusted.example'},key,
                                            algorithm='RS256',headers={'kid':'key-1'}))
    with pytest.raises(FederatedAuthenticationError):
        validate_federated_token(jwt.encode({**claims,'amr':['pwd']},key,
                                            algorithm='RS256',headers={'kid':'key-1'}))

def test_income_endpoint_review_only_and_privileged(cases,client,login):
    case_id=cases['AS-1001']['id'];data=normal_batch().model_dump(mode='json')
    headers=login('borrower')
    r=client.post(f'/api/v1/applications/{case_id}/income-reconciliation',json=data,headers=headers)
    assert r.status_code==403
    headers=login('analyst')
    r=client.post(f'/api/v1/applications/{case_id}/income-reconciliation',json=data,headers=headers)
    assert r.status_code==200,r.text
    assert r.json()['assessment_effect']=='NONE'
    assert r.json()['accepted_monthly_income']==85000

def test_sanction_preview_nonbinding(cases,client,login):
    login('analyst')
    r=client.get(f"/api/v1/applications/{cases['AS-1001']['id']}/sanction-preview")
    assert r.status_code==200
    assert r.json()['binding'] is False
    assert r.json()['prerequisites']['disbursement']=='BLOCKED'
    assert r.json()['type']=='NON_BINDING_ASSESSMENT_PREVIEW'

def test_local_password_auth_forbidden_in_production(client,monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    r=client.post('/api/v1/auth/login',json={'username':'analyst','password':'Demo@12345'})
    assert r.status_code==403

def test_property_comparables_non_verified_never_become_accepted_collateral():
    from aadharshila.property_intelligence import PropertyReview,evaluate_property
    data=PropertyReview(area_sqm=100,declared_value_inr=8000000,comparables=[
        {'sale_reference':f'SALE-{i}','area_sqm':100,'sale_price_inr':6500000+i*100000,
         'distance_km':2,'months_ago':4,'issuer_verified':True} for i in range(3)])
    result=evaluate_property(data)
    assert result['indicative_median_valuation_inr']==6600000
    assert result['accepted_collateral_value_inr'] is None
    assert 'title_opinion' in result['missing_controls']


def test_drift_monitor_insufficient_data_and_zero_shift():
    from aadharshila.risk_monitor import population_stability_index
    assert population_stability_index([4,5],[2,7])['status']=='INSUFFICIENT_SAMPLE'
    stable=population_stability_index([100,100],[100,100])
    assert stable['psi']==0
    assert stable['status']=='CALCULATED'


def test_property_review_and_monitor_access(cases,client,login):
    app_id=cases['AS-1002']['id']
    payload={'area_sqm':120,'declared_value_inr':3000000}
    login('borrower')
    assert client.post(f'/api/v1/applications/{app_id}/property-review-preview',json=payload,
                      headers={'X-CSRF-Token':client.cookies.get('aadharshila_csrf')}).status_code==403
    headers=login('analyst')
    r=client.post(f'/api/v1/applications/{app_id}/property-review-preview',json=payload,headers=headers)
    assert r.status_code==200
    assert r.json()['status']=='REVIEW_REQUIRED'
    r=client.post('/api/v1/monitoring/feature-drift',json={'reference_counts':[150,150],
                  'current_counts':[160,140]},headers=headers)
    assert r.status_code==200 and r.json()['status']=='CALCULATED'


def test_live_consent_requires_provider_and_category(cases,client,login):
    from aadharshila.connectors import consent_authorized
    from aadharshila.models import Application, Consent
    from aadharshila.db import SessionLocal
    login('analyst')
    with SessionLocal() as db:
        app=db.get(Application,cases['AS-1001']['id'])
        assert not consent_authorized(db,app,evidence_key='bank_income',provider='BANK-PARTNER',mode='LIVE')
        consent=Consent(application_id=app.id,subject_id=app.owner_id,purpose='financial_underwriting',
                        provider='BANK-PARTNER',categories=['bank_income'])
        db.add(consent);db.flush()
        assert consent_authorized(db,app,evidence_key='bank_income',provider='BANK-PARTNER',mode='LIVE')
        assert not consent_authorized(db,app,evidence_key='bureau',provider='BANK-PARTNER',mode='LIVE')
        assert not consent_authorized(db,app,evidence_key='bank_income',provider='OTHER',mode='LIVE')
        db.rollback()

def test_compliance_controls_stay_unverified(cases,client,login):
    login('analyst')
    app_id=cases['AS-1001']['id']
    r=client.get(f'/api/v1/applications/{app_id}/compliance-checks')
    assert r.status_code==200
    assert r.json()['legal_certified'] is False
    assert r.json()['disbursement_permitted'] is False
    assert all(row['compliance_status']=='NOT_ASSESSED' for row in r.json()['controls'])
    login('borrower')
    assert client.get(f'/api/v1/applications/{app_id}/compliance-checks').status_code==403


def test_sanction_preview_redacts_staff_screening_signals(cases,client,login):
    app_id=cases['AS-1006']['id']
    login('analyst')
    staff=client.get(f'/api/v1/applications/{app_id}/sanction-preview')
    assert staff.status_code==200
    assert any(b['code']=='SCREENING_POTENTIAL_MATCH' for b in staff.json()['blockers'])

    login('borrower')
    borrower=client.get(f'/api/v1/applications/{app_id}/sanction-preview')
    assert borrower.status_code==200
    assert borrower.json()['binding'] is False
    assert 'SCREENING_' not in borrower.text
    assert 'DOCUMENT_REUSE_REVIEW' not in borrower.text
    assert any(b['code']=='ADDITIONAL_REVIEW_REQUIRED' for b in borrower.json()['blockers'])
