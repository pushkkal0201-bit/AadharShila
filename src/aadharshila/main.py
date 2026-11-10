"""Aadharshila HTTP API and bundled local interface."""
from .runtime import is_production
import os, json, re, hashlib, html, io, uuid, time, tempfile, hmac
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from typing import Literal
from fastapi import FastAPI, HTTPException, Depends, Request, Response, UploadFile, File, Header
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,field_validator,ValidationError
from sqlalchemy import select,func,text as sqltext
from sqlalchemy.orm import Session
from .db import get_db,init_db,SessionLocal
from .models import FederatedSession,PolicySimulation,Application,User,Consent,Evidence,Policy,Assessment,Document,ReviewTask,Conflict,AuditEvent,Job,Participant,ProviderInvocation
from .security import current_user,require,verify_password,token_for,SECRET
from .service import active_policy,build_assessment,bump,collect_snapshot,replay,audit
from .engine import evaluate
from .connectors import fetch_and_record, configured_adapter
from .production_gate import evaluate_configured
from .seed import seed
from .income import TransactionBatch, reconcile
from .evidence_intelligence import review_transactions, synthetic_case_batch
from .documents_pipeline import clamav_scan, DocumentSafetyError
from .document_isolation import extract_pdf_isolated, IsolatedExtractionUnavailable
from .secure_documents import (encrypt_document, decrypt_document, storage_filename,
    DocumentKeyUnavailable, DocumentIntegrityError, FORMAT_ENCRYPTED, FORMAT_LEGACY, encryption_key_status)
from .sanction import preview as sanction_preview
from .property_intelligence import PropertyReview, evaluate_property
from .risk_monitor import population_stability_index
from .risk_serving import (model_status as research_model_status, preview as research_model_preview,
                           research_drift, ResearchModelUnavailable)
from .compliance_controls import check_application, CONTROL_REGISTRY
from .browser_sso import begin as start_browser_sso, consume_flow, exchange_authorization_code, new_opaque_session, BrowserSSOError
from .observability import record as record_http, prometheus, snapshot as request_metrics

ROOT=Path(__file__).resolve().parents[2]
@asynccontextmanager
async def lifespan(application):
    init_db()
    if not is_production() and os.getenv('SEED_DEMO','true').lower()=='true':
        with SessionLocal() as db:seed(db)
    yield

app=FastAPI(title='Aadharshila API',version='0.2.0',lifespan=lifespan,
    description='Evidence-driven mortgage underwriting demonstration; lender policies and provider responses are synthetic')
WEB=ROOT/'web'
UPLOADS=Path(os.getenv('UPLOAD_DIR',str(ROOT/'var'/'documents')))
UPLOADS.mkdir(parents=True,exist_ok=True)
if WEB.is_dir():app.mount('/assets',StaticFiles(directory=WEB),name='assets')

class Login(BaseModel):
    username:str
    password:str
class ApplicationCreate(BaseModel):
    product:str
    applicant_type:str
    applicant_name:str=Field(min_length=2,max_length=150)
    amount:Decimal=Field(gt=0,le=10_000_000_000)
    tenure_months:int=Field(gt=0,le=600)
    declared_income:Decimal=Field(ge=0,le=1_000_000_000)
    existing_obligations:Decimal=Field(ge=0,le=1_000_000_000)
    property_value:Decimal=Field(gt=0,le=100_000_000_000)
    location:str=''
    employment:str=''
    @field_validator('product')
    @classmethod
    def product_valid(cls,v):
        if v not in ('HOME_LOAN','LAP'):raise ValueError('Unsupported product')
        return v
    @field_validator('applicant_type')
    @classmethod
    def type_valid(cls,v):
        if v not in ('SALARIED','SELF_EMPLOYED'):raise ValueError('Unsupported applicant type')
        return v
class ParticipantCreate(BaseModel):
    relationship:str
    name:str=Field(min_length=2,max_length=150)
    accepted_monthly_income:Decimal=Field(default=Decimal(0),ge=0)

class ConsentRequest(BaseModel):
    purpose:str
    granted:bool
    provider:str='borrower'
    categories:list[str]=Field(default_factory=list)
class EvidenceRequest(BaseModel):
    key:str=Field(pattern='^[a-z_]{3,40}$')
    value:dict
    verification:str='UNRESOLVED'
    provider:str='borrower'
    mode:str='SELF_REPORTED'
class ReviewRequest(BaseModel):
    action:str
    reason:str=Field(min_length=2)
class PolicyCreate(BaseModel):
    product:str
    config:dict
class PolicyApprovalNote(BaseModel):
    reason:str=Field(min_length=12,max_length=2000)
class ScenarioRequest(BaseModel):
    principal:float|None=None
    tenure_months:int|None=None

def serialize_app(a):
    return dict(id=a.id,reference=a.reference,product=a.product,applicant_type=a.applicant_type,applicant_name=a.applicant_name,
      amount=float(a.amount),tenure_months=a.tenure_months,declared_income=float(a.declared_income),existing_obligations=float(a.existing_obligations),
      property_value=float(a.property_value),employment=a.employment,location=a.location,workflow=a.workflow,
      verification=a.verification,revision=a.revision,created_at=a.created_at.isoformat() if a.created_at else None)

def serialize_assessment(a):
    return dict(id=a.id,application_id=a.application_id,outcome=a.outcome,revision=a.revision,created_at=a.created_at.isoformat() if a.created_at else None,
        engine_version=a.engine_version,result=a.result)

BORROWER_RESTRICTED_REASONS={'SCREENING_POTENTIAL_MATCH','TECHNICAL_FAILURE','DOCUMENT_REUSE_REVIEW','PROVIDER_UNAVAILABLE'}

def borrower_result(result):
    """Borrower projection: never export internal screening, fraud or provider failure details."""
    return {'outcome':result['outcome'],
            'reasons':[r['explanation'] for r in result['reasons']
                       if r['code'] not in BORROWER_RESTRICTED_REASONS
                       and r.get('category') not in {'screening','fraud'}],
            'policy_version':result['policy_version'],
            'evidence_revision':result['evidence_revision'],
            'note':result['note']}

def serialize_for(user,assessment):
    result=serialize_assessment(assessment)
    if user.role=='BORROWER':result['result']=borrower_result(assessment.result)
    return result

def can_view(user,a):
    if a.org_id!=user.org_id:raise HTTPException(status_code=404,detail='Application not found')
    if user.role=='BORROWER' and a.owner_id!=user.id:raise HTTPException(status_code=404,detail='Application not found')

def load_app(db,id,user):
    a=db.get(Application,id)
    if not a:raise HTTPException(status_code=404,detail='Application not found')
    can_view(user,a)
    return a

def get_assessment(db,id,user):
    a=db.get(Assessment,id)
    if not a:raise HTTPException(404,'Assessment not found')
    load_app(db,a.application_id,user)
    return a

def latest_assessment(db,app_id):
    return db.scalar(select(Assessment).where(Assessment.application_id==app_id).order_by(Assessment.revision.desc(),Assessment.created_at.desc(),Assessment.id.desc()))

