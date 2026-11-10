"""Security, loan policy governance, synthetic ML and document isolation regressions."""
from __future__ import annotations
import hashlib
import io
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import pytest
from pypdf import PdfWriter
from sqlalchemy import select
from aadharshila.db import SessionLocal
from aadharshila.models import Policy, User, PolicySimulation
from aadharshila.browser_sso import begin,consume_flow,exchange_authorization_code,BrowserSSOError
from aadharshila.document_isolation import extract_pdf_isolated,IsolatedExtractionUnavailable
from aadharshila.income import TransactionBatch,reconcile
from aadharshila.synthetic_risk_benchmark import generate_synthetic,run as research_run


def test_isolated_pdf_subprocess_roundtrip():
    pdf=PdfWriter();pdf.add_blank_page(width=200,height=200)
    out=io.BytesIO();pdf.write(out)
    report=extract_pdf_isolated(out.getvalue(),ocr_enabled=False)
    assert report['status']=='NEEDS_OCR' and report['page_count']==1
    assert report['signature']=='NOT_PERFORMED'
    with pytest.raises(IsolatedExtractionUnavailable):extract_pdf_isolated(b'not PDF')


def test_document_extractor_fail_closed_on_timeout(monkeypatch):
    def time_out(*args,**kwargs):raise subprocess.TimeoutExpired(cmd='isolation',timeout=5)
    monkeypatch.setattr(subprocess,'run',time_out)
    with pytest.raises(IsolatedExtractionUnavailable,match='TIMEOUT_OR_UNAVAILABLE'):
        extract_pdf_isolated(b'%PDF-1.5',timeout=5)


def test_oidc_pkce_state_endpoint_pinning(monkeypatch):
    for name,value in {
        'OIDC_ISSUER':'https://id.example.test/tenant',
        'OIDC_AUTHORIZATION_ENDPOINT':'https://id.example.test/tenant/oauth2/authorize',
        'OIDC_TOKEN_ENDPOINT':'https://id.example.test/tenant/oauth2/token',
        'OIDC_REDIRECT_URI':'http://localhost:8000/api/v1/auth/oidc/callback',
        'OIDC_CLIENT_ID':'mortgage-test-client',
    }.items():monkeypatch.setenv(name,value)
    url,cookie=begin('unit-test-secret')
    params=parse_qs(urlsplit(url).query)
    assert params['code_challenge_method']==['S256']
    assert params['response_type']==['code']
    assert 'code_verifier' not in url
    state=params['state'][0]
    flow=consume_flow(cookie,state,'unit-test-secret')
    assert flow['nonce'] and flow['verifier']
    with pytest.raises(BrowserSSOError):consume_flow(cookie,'changed-state','unit-test-secret')
    monkeypatch.setenv('OIDC_TOKEN_ENDPOINT','https://attacker.example/token')
    with pytest.raises(BrowserSSOError):begin('unit-test-secret')


def test_oidc_browser_login_revocation_and_user_deactivation(client,login,monkeypatch):
    from aadharshila import main
    for name,value in {
        'OIDC_ISSUER':'https://login.example.test/tenant',
        'OIDC_AUTHORIZATION_ENDPOINT':'https://login.example.test/authorize',
        'OIDC_TOKEN_ENDPOINT':'https://login.example.test/token',
        'OIDC_REDIRECT_URI':'http://localhost:8000/api/v1/auth/oidc/callback',
        'OIDC_CLIENT_ID':'aadharshila-e2e-test',
    }.items():monkeypatch.setenv(name,value)
    with SessionLocal() as db:
        analyst=db.scalar(select(User).where(User.username=='analyst'))
        analyst.oidc_subject='sso-preprovisioned-analyst'
        subject=analyst.id
        db.commit()
    monkeypatch.setattr(main,'exchange_authorization_code',lambda code,verifier,nonce:
                        ({'sub':'sso-preprovisioned-analyst','nonce':nonce,'amr':['pwd','mfa']},600))
    started=client.get('/api/v1/auth/oidc/start',follow_redirects=False)
    assert started.status_code==302
    state=parse_qs(urlsplit(started.headers['location']).query)['state'][0]
    rejected=client.get('/api/v1/auth/oidc/callback',params={'code':'test-code','state':'not-our-state'},follow_redirects=False)
    assert rejected.status_code==401
    accepted=client.get('/api/v1/auth/oidc/callback',params={'code':'test-code','state':state},follow_redirects=False)
    assert accepted.status_code==303 and accepted.headers['location']=='/'
    assert client.get('/api/v1/auth/me').json()['id']==subject
    token=client.cookies.get('aadharshila_csrf')
    assert client.post('/api/v1/auth/logout').status_code==403
    assert client.post('/api/v1/auth/logout',headers={'X-CSRF-Token':token}).status_code==200
    assert client.get('/api/v1/auth/me').status_code==401
    # A fresh federated session is invalidated when an administrator deactivates the identity.
    started=client.get('/api/v1/auth/oidc/start',follow_redirects=False)
    state=parse_qs(urlsplit(started.headers['location']).query)['state'][0]
    assert client.get('/api/v1/auth/oidc/callback',params={'code':'second','state':state},follow_redirects=False).status_code==303
    old_cookie=client.cookies.get('aadharshila_session')
    admin_headers=login('admin')
    response=client.post('/api/v1/users/'+subject+'/deactivate',headers=admin_headers)
    assert response.status_code==200 and response.json()['sessions_revoked']
    client.cookies.set('aadharshila_session',old_cookie)
    assert client.get('/api/v1/auth/me').status_code==401
    # Restore the seed user for independent tests.
    with SessionLocal() as db:
        user=db.get(User,subject);user.active=True;db.commit()
    client.cookies.clear()
    login('analyst')


