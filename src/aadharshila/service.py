"""Materialize provenance snapshots and persist explainable assessments."""
import os
from datetime import datetime,timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Application, Evidence, Consent, Assessment, Conflict, ReviewTask, AuditEvent, Policy, Job, Document
from .engine import evaluate

def stamp(d): return d.isoformat() if d else None

def audit(db, app_id, actor, action, reason='', detail=None):
    db.add(AuditEvent(application_id=app_id,actor_id=getattr(actor,'id',None),role=getattr(actor,'role','system'),action=action,reason=reason,detail=detail or {}))

def active_policy(db,product):
    policy=db.scalar(select(Policy).where(Policy.product==product,Policy.state=='ACTIVE').order_by(Policy.version.desc()))
    if not policy: raise ValueError('Active policy missing')
    return policy

def collect_snapshot(db,app):
    rows=db.scalars(select(Evidence).where(Evidence.application_id==app.id).order_by(Evidence.revision,Evidence.captured_at,Evidence.id)).all()
    evidence={}
    current=datetime.now(timezone.utc)
    for r in rows:
        expires=r.expires_at
        if expires and expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
        evidence[r.key]={'id':r.id,'key':r.key,'value':r.value,'verification':r.verification,'mode':r.mode,'provider':r.provider,
                        'captured_at':stamp(r.captured_at),'expired':bool(expires and expires<=current),'expires_at':stamp(r.expires_at),'revision':r.revision}
    purposes=[]
    for c in db.scalars(select(Consent).where(Consent.application_id==app.id)).all():
        if c.revoked_at: continue
        expiry=c.expires_at
        if expiry and expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
        if expiry and expiry<=current: continue
        purposes.append(c.purpose)
    fields=['id','reference','product','applicant_type','applicant_name','location','amount','tenure_months','declared_income','existing_obligations','property_value','employment','revision']
    record={k:float(getattr(app,k)) if k in ('amount','declared_income','existing_obligations','property_value') else getattr(app,k) for k in fields}
    documents=db.scalars(select(Document).where(Document.application_id==app.id)).all()
    shared=[]
    for d in documents:
        reuse=db.scalars(select(Document).join(Application,Document.application_id==Application.id).where(Document.sha256==d.sha256,Document.application_id!=app.id,Application.org_id==app.org_id)).all()
        if reuse: shared.append({'hash_prefix':d.sha256[:12],'document_id':d.id,'other_application_count':len({x.application_id for x in reuse})})
    return {'application':record,'evidence':evidence,'consents':purposes,'shared_document_hashes':shared,
            'operating_mode':os.getenv('APP_ENV','development').upper()}

def build_assessment(db:Session,app:Application,actor=None,policy=None):
    policy=policy or active_policy(db,app.product)
    existing=db.scalar(select(Assessment).where(Assessment.application_id==app.id, Assessment.revision==app.revision,Assessment.policy_id==policy.id).order_by(Assessment.created_at.desc()))
    if existing:return existing
    snapshot=collect_snapshot(db,app)
    config={**policy.config,'version':policy.version}
    result=evaluate(snapshot,config)
    snap={'input':snapshot,'policy':config,'model_version':'rule-band-1'}
    assessment=Assessment(application_id=app.id,revision=app.revision,policy_id=policy.id,outcome=result['outcome'],result=result,snapshot=snap)
    db.add(assessment);db.flush()
    for conflict in result['conflicts']:
        db.add(Conflict(assessment_id=assessment.id,code=conflict['code'],detail=conflict))
    # Evidence requests are explicit and can be fulfilled by corrected evidence.
    open_tasks=db.scalars(select(ReviewTask).where(ReviewTask.application_id==app.id,ReviewTask.status=='OPEN')).all()
    current_blockers={r['code'] for r in result['reasons'] if r['status']=='UNRESOLVED'}
    for task in open_tasks:
        if task.reason_code not in current_blockers:
            task.status='RESOLVED'
            task.resolution='Evidence revision cleared this condition; re-evaluated automatically.'
    prior={task.reason_code for task in open_tasks if task.status=='OPEN'}
    for reason in result['reasons']:
        if reason['status']=='UNRESOLVED' and reason['code'] not in prior:
            db.add(ReviewTask(application_id=app.id,assessment_id=assessment.id,reason_code=reason['code'],request_text=reason['explanation']))
    app.workflow='AWAITING_REVIEW' if result['outcome']=='REFER' else 'ASSESSED'
    app.verification='VERIFIED' if result['outcome']=='APPROVE' else 'UNRESOLVED'
    audit(db,app.id,actor,'ASSESSMENT_COMPLETED',detail={'assessment_id':assessment.id,'revision':app.revision,'outcome':result['outcome'],'policy_version':policy.version})
    db.flush()
    return assessment

def bump(db,app,actor,reason,queue=False):
    app.revision+=1
    audit(db,app.id,actor,'EVIDENCE_REVISION',reason=reason,detail={'revision':app.revision})
    if queue and app.workflow!='DRAFT':
        db.add(Job(application_id=app.id,target_revision=app.revision))
        app.workflow='ASSESSING'

def replay(assessment):
    result=evaluate(assessment.snapshot['input'],assessment.snapshot['policy'])
    previous=assessment.result
    fields=['outcome','reasons','rules','financials']
    checks={field:result[field]==previous[field] for field in fields}
    return {'assessment_id':assessment.id,'reproduced':all(checks.values()),'checks':checks,
        'original_outcome':previous['outcome'],'replayed_outcome':result['outcome'],
        'note':'Replay uses frozen inputs and frozen policy without external provider calls.'}