def require_editor(user):require(user,{'BORROWER','ANALYST','COMPLIANCE','ADMIN'})

@app.middleware('http')
async def security_headers_and_metrics(request:Request,call_next):
    started=time.perf_counter()
    response=await call_next(request)
    route=request.scope.get('route')
    template=getattr(route,'path',None)
    if template:
        record_http(request.method,template,response.status_code,time.perf_counter()-started)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    if request.url.scheme=='https':response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    if request.url.path.startswith('/api/') or request.url.path.startswith('/internal/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.get('/internal/metrics',include_in_schema=False)
def private_metrics(request:Request):
    token=os.getenv('METRICS_ACCESS_TOKEN','')
    if len(token)<24:
        raise HTTPException(503,'Metrics export is not enabled')
    supplied=request.headers.get('X-Metrics-Token','')
    if not hmac.compare_digest(supplied,token):
        raise HTTPException(403,'Metrics authentication required')
    return PlainTextResponse(prometheus(),media_type='text/plain; version=0.0.4')

@app.get('/')
def index():return FileResponse(WEB/'index.html')
@app.get('/api/v1/meta')
def meta():
    return {'name':'Aadharshila','demo_enabled':not is_production() and os.getenv('SEED_DEMO','true').lower()=='true',
        'providers':'SIMULATED','real_sanction':False,
        'sso_enabled':bool(os.getenv('OIDC_AUTHORIZATION_ENDPOINT'))}

@app.get('/health/live')
def live():return {'status':'UP'}
@app.get('/health/ready')
def ready(db:Session=Depends(get_db)):
    try:db.execute(sqltext('SELECT 1'))
    except Exception: raise HTTPException(503,'Database unavailable')
    return {'status':'READY','database':'connected'}

@app.post('/api/v1/auth/login')
def login(body:Login,response:Response,db:Session=Depends(get_db)):
    if is_production():
        raise HTTPException(403,'Local password login is disabled in production')
    user=db.scalar(select(User).where(User.username==body.username))
    if not user or not verify_password(body.password,user.password_hash) or not user.active:
        raise HTTPException(status_code=401,detail='Invalid credentials')
    secure=is_production()
    response.set_cookie('aadharshila_session',token_for(user),httponly=True,secure=secure,samesite='lax',max_age=28800)
    csrf=uuid.uuid4().hex
    response.set_cookie('aadharshila_csrf',csrf,secure=secure,samesite='lax',max_age=28800)
    return {'user':{'username':user.username,'role':user.role},'csrf':csrf}
@app.get('/api/v1/auth/oidc/start')
def oidc_start():
    try:
        url,flow_cookie=start_browser_sso(SECRET)
    except BrowserSSOError as exc:
        raise HTTPException(503,str(exc)) from None
    response=RedirectResponse(url,status_code=302)
    response.set_cookie('aadharshila_oidc_flow',flow_cookie,httponly=True,
                        secure=is_production(),samesite='lax',max_age=300,path='/api/v1/auth/oidc')
    response.headers['Cache-Control']='no-store'
    return response

@app.get('/api/v1/auth/oidc/callback')
def oidc_callback(request:Request,code:str|None=None,state:str|None=None,db:Session=Depends(get_db)):
    try:
        if not code or not state:raise BrowserSSOError('OIDC callback missing code or state')
        flow=consume_flow(request.cookies.get('aadharshila_oidc_flow'),state,SECRET)
        claims,ttl=exchange_authorization_code(code,flow['verifier'],flow['nonce'])
        user=db.scalar(select(User).where(User.oidc_subject==claims['sub'],User.active.is_(True)))
        if user is None:raise BrowserSSOError('Identity requires prior lender provisioning')
        token,token_hash=new_opaque_session()
        db.add(FederatedSession(token_hash=token_hash,user_id=user.id,
            expires_at=datetime.now(timezone.utc)+timedelta(seconds=ttl)))
        db.commit()
    except BrowserSSOError as exc:
        raise HTTPException(401,str(exc)) from None
    response=RedirectResponse('/',status_code=303)
    response.delete_cookie('aadharshila_oidc_flow',path='/api/v1/auth/oidc')
    response.set_cookie('aadharshila_session',token,httponly=True,
        secure=is_production(),samesite='lax',max_age=ttl)
    response.set_cookie('aadharshila_csrf',uuid.uuid4().hex,
        secure=is_production(),samesite='lax',max_age=ttl)
    response.headers['Cache-Control']='no-store'
    return response

@app.post('/api/v1/auth/logout')
def logout(response:Response,request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    cookie=request.cookies.get('aadharshila_session','')
    if cookie.startswith('fs_'):
        session=db.get(FederatedSession,hashlib.sha256(cookie.encode()).hexdigest())
        if session and session.user_id==user.id:
            session.revoked_at=datetime.now(timezone.utc);db.commit()
    response.delete_cookie('aadharshila_session');response.delete_cookie('aadharshila_csrf')
    return {'ok':True}
@app.get('/api/v1/auth/me')
def me(user:User=Depends(current_user)):
    return {'id':user.id,'username':user.username,'role':user.role}

@app.post('/api/v1/users/{user_id}/deactivate')
def deactivate_user(user_id:str,request:Request,db:Session=Depends(get_db),actor:User=Depends(current_user)):
    require(actor,{'ADMIN'})
    if user_id==actor.id:raise HTTPException(409,'Cannot deactivate your own administrator account')
    target=db.scalar(select(User).where(User.id==user_id,User.org_id==actor.org_id))
    if not target:raise HTTPException(404,'User not found')
    target.active=False
    for sess in db.scalars(select(FederatedSession).where(FederatedSession.user_id==target.id,
                      FederatedSession.revoked_at.is_(None))).all():
        sess.revoked_at=datetime.now(timezone.utc)
    db.add(AuditEvent(actor_id=actor.id,role=actor.role,action='USER_DEACTIVATED',detail={'user_id':target.id}))
    db.commit()
    return {'status':'DEACTIVATED','sessions_revoked':True}

@app.get('/api/v1/operations/http-metrics')
def staff_http_metrics(user:User=Depends(current_user)):
    require(user,{'ADMIN','AUDITOR','COMPLIANCE'})
    return {'process_local':True,'contains_borrower_identifiers':False,'items':request_metrics()}

@app.get('/api/v1/applications')
def list_applications(limit:int=50,offset:int=0,db:Session=Depends(get_db),user:User=Depends(current_user)):
    limit=min(max(limit,1),100);offset=max(offset,0)
    statement=select(Application).where(Application.org_id==user.org_id)
    if user.role=='BORROWER':statement=statement.where(Application.owner_id==user.id)
    rows=db.scalars(statement.order_by(Application.reference).limit(limit).offset(offset)).all()
    all_assessments=db.scalars(select(Assessment).where(Assessment.application_id.in_([a.id for a in rows])).order_by(Assessment.created_at,Assessment.revision)).all() if rows else []
    latest={}
    for assessment in all_assessments:latest[assessment.application_id]=assessment.outcome
    return {'items':[{**serialize_app(a),'latest_outcome':latest.get(a.id)} for a in rows], 'limit':limit,'offset':offset}

@app.post('/api/v1/applications',status_code=201)
def create_application(body:ApplicationCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user)
    ref='AS-'+uuid.uuid4().hex[:8].upper()
    a=Application(org_id=user.org_id,owner_id=user.id,reference=ref,**body.model_dump())
    db.add(a);db.flush();audit(db,a.id,user,'APPLICATION_CREATED');db.commit()
    return serialize_app(a)

@app.get('/api/v1/applications/{id}/participants')
def participants(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user)
    rows=db.scalars(select(Participant).where(Participant.application_id==id)).all()
    return {'items':[{'id':r.id,'name':r.name,'relationship':r.relationship,'accepted_monthly_income':float(r.accepted_monthly_income)} for r in rows]}

@app.post('/api/v1/applications/{id}/participants')
def add_participant(id:str,body:ParticipantCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user);a=load_app(db,id,user)
    if body.relationship not in ('CO_APPLICANT','GUARANTOR'):
        raise HTTPException(422,'Unsupported relationship')
    # Co-applicant income requires its own proven evidence and is NOT silently included.
    if body.accepted_monthly_income!=0:
        raise HTTPException(422,'Additional applicant income must be verified independently')
    row=Participant(application_id=id,name=body.name,relationship=body.relationship,accepted_monthly_income=0)
    db.add(row);bump(db,a,user,'Participant added')
    if a.workflow!='DRAFT':build_assessment(db,a,user)
    db.commit()
    return {'id':row.id,'relationship':row.relationship,'name':row.name,'income_included':False}

@app.get('/api/v1/applications/{id}')
def detail(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=load_app(db,id,user);latest=latest_assessment(db,id)
    return {'application':serialize_app(a),'latest_assessment':serialize_for(user,latest) if latest else None}

class ApplicationPatch(BaseModel):
    applicant_name:str|None=Field(default=None,min_length=2,max_length=150)
    location:str|None=Field(default=None,max_length=150)
    employment:str|None=Field(default=None,max_length=150)
    amount:Decimal|None=Field(default=None,gt=0,le=10_000_000_000)
    tenure_months:int|None=Field(default=None,ge=1,le=600)
    declared_income:Decimal|None=Field(default=None,ge=0,le=1_000_000_000)
    existing_obligations:Decimal|None=Field(default=None,ge=0,le=1_000_000_000)
    property_value:Decimal|None=Field(default=None,gt=0,le=100_000_000_000)
    model_config={'extra':'forbid'}

@app.patch('/api/v1/applications/{id}')
def modify_application(id:str,body:ApplicationPatch,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user);a=load_app(db,id,user)
    if a.workflow=='WITHDRAWN':raise HTTPException(409,'Cannot update a withdrawn application')
    changes=body.model_dump(exclude_unset=True)
    if not changes:raise HTTPException(422,'No fields submitted')
    if any(value is None for value in changes.values()):raise HTTPException(422,'Null fields are not supported')
    for key,value in changes.items():setattr(a,key,value)
    bump(db,a,user,'Application fields corrected')
    if a.workflow!='DRAFT':build_assessment(db,a,user)
    db.commit();return serialize_app(a)

@app.post('/api/v1/applications/{id}/submit')
def submit(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user);a=load_app(db,id,user)
    if a.workflow!='DRAFT':raise HTTPException(409,'Application already submitted')
    a.workflow='SUBMITTED';audit(db,a.id,user,'APPLICATION_SUBMITTED')
    assessed=build_assessment(db,a,user);db.commit()
    return serialize_for(user,assessed)

@app.post('/api/v1/applications/{id}/consents')
def add_consent(id:str,body:ConsentRequest,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'BORROWER'});a=load_app(db,id,user)
    if body.purpose!='financial_underwriting':raise HTTPException(422,'Unsupported consent purpose')
    existing=db.scalars(select(Consent).where(Consent.application_id==id,Consent.purpose==body.purpose,Consent.revoked_at==None)).all()
    for c in existing:c.revoked_at=datetime.now(timezone.utc)
    if body.granted:
        db.add(Consent(application_id=id,subject_id=user.id,purpose=body.purpose,provider=body.provider,categories=body.categories))
    bump(db,a,user,'Consent granted' if body.granted else 'Consent revoked')
    if a.workflow!='DRAFT':build_assessment(db,a,user)
    db.commit();return {'purpose':body.purpose,'granted':body.granted,'revision':a.revision}

@app.get('/api/v1/applications/{id}/evidence')
def evidence_list(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=load_app(db,id,user)
    snapshot=collect_snapshot(db,a)
    visible=snapshot['evidence'] if user.role!='BORROWER' else {k:v for k,v in snapshot['evidence'].items() if k!='screening'}
    return {'revision':a.revision,'evidence':visible,'consents':snapshot['consents']}

@app.post('/api/v1/applications/{id}/evidence')
def add_evidence(id:str,body:EvidenceRequest,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user);a=load_app(db,id,user)
    # Borrower uploads and statements cannot assign verified status.
    if user.role=='BORROWER' and (body.verification!='UNRESOLVED' or body.mode!='SELF_REPORTED'):
        raise HTTPException(403,'Borrowers cannot verify their own evidence')
    if body.verification not in ('VERIFIED','UNRESOLVED','FAILED') or body.mode not in ('SIMULATED','SELF_REPORTED','SANDBOX'):
        raise HTTPException(422,'Invalid evidence mode or verification')
    if body.mode!='SELF_REPORTED' and user.role not in ('ANALYST','COMPLIANCE','ADMIN'):
        raise HTTPException(403,'Analyst authorization required')
    if body.verification=='VERIFIED' and (body.mode!='SIMULATED' or body.provider!='local-review-fixture'):
        raise HTTPException(422,'Only explicitly labeled local-review fixtures can assert verified status in this build')
    if body.key not in {'identity','bank_income','income_support','bureau','ownership','legal','valuation','screening','obligations'}:
        raise HTTPException(422,'Unsupported evidence key')
    bump(db,a,user,f'Updated {body.key}')
    e=Evidence(application_id=id,key=body.key,value=body.value,mode=body.mode,verification=body.verification,provider=body.provider,revision=a.revision)
    db.add(e);db.flush()
    assessment=build_assessment(db,a,user) if a.workflow!='DRAFT' else None
    db.commit();return {'evidence_id':e.id,'revision':a.revision,'assessment':serialize_for(user,assessment) if assessment else None}

@app.get('/api/v1/applications/{id}/conflicts')
def conflicts(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user);a=latest_assessment(db,id)
    return {'assessment_id':a.id if a else None,'items':a.result['conflicts'] if a else []}

@app.post('/api/v1/applications/{id}/assessments')
def assess(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user);a=load_app(db,id,user)
    if a.workflow=='DRAFT':raise HTTPException(409,'Submit application first')
    ass=build_assessment(db,a,user);db.commit();return serialize_for(user,ass)

@app.post('/api/v1/applications/{id}/queue-reassessment')
def queue_reassessment(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','ADMIN'});a=load_app(db,id,user)
    if a.workflow=='DRAFT':raise HTTPException(409,'Submit first')
    bump(db,a,user,'Manual queued reassessment',queue=True)
    db.flush()
    job=db.scalar(select(Job).where(Job.application_id==a.id,Job.target_revision==a.revision))
    db.commit()
    return {'job_id':job.id,'status':job.status,'target_revision':job.target_revision}

@app.get('/api/v1/jobs/{id}')
def job_status(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    j=db.get(Job,id)
    if not j:raise HTTPException(404,'Job not found')
    load_app(db,j.application_id,user)
    return {'id':j.id,'status':j.status,'attempts':j.attempts,'target_revision':j.target_revision,'error_category':j.last_error}

@app.get('/api/v1/applications/{id}/assessments')
def history(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user)
    rows=db.scalars(select(Assessment).where(Assessment.application_id==id).order_by(Assessment.created_at,Assessment.revision)).all()
    return {'items':[serialize_for(user,a) for a in rows]}

@app.get('/api/v1/assessments/{id}')
def assessment_detail(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return serialize_for(user,get_assessment(db,id,user))
@app.get('/api/v1/assessments/{id}/decision')
def assessment_decision(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=get_assessment(db,id,user)
    if user.role=='BORROWER':return borrower_result(a.result)
    return {k:a.result[k] for k in ('outcome','reasons','policy_version','engine_version','evidence_revision','note')}
@app.get('/api/v1/assessments/{id}/explanation')
def explanation(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=get_assessment(db,id,user)
    if user.role=='BORROWER':return borrower_result(a.result)
    return a.result
@app.post('/api/v1/assessments/{id}/replay')
def replay_assessment(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=get_assessment(db,id,user);return replay(a)

@app.get('/api/v1/assessments/{id}/evidence-pack')
def evidence_pack(id:str,format:str='json',db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=get_assessment(db,id,user);app_row=load_app(db,a.application_id,user)
    if user.role=='BORROWER':
        public=borrower_result(a.result)
    else:public=a.result
    contents={'reference':app_row.reference,'assessment_id':a.id,'result':public,'snapshot':a.snapshot if user.role!='BORROWER' else {'application':{'reference':app_row.reference},'note':'Detailed evidence restricted'} }
    if format=='json':return contents
    if format!='html':raise HTTPException(422,'Use json or html')
    borrower_hidden=BORROWER_RESTRICTED_REASONS
    public_reasons=[r for r in a.result['reasons'] if user.role!='BORROWER' or r['code'] not in borrower_hidden]
    reason_html=''.join('<li>'+html.escape(r['explanation'])+'</li>' for r in public_reasons)
    return HTMLResponse(f'<!doctype html><meta charset="utf-8"><title>Aadharshila evidence report</title><main style="font-family:system-ui;max-width:760px;margin:40px auto"><h1>Aadharshila</h1><p>Demonstration assessment — not a sanction letter.</p><h2>{html.escape(app_row.reference)} — {html.escape(a.outcome)}</h2><p>Policy version {a.result["policy_version"]}; evidence revision {a.revision}</p><h3>Reasons</h3><ul>{reason_html}</ul><p>Generated from stored assessment evidence.</p></main>')

@app.post('/api/v1/applications/{id}/alternative-scenarios')
def alternatives(id:str,body:ScenarioRequest,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=load_app(db,id,user);current=latest_assessment(db,id)
    if not current:raise HTTPException(409,'Assessment missing')
    from .finance import alternative
    policy=current.snapshot['policy'];f=current.result['financials']
    if not f: return {'alternative':None,'reason':'Insufficient valid financial data'}
    principal=body.principal if body.principal is not None else float(a.amount)
    tenure=body.tenure_months if body.tenure_months is not None else a.tenure_months
    if principal<=0 or tenure<=0:raise HTTPException(422,'Invalid scenario terms')
    return {'alternative':alternative(principal,policy['annual_rate_percent'],tenure,f['accepted_income'],f['existing_obligations'],f['accepted_property_value'],policy['max_foir'],policy['max_ltv'],policy['max_tenure_months']),
           'policy_version':policy['version'],'note':'Scenario only. No borrower terms changed.'}

@app.post('/api/v1/applications/{id}/stress-scenarios')
def stresses(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user);a=latest_assessment(db,id)
    return {'scenarios':a.result['stress'] if a else [],'note':'Hypothetical sensitivity tests, not forecasts.'}

@app.get('/api/v1/review-tasks')
def list_reviews(db:Session=Depends(get_db),user:User=Depends(current_user)):
    ids=[a.id for a in db.scalars(select(Application).where(Application.org_id==user.org_id)).all() if user.role!='BORROWER' or a.owner_id==user.id]
    if not ids:return {'items':[]}
    rows=db.scalars(select(ReviewTask).where(ReviewTask.application_id.in_(ids)).order_by(ReviewTask.status,ReviewTask.reason_code).limit(250)).all()
    return {'items':[{'id':t.id,'application_id':t.application_id,'reason_code':t.reason_code,'status':t.status,'request_text':t.request_text,'resolution':t.resolution} for t in rows]}

@app.post('/api/v1/review-tasks/{id}/actions')
def act_on_review(id:str,body:ReviewRequest,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','ADMIN'})
    t=db.get(ReviewTask,id)
    if not t:raise HTTPException(404,'Task not found')
    a=load_app(db,t.application_id,user)
    if body.action not in ('RESOLVE','REOPEN'):raise HTTPException(422,'Unsupported action')
    t.status='RESOLVED' if body.action=='RESOLVE' else 'OPEN'
    t.resolution=body.reason;t.actor_id=user.id
    audit(db,a.id,user,'REVIEW_'+body.action,body.reason,{'task_id':id})
    db.commit();return {'status':t.status,'note':'Resolving a task does not bypass mandatory evidence gates.'}

@app.get('/api/v1/applications/{id}/audit')
def audit_history(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user)
    rows=db.scalars(select(AuditEvent).where(AuditEvent.application_id==id).order_by(AuditEvent.timestamp)).all()
    if user.role=='BORROWER':
        allowed={'APPLICATION_CREATED','APPLICATION_SUBMITTED','ASSESSMENT_COMPLETED','EVIDENCE_REVISION','DOCUMENT_UPLOADED','DOCUMENT_ACCESSED'}
        return {'items':[{'action':x.action,'timestamp':x.timestamp.isoformat(),'role':x.role} for x in rows if x.action in allowed]}
    return {'items':[{'action':x.action,'timestamp':x.timestamp.isoformat(),'role':x.role,'reason':x.reason,'detail':x.detail} for x in rows]}

@app.get('/api/v1/policies')
def policies(db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','POLICY_AUTHOR','POLICY_APPROVER','AUDITOR','ADMIN'})
    rows=db.scalars(select(Policy).where(Policy.org_id==user.org_id).order_by(Policy.product,Policy.version)).all()
    return {'items':[{'id':p.id,'product':p.product,'version':p.version,'state':p.state,'config':p.config,'author_id':p.author_id,'approver_id':p.approver_id} for p in rows]}

def policy_config_digest(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def policy_simulation_for_approval(db,policy):
    simulations=db.scalars(select(PolicySimulation).where(
        PolicySimulation.policy_id==policy.id,PolicySimulation.org_id==policy.org_id
    ).order_by(PolicySimulation.created_at.desc(),PolicySimulation.id.desc())).all()
    digest=policy_config_digest(policy.config)
    return next((s for s in simulations if s.policy_sha256==digest and s.report.get('evaluated',0)>0),None)

def policy_for_user(db,id,user):
    policy=db.scalar(select(Policy).where(Policy.id==id,Policy.org_id==user.org_id))
    if policy is None:raise HTTPException(404,'Policy not found')
    return policy

def validate_policy_config(conf):
    required={'product','annual_rate_percent','max_foir','max_ltv','min_income','max_tenure_months','income_tolerance','property_tolerance','authority'}
    if not required.issubset(set(conf)):raise HTTPException(422,'Missing policy fields: '+str(sorted(required-set(conf))))
    if conf['product'] not in ('HOME_LOAN','LAP') or conf['authority']!='DEMONSTRATION_ASSUMPTION':raise HTTPException(422,'Only illustrative policies can be authored')
    for k in ('max_foir','max_ltv','income_tolerance','property_tolerance'):
        if not isinstance(conf[k],(float,int)) or not 0<conf[k]<=1:raise HTTPException(422,'Invalid policy ratio: '+k)
    if not 0<=conf['annual_rate_percent']<=40 or not 1<=conf['max_tenure_months']<=600 or conf['min_income']<0:raise HTTPException(422,'Invalid policy limits')
    return True
@app.post('/api/v1/policies',status_code=201)
def create_policy(body:PolicyCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'POLICY_AUTHOR','ADMIN'})
    cfg=body.config
    if cfg.get('product')!=body.product:raise HTTPException(422,'Product mismatch')
    validate_policy_config(cfg)
    n=db.scalar(select(func.max(Policy.version)).where(Policy.org_id==user.org_id,Policy.product==body.product)) or 0
    p=Policy(org_id=user.org_id,name='Proposed illustrative policy',product=body.product,version=n+1,config={**cfg,'version':n+1},state='DRAFT',author_id=user.id)
    db.add(p);db.commit();return {'id':p.id,'version':p.version,'state':p.state}
@app.post('/api/v1/policies/{id}/validate')
def validate_policy(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'POLICY_AUTHOR','ADMIN'});p=policy_for_user(db,id,user)
    if p.state!='DRAFT':raise HTTPException(409,'Only a draft may be validated')
    validate_policy_config(p.config);p.state='VALIDATED';db.commit();return {'state':p.state}
@app.post('/api/v1/policies/{id}/simulate')
def simulate_policy(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'POLICY_AUTHOR','POLICY_APPROVER','ANALYST','ADMIN'})
    p=policy_for_user(db,id,user)
    validate_policy_config(p.config)
    apps=db.scalars(select(Application).where(Application.product==p.product,Application.org_id==user.org_id)).all()
    changes=[];old={'APPROVE':0,'REJECT':0,'REFER':0};new={'APPROVE':0,'REJECT':0,'REFER':0}
    for row in apps:
        prev=latest_assessment(db,row.id)
        if prev:
            out=evaluate(prev.snapshot['input'],{**p.config,'version':p.version})
            old[prev.outcome]+=1;new[out['outcome']]+=1
            if prev.outcome!=out['outcome']:changes.append({'reference':row.reference,'old':prev.outcome,'new':out['outcome']})
    report={'product':p.product,'version':p.version,'original_counts':old,'simulated_counts':new,
            'changes':changes,'evaluated':sum(old.values()),
            'note':'Synthetic portfolio, no original decisions modified.'}
    record=PolicySimulation(org_id=user.org_id,policy_id=p.id,actor_id=user.id,
                            policy_sha256=policy_config_digest(p.config),report=report)
    db.add(record)
    db.add(AuditEvent(actor_id=user.id,role=user.role,action='POLICY_SIMULATED',
                      detail={'policy_id':p.id,'simulation_id':record.id,'policy_sha256':record.policy_sha256}))
    db.commit()
    return {**report,'simulation_id':record.id,'policy_sha256':record.policy_sha256}
@app.post('/api/v1/policies/{id}/approve')
def approve_policy(id:str,body:PolicyApprovalNote,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'POLICY_APPROVER','ADMIN'});p=policy_for_user(db,id,user)
    if p.state!='VALIDATED' or p.author_id==user.id:
        raise HTTPException(409,'Validation and separation of duties required')
    simulation=policy_simulation_for_approval(db,p)
    if simulation is None:raise HTTPException(409,'Current policy must have a completed portfolio simulation')
    if simulation.actor_id==user.id:raise HTTPException(409,'Independent simulation and approval required')
    p.state='APPROVED';p.approver_id=user.id
    db.add(AuditEvent(actor_id=user.id,role=user.role,action='POLICY_APPROVED',
         reason=body.reason,detail={'policy_id':p.id,'simulation_id':simulation.id,'policy_sha256':simulation.policy_sha256}))
    db.commit();return {'state':p.state,'simulation_id':simulation.id}
@app.post('/api/v1/policies/{id}/activate')
def activate_policy(id:str,body:PolicyApprovalNote,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'POLICY_APPROVER','ADMIN'});p=policy_for_user(db,id,user)
    if p.state!='APPROVED' or p.approver_id!=user.id:raise HTTPException(409,'Approved policy required')
    for prior in db.scalars(select(Policy).where(Policy.org_id==user.org_id,Policy.product==p.product,Policy.state=='ACTIVE')).all():prior.state='RETIRED'
    db.flush()  # Retire the previous active policy before activating the new one.
    if policy_simulation_for_approval(db,p) is None:
        raise HTTPException(409,'Matching preapproval simulation no longer exists')
    p.state='ACTIVE'
    db.add(AuditEvent(actor_id=user.id,role=user.role,action='POLICY_ACTIVATED',reason=body.reason,
                      detail={'policy_id':p.id,'version':p.version,'product':p.product}))
    db.commit();return {'state':p.state}

@app.get('/api/v1/policies/{id}/simulations')
def policy_simulations(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','POLICY_AUTHOR','POLICY_APPROVER','AUDITOR','ADMIN'})
    p=policy_for_user(db,id,user)
    records=db.scalars(select(PolicySimulation).where(PolicySimulation.policy_id==p.id,
             PolicySimulation.org_id==user.org_id).order_by(PolicySimulation.created_at.desc()).limit(50)).all()
    return {'items':[{'id':x.id,'policy_sha256':x.policy_sha256,'created_at':x.created_at.isoformat(),
                      'actor_id':x.actor_id,'report':x.report} for x in records]}

@app.get('/api/v1/operations/governance-audit')
def governance_audit(db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'POLICY_AUTHOR','POLICY_APPROVER','COMPLIANCE','AUDITOR','ADMIN'})
    rows=db.scalars(select(AuditEvent).join(User,AuditEvent.actor_id==User.id).where(
        User.org_id==user.org_id,AuditEvent.application_id.is_(None),
        AuditEvent.action.in_(['POLICY_SIMULATED','POLICY_APPROVED','POLICY_ACTIVATED','USER_DEACTIVATED'])
    ).order_by(AuditEvent.timestamp.desc(),AuditEvent.id.desc()).limit(100)).all()
    return {'items':[{'action':r.action,'timestamp':r.timestamp.isoformat(),
            'role':r.role,'reason':r.reason,'detail':r.detail} for r in rows]}

@app.get('/api/v1/operations/readiness')
def production_readiness(db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','AUDITOR','ADMIN','POLICY_APPROVER'})
    keys=['identity','bank_income','income_support','bureau','ownership','legal','valuation','screening']
    providers={}
    for key in keys:
        adapter,error=configured_adapter(key)
        providers[key]={'configuration_mode':adapter.mode if adapter else 'UNAVAILABLE',
                        'configuration_error':error, 'live_verified':False}
    policies={}
    for product in ('HOME_LOAN','LAP'):
        try:
            policy=active_policy(db,product,user.org_id)
            config={**policy.config,'version':policy.version}
            gate=evaluate_configured(organization_id=user.org_id,product=product,policy=config)
            policies[product]={'active_policy_version':policy.version,
                               'signed_attestations':gate}
        except ValueError:
            policies[product]={'active_policy_version':None,'error':'ACTIVE_POLICY_MISSING'}
    # This reports external signature verification, not institution/issuer licensing.
    all_signed=all(p.get('signed_attestations',{}).get('valid',False) for p in policies.values())
    return {'application':'Aadharshila','environment':os.getenv('APP_ENV','development'),
            'automatic_real_underwriting':('SIGNED_GOVERNANCE_PREREQUISITES_PRESENT'
                if all_signed and is_production() else 'BLOCKED_BY_GOVERNANCE_GATE'),
            'production_authorizations':policies.get('HOME_LOAN',{}).get('signed_attestations',{}).get('requirements',{}),
            'per_product':policies,
            'providers':providers,
            'document_storage':{**encryption_key_status(), 'encryption_required':is_production(),
                                'legacy_plaintext_allowed':not is_production()},
            'note':'Signatures are checked against an institution-configured trust store. Licensing, legal competence, and production certification cannot be established by this software.'}

@app.get('/api/v1/applications/{id}/compliance-checks')
def application_compliance_checks(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','AUDITOR','ADMIN'})
    row=load_app(db,id,user)
    assessment=latest_assessment(db,id)
    if assessment is None:raise HTTPException(409,'Assessment required')
    return check_application(assessment.snapshot['input'],assessment.result)

@app.get('/api/v1/compliance/register')
def compliance_register(user:User=Depends(current_user)):
    return {'items':json.loads((ROOT/'data'/'regulatory-register.json').read_text()),'engineering_control_registry':CONTROL_REGISTRY,
        'note':'Official primary-source references only. No clause-specific legal certification or executable regulatory controls.'}

@app.get('/api/v1/connectors')
def connector_matrix(user:User=Depends(current_user)):
    names=[('Identity/KYC','identity'),('CKYCR','ckyc'),('DigiLocker','digilocker'),('Account Aggregator','account_aggregator'),('Bank income','bank_income'),('Bank transactions','bank_transactions'),('Credit bureau','bureau'),('GST/tax','gst'),('Income support','income_support'),('Property registry','property_registry'),('CERSAI','cersai'),('RERA','rera'),('Valuation','valuation'),('Legal/title','legal'),('Sanctions/PEP','screening')]
    records=[]
    for name,key in names:
        adapter,error=configured_adapter(key) if key else (None,'PROVIDER_SPECIFIC_INTEGRATION_REQUIRED')
        mode=adapter.mode if adapter else 'UNAVAILABLE'
        records.append({'name':name,'evidence_key':key,'mode':mode,
                        'verified_live':False,'configuration_error':error,
                        'note':('Signed authorized partner gateway configured; no actual provider verification asserted.'
                                if mode in ('SANDBOX','LIVE') else
                                'Deterministic local fixture; not a real provider.' if mode=='SIMULATED' else
                                'Provider onboarding/authorization not configured.')})
    return {'items':records,'note':'Configured mode is not evidence of successful authorized provider onboarding.'}

@app.post('/api/v1/applications/{id}/providers/{key}/run')
def run_provider(id:str,key:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','ADMIN'});a=load_app(db,id,user)
    try:response=fetch_and_record(db,a,key,user)
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(422,str(exc))
    db.commit()
    return response

@app.post('/api/v1/applications/{id}/income-reconciliation')
def income_reconciliation(id:str,body:TransactionBatch,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','ADMIN'})
    a=load_app(db,id,user)
    if body.applicant_type!=a.applicant_type:raise HTTPException(422,'Applicant category mismatch')
    result=reconcile(body)
    # Exploratory financial calculation. Only independently authenticated provider evidence
    # can be materialized into an underwriting assessment by the evidence pipeline.
    return {**result,'assessment_effect':'NONE','source_mode':'ANALYST_SUBMITTED_PREVIEW',
            'note':'Not independent bank verification, cannot authorize a mortgage decision.'}

@app.post('/api/v1/applications/{id}/evidence-intelligence')
def evidence_intelligence(id:str,body:TransactionBatch,db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Analyst-only ML-assisted review; no writes, promotions, or decision mutations."""
    require(user,{'ANALYST','COMPLIANCE','ADMIN'})
    a=load_app(db,id,user)
    if body.applicant_type!=a.applicant_type:raise HTTPException(422,'Applicant category mismatch')
    if len(body.transactions)>360:raise HTTPException(422,'Preview limited to 360 transactions')
    snapshot=collect_snapshot(db,a)
    evidence=snapshot.get('evidence',{})
    def value(key):
        raw=evidence.get(key,{}).get('value',{})
        return raw.get('amount') if isinstance(raw,dict) else None
    policy=active_policy(db,a.product,a.org_id)
    return review_transactions(body,value('bank_income'),value('income_support'),
                               float(policy.config['income_tolerance']))

@app.get('/api/v1/applications/{id}/evidence-intelligence/demo')
def evidence_intelligence_demo(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Synthetic, fixed, local sample with transaction provenance explicitly marked demo."""
    require(user,{'ANALYST','COMPLIANCE','ADMIN'})
    a=load_app(db,id,user)
    if is_production():raise HTTPException(404,'Synthetic demo unavailable')
    return {'sample':synthetic_case_batch(a.applicant_type).model_dump(mode='json'),
            'classification':'SYNTHETIC_ANALYST_INPUT',
            'note':'Generated only for a local judge demonstration. No bank provider is contacted.'}

@app.post('/api/v1/applications/{id}/property-review-preview')
def property_review_preview(id:str,body:PropertyReview,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','ADMIN'})
    load_app(db,id,user)
    return {**evaluate_property(body),'assessment_effect':'NONE'}

class DriftRequest(BaseModel):
    reference_counts:list[int]=Field(min_length=2,max_length=200)
    current_counts:list[int]=Field(min_length=2,max_length=200)

@app.post('/api/v1/monitoring/feature-drift')
def feature_drift(body:DriftRequest,user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','AUDITOR','ADMIN'})
    try:return population_stability_index(body.reference_counts,body.current_counts)
    except ValueError as exc:raise HTTPException(422,str(exc))

class ResearchRiskPreviewRequest(BaseModel):
    features:dict[str,float]=Field(min_length=6,max_length=6)
    synthetic_acknowledged:Literal[True]

class ResearchRiskDriftRequest(BaseModel):
    rows:list[dict[str,float]]=Field(min_length=100,max_length=2000)
    synthetic_acknowledged:Literal[True]

@app.get('/api/v1/research/risk-model/status')
def risk_model_research_status(user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','AUDITOR','ADMIN'})
    if is_production():
        raise HTTPException(404,'Research model preview is unavailable')
    try:return research_model_status()
    except ResearchModelUnavailable as exc:
        return {'status':'NOT_READY', 'reason':str(exc), 'model_activated':False,
                'training_reference':'SYNTHETIC_ONLY', 'documentation':'docs/hackathon/FULL_ML_PIPELINE.md'}

@app.post('/api/v1/research/risk-model/preview')
def risk_model_research_preview(body:ResearchRiskPreviewRequest,user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','ADMIN'})
    if is_production():
        raise HTTPException(404,'Research model preview is unavailable')
    try:return research_model_preview(body.features)
    except ResearchModelUnavailable as exc:raise HTTPException(503,str(exc))
    except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc))

@app.post('/api/v1/research/risk-model/drift')
def risk_model_research_drift(body:ResearchRiskDriftRequest,user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','AUDITOR','ADMIN'})
    if is_production():
        raise HTTPException(404,'Research model preview is unavailable')
    try:return research_drift(body.rows)
    except ResearchModelUnavailable as exc:raise HTTPException(503,str(exc))
    except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc))

@app.get('/api/v1/applications/{id}/sanction-preview')
def get_sanction_preview(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=load_app(db,id,user)
    item=latest_assessment(db,id)
    if not item:raise HTTPException(409,'Assessment required before a preview')
    return sanction_preview(item,a,borrower_view=user.role=='BORROWER')

@app.get('/api/v1/applications/{id}/provider-calls')
def provider_calls(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user)
    require(user,{'ANALYST','COMPLIANCE','AUDITOR','ADMIN'})
    rows=db.scalars(select(ProviderInvocation).where(ProviderInvocation.application_id==id).order_by(ProviderInvocation.started_at.desc())).all()
    return {'items':[{'request_id':x.request_id,'key':x.evidence_key,'mode':x.mode,'provider':x.provider_name,
        'status':x.status,'error_category':x.error_category,'started_at':x.started_at.isoformat()} for x in rows]}

@app.post('/api/v1/applications/{id}/documents')
async def upload_document(id:str,file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_editor(user);a=load_app(db,id,user)
    raw=await file.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise HTTPException(413,'File exceeds 8 MiB limit')
    if not raw:raise HTTPException(422,'Empty file')
    is_pdf=raw.startswith(b'%PDF-');is_txt=not is_pdf and b'\x00' not in raw[:4096] and file.filename.lower().endswith('.txt')
    if not (is_pdf or is_txt):raise HTTPException(415,'Only valid PDFs or UTF-8 TXT accepted in this build')
    media='application/pdf' if is_pdf else 'text/plain'
    digest=hashlib.sha256(raw).hexdigest();document_id=str(uuid.uuid4())
    text_output='';status='PARSED';fields={}
    try:
        scan_result=clamav_scan(raw)
    except DocumentSafetyError as exc:
        raise HTTPException(422 if str(exc)=='MALWARE_DETECTED' else 503,str(exc))
    if is_production() and scan_result!='CLEAN':
        raise HTTPException(503,'Production document upload requires functioning malware scanner')
    if is_pdf:
        try:
            extracted=extract_pdf_isolated(raw,ocr_enabled=os.getenv('ENABLE_DOCUMENT_OCR','false').lower()=='true')
        except IsolatedExtractionUnavailable as exc:
            raise HTTPException(503,str(exc)) from None
        text_output=extracted.get('text','');status=extracted['status']
        fields={'signature_check':extracted['signature'],'ocr_status':extracted['ocr'],
                'page_count':extracted.get('page_count')}
        if 'error' in extracted:fields['parse_error']=extracted['error']
    else:
        try:text_output=raw.decode('utf-8')[:40000]
        except UnicodeDecodeError:raise HTTPException(415,'Text file is not UTF-8')
    # Extraction is not issuer verification; no document-derived fields auto-pass policy.
    for line in text_output.splitlines():
        match=re.match(r'^\s*(monthly_income|property_value|reference)\s*:\s*([^\n]{1,60})$',line,re.I)
        if match:fields[match.group(1).lower()]=match.group(2).strip()
    try:
        secured=encrypt_document(raw,a.org_id,a.id,document_id)
    except DocumentKeyUnavailable:
        raise HTTPException(503,'Document encryption key configuration unavailable') from None
    if is_production():
        text_output=''
        fields={k:v for k,v in fields.items() if k in ('signature_check','ocr_status','page_count','parse_error')}
    destination=UPLOADS/storage_filename(document_id,secured.storage_format,media)
    # Restrict local object permissions and atomically publish complete ciphertext.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.upload-',suffix='.tmp',dir=UPLOADS,delete=False) as handle:
            temporary=Path(handle.name)
            if os.name=='posix':os.fchmod(handle.fileno(),0o600)
            handle.write(secured.contents)
            handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,destination)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    bump(db,a,user,'Document uploaded')
    doc=Document(id=document_id,application_id=id,filename=Path(file.filename).name[:255],media_type=media,byte_count=len(raw),sha256=digest,path=str(destination),parse_status=status,extracted_text=text_output,extracted_fields=fields,
                 storage_format=secured.storage_format,storage_sha256=secured.storage_sha256,encryption_key_id=secured.key_id)
    db.add(doc);db.flush()
    if a.workflow!='DRAFT':build_assessment(db,a,user)
    audit(db,id,user,'DOCUMENT_UPLOADED',detail={'document_id':doc.id,'sha256':digest,'parse_status':status})
    db.commit()
    return {'id':doc.id,'status':status,'sha256':digest,'fields':fields,'verified':False,'malware_scan':scan_result,'encrypted_at_rest':secured.storage_format==FORMAT_ENCRYPTED}

@app.get('/api/v1/applications/{id}/documents')
def list_documents(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user);rows=db.scalars(select(Document).where(Document.application_id==id)).all()
    return {'items':[{'id':d.id,'filename':d.filename,'sha256':d.sha256,'byte_count':d.byte_count,'parse_status':d.parse_status,'fields':d.extracted_fields,'verified':False,'encrypted_at_rest':d.storage_format==FORMAT_ENCRYPTED} for d in rows]}

@app.get('/api/v1/applications/{id}/documents/{document_id}/download')
def download_document(id:str,document_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=load_app(db,id,user)
    require(user,{'BORROWER','ANALYST','COMPLIANCE','AUDITOR','ADMIN'})
    doc=db.get(Document,document_id)
    if not doc or doc.application_id!=id:raise HTTPException(404,'Document not found')
    root=UPLOADS.resolve()
    storage_format=doc.storage_format or FORMAT_LEGACY
    try:
        filename=storage_filename(doc.id,storage_format,doc.media_type)
    except DocumentIntegrityError:
        raise HTTPException(409,'Document storage metadata invalid') from None
    recorded=Path(doc.path)
    if recorded.is_absolute():
        # Legacy absolute paths are not portable across drive/restore operations.
        candidate=recorded.resolve()
        stored=candidate if root in candidate.parents and candidate.is_file() else (root/filename).resolve()
    else:
        stored=(root/recorded).resolve()
    if root not in stored.parents:raise HTTPException(409,'Storage path invalid')
    if not stored.is_file():raise HTTPException(404,'Document bytes unavailable')
    try:
        raw=decrypt_document(stored.read_bytes(),storage_format=storage_format,key_id=doc.encryption_key_id,
                             org_id=a.org_id,application_id=id,document_id=doc.id,
                             plaintext_sha256=doc.sha256,stored_sha256=doc.storage_sha256)
        if len(raw)!=doc.byte_count:raise DocumentIntegrityError('Stored document size mismatch')
    except DocumentKeyUnavailable:
        raise HTTPException(503,'Document decryption key unavailable') from None
    except DocumentIntegrityError:
        raise HTTPException(409,'Stored document failed integrity or ownership check') from None
    audit(db,id,user,'DOCUMENT_ACCESSED',detail={'document_id':doc.id})
    db.commit()
    from urllib.parse import quote
    # Body is exactly the authenticated plaintext verified above; no file race after verification.
    return Response(content=raw,media_type=doc.media_type,headers={
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(doc.filename,safe='')})

@app.get('/api/v1/applications/{id}/assessment-diff')
def assessment_diff(id:str,older_id:str|None=None,newer_id:str|None=None,
                    db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user)
    records=db.scalars(select(Assessment).where(Assessment.application_id==id).order_by(Assessment.revision.desc(),Assessment.created_at.desc())).all()
    if len(records)<2:raise HTTPException(409,'Two assessments are needed for comparison')
    lookup={item.id:item for item in records}
    newer=lookup.get(newer_id) if newer_id else records[0]
    older=lookup.get(older_id) if older_id else next((x for x in records if x.id!=newer.id),None)
    if not older or not newer:raise HTTPException(404,'Assessment not found in this application')
    def reason_codes(a):return {r['code']:r['status'] for r in a.result['reasons']}
    before=reason_codes(older);after=reason_codes(newer)
    changes=[{'reason_code':key,'before':before.get(key,'ABSENT'),'after':after.get(key,'ABSENT')} for key in sorted(before.keys()|after.keys()) if before.get(key)!=after.get(key)]
    money=['emi','foir','ltv','accepted_income','accepted_property_value','existing_obligations','monthly_surplus']
    fin_before=older.result.get('financials') or {};fin_after=newer.result.get('financials') or {}
    financial_changes=[{'metric':key,'before':fin_before.get(key),'after':fin_after.get(key)} for key in money if fin_before.get(key)!=fin_after.get(key)]
    out={'older':{'assessment_id':older.id,'revision':older.revision,'outcome':older.outcome,'policy_version':older.result['policy_version']},
         'newer':{'assessment_id':newer.id,'revision':newer.revision,'outcome':newer.outcome,'policy_version':newer.result['policy_version']},
         'outcome_changed':older.outcome!=newer.outcome,'reason_changes':changes,'financial_changes':financial_changes,
         'note':'Comparison of persisted assessments. Earlier records were not modified.'}
    if user.role=='BORROWER':
        # Borrower sees an outcome summary; not internal rule-code/AML investigation details.
        return {k:out[k] for k in ('older','newer','outcome_changed','note')}
    return out

@app.get('/api/v1/applications/{id}/next-evidence')
def next_evidence(id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    load_app(db,id,user)
    assessment=latest_assessment(db,id)
    if not assessment:raise HTTPException(409,'Application has not been assessed')
    targets={'MISSING_CONSENT':('financial_underwriting','Review and grant permission before financial records can be retrieved.'),
             'IDENTITY_UNRESOLVED':('identity','Provide an authorized identity-verification result.'),
             'BANK_INCOME_UNRESOLVED':('bank_income','Obtain authorized bank income records.'),
             'INCOME_SUPPORT_UNRESOLVED':('income_support','Obtain independent income support.'),
             'INCOME_CONTRADICTION':('income_support','Resolve the difference using corrected independent income evidence.'),
             'OWNERSHIP_UNRESOLVED':('ownership','Obtain verified ownership evidence.'),
             'VALUATION_UNRESOLVED':('valuation','Obtain an authorized collateral valuation.'),
             'PROPERTY_CONTRADICTION':('valuation','Reconcile declared value with supported valuation.'),
             'LEGAL_UNRESOLVED':('legal','Obtain professional legal/property review.'),
             'BUREAU_UNRESOLVED':('bureau','Obtain an authorized credit bureau result.'),
             'SCREENING_UNRESOLVED':('screening','Complete authorized screening review.'),
             'SCREENING_POTENTIAL_MATCH':('screening','Escalate the potential match to an authorized reviewer.')}
    result=[];used=set()
    for reason in assessment.result['reasons']:
        if reason['status']!='UNRESOLVED' or reason['code'] not in targets:continue
        key,description=targets[reason['code']]
        if key in used:continue
        used.add(key)
        priority=0 if reason['code']=='MISSING_CONSENT' else (1 if reason['code'].endswith('CONTRADICTION') else 2)
        result.append({'evidence_key':key,'reason_code':reason['code'],'priority':priority,'request':description})
    result.sort(key=lambda x:(x['priority'],x['evidence_key']))
    if user.role=='BORROWER':
        result=[{'evidence_key':r['evidence_key'],'request':r['request']} for r in result if r['evidence_key']!='screening']
    return {'assessment_id':assessment.id,'items':result,'ranking':'Deterministic prerequisites/conflicts first; not a trained information-gain model.'}

@app.get('/api/v1/monitoring/summary')
def monitoring(db:Session=Depends(get_db),user:User=Depends(current_user)):
    require(user,{'ANALYST','COMPLIANCE','POLICY_AUTHOR','POLICY_APPROVER','AUDITOR','ADMIN'})
    apps=db.scalars(select(Application).where(Application.org_id==user.org_id)).all()
    counts={'APPROVE':0,'REJECT':0,'REFER':0};decisions=0
    for a in apps:
        ass=latest_assessment(db,a.id)
        if ass:counts[ass.outcome]+=1;decisions+=1
    return {'applications':len(apps),'assessed':decisions,'current_outcomes':counts,'sample':'SYNTHETIC FIXTURES + LOCAL USER ENTRIES','operational_latency':'NOT_MEASURED','provider_latency':'NO LIVE PROVIDERS'}

@app.get('/api/v1/traceability')
def traceability(user:User=Depends(current_user)):
    data=json.loads((ROOT/'docs'/'traceability.json').read_text())
    return data