def _income(month,amount,ref,account='bank-1',category='SALARY',direction='CREDIT',counterparty='employer'):
    return {'transaction_id':account+'-'+str(month)+'-'+ref+str(amount),
            'account_id':account,'posting_date':f'2026-{month:02d}-10','amount':amount,
            'direction':direction,'category':category,'reference':ref,'counterparty_id':counterparty,'verified':True}


def test_duplicate_credit_across_accounts_does_not_inflate_income():
    rows=[_income(m,85000,'salary-reference-long') for m in range(1,7)]
    rows.append(_income(3,85000,'salary-reference-long',account='bank-2'))
    report=reconcile(TransactionBatch(transactions=rows,applicant_type='SALARIED',as_of=date(2026,7,10)))
    assert report['accepted_monthly_income']==85000
    assert 'DUPLICATE_INCOME_RECEIPT' in report['findings']


def test_self_account_salary_label_and_statement_coverage_fail_closed():
    rows=[_income(m,60000,f'salary-2026-{m:02d}') for m in range(1,7)]
    rows.append(_income(3,300000,'self-transfer-in-disguise',counterparty='bank-1'))
    report=reconcile(TransactionBatch(transactions=rows,applicant_type='SALARIED',as_of=date(2026,7,1)))
    assert report['accepted_monthly_income']==0
    assert 'INCOME_LABEL_CONFLICTS_WITH_OWN_ACCOUNT' in report['findings']
    cleaned=rows[:6]
    short=reconcile(TransactionBatch(transactions=cleaned,applicant_type='SALARIED',as_of=date(2026,7,1),
                        statement_months=['2026-01','2026-02','2026-03']))
    assert short['accepted_monthly_income']==0
    assert 'INCOMPLETE_STATEMENT_MONTH_COVERAGE' in short['findings']


def test_policy_activation_requires_matching_independent_simulation(client,login,cases):
    author=login('policy_author')
    policy=next(p for p in client.get('/api/v1/policies').json()['items'] if p['state']=='ACTIVE' and p['product']=='HOME_LOAN')
    proposed=client.post('/api/v1/policies',json={'product':'HOME_LOAN','config':{**policy['config'],'max_ltv':.69}},headers=author)
    assert proposed.status_code==201
    pid=proposed.json()['id']
    assert client.post('/api/v1/policies/'+pid+'/validate',headers=author).status_code==200
    approver=login('policy_approver')
    assert client.post('/api/v1/policies/'+pid+'/approve',headers=approver,json={'reason':'Independent simulation has not yet been recorded'}).status_code==409
    author=login('policy_author')
    simulation=client.post('/api/v1/policies/'+pid+'/simulate',headers=author)
    assert simulation.status_code==200
    stored=client.get('/api/v1/policies/'+pid+'/simulations')
    assert stored.status_code==200 and stored.json()['items'][0]['policy_sha256']==simulation.json()['policy_sha256']
    with SessionLocal() as db:
        row=db.get(Policy,pid)
        row.config={**row.config,'max_foir':.31}
        db.commit()
    approver=login('policy_approver')
    assert client.post('/api/v1/policies/'+pid+'/approve',headers=approver,json={'reason':'Independent simulation has not yet been recorded'}).status_code==409
    # Do not activate this draft; previously tested active policies remain unchanged.


def test_synthetic_research_is_reproducible_and_not_activated(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b'
    csv_a,manifest_a=generate_synthetic(a,rows=640,seed=42)
    csv_b,manifest_b=generate_synthetic(b,rows=640,seed=42)
    assert csv_a.read_bytes()==csv_b.read_bytes()
    assert json.loads(manifest_a.read_text())['synthetic'] is True
    report=research_run(a,rows=640,seed=42)
    assert report['status']=='SYNTHETIC_TEST_ONLY' and not report['model_activated']
    assert (a/'research_model.json').exists()
    assert 'roc_auc' in report['holdout_test']


def test_operational_metrics_private_and_no_application_ids(client,login,cases,monkeypatch):
    monkeypatch.delenv('METRICS_ACCESS_TOKEN',raising=False)
    assert client.get('/internal/metrics').status_code==503
    monkeypatch.setenv('METRICS_ACCESS_TOKEN','local-test-super-long-unguessable-token')
    assert client.get('/internal/metrics').status_code==403
    result=client.get('/internal/metrics',headers={'X-Metrics-Token':'local-test-super-long-unguessable-token'})
    assert result.status_code==200 and 'aadharshila_http_requests_total' in result.text
    assert cases['AS-1001']['id'] not in result.text
    login('borrower')
    assert client.get('/api/v1/operations/http-metrics').status_code==403
    login('admin')
    staff=client.get('/api/v1/operations/http-metrics')
    assert staff.status_code==200 and staff.json()['process_local'] is True
    assert 'nosniff'==staff.headers['x-content-type-options']


def test_pdf_upload_runs_bounded_parser_and_does_not_verify(client,login,cases):
    author=login('analyst')
    writer=PdfWriter();writer.add_blank_page(width=200,height=200)
    out=io.BytesIO();writer.write(out)
    response=client.post('/api/v1/applications/'+cases['AS-1008']['id']+'/documents',
        files={'file':('synthetic-blank.pdf',out.getvalue(),'application/pdf')},headers=author)
    assert response.status_code==200,response.text
    assert response.json()['status']=='NEEDS_OCR'
    assert response.json()['verified'] is False
    assert response.json()['fields']['signature_check']=='NOT_PERFORMED'


def test_oidc_token_exchange_requires_signed_nonce_mfa_and_fixed_endpoint(monkeypatch,tmp_path):
    import base64
    import jwt
    import httpx
    from datetime import datetime,timezone,timedelta
    from cryptography.hazmat.primitives.asymmetric import rsa
    from aadharshila import browser_sso
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=key.public_key().public_numbers()
    enc=lambda n:base64.urlsafe_b64encode(n.to_bytes((n.bit_length()+7)//8,'big')).rstrip(b'=').decode()
    jwks={'keys':[{'kty':'RSA','kid':'test-oidc-key','alg':'RS256','use':'sig',
                  'n':enc(public.n),'e':enc(public.e)}]}
    file=tmp_path/'jwks.json';file.write_text(json.dumps(jwks))
    for k,v in {'OIDC_ISSUER':'https://lender-id.example.test',
                'OIDC_AUTHORIZATION_ENDPOINT':'https://lender-id.example.test/authorize',
                'OIDC_TOKEN_ENDPOINT':'https://lender-id.example.test/token',
                'OIDC_REDIRECT_URI':'http://localhost:8000/api/v1/auth/oidc/callback',
                'OIDC_CLIENT_ID':'mortgage-issuer-app','OIDC_CLIENT_SECRET':'secret-for-test',
                'OIDC_AUDIENCE':'mortgage-issuer-app',
                'OIDC_JWKS_PATH':str(file),'OIDC_REQUIRE_MFA':'true'}.items():monkeypatch.setenv(k,v)
    now=datetime.now(timezone.utc)
    claim={'sub':'staff-approved','iss':'https://lender-id.example.test','aud':'mortgage-issuer-app',
           'iat':now,'exp':now+timedelta(minutes=5),'nonce':'expected-nonce','amr':['pwd','mfa']}
    signed=jwt.encode(claim,key,algorithm='RS256',headers={'kid':'test-oidc-key'})
    recorded=[]
    # Preserve the original Client factory instead of recursive monkeypatch calls.
    real_client=httpx.Client
    def mock_factory(**kwargs):
        def handler(request):
            recorded.append(request)
            return httpx.Response(200,json={'id_token':signed})
        return real_client(transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr(browser_sso.httpx,'Client',mock_factory)
    validated,ttl=browser_sso.exchange_authorization_code('code-from-provider','pkce-verifier','expected-nonce')
    assert validated['sub']=='staff-approved' and ttl>0
    assert recorded and recorded[0].url.host=='lender-id.example.test'
    with pytest.raises(browser_sso.BrowserSSOError,match='Identity-provider verification failed'):
        browser_sso.exchange_authorization_code('code-from-provider','pkce-verifier','different-nonce')
