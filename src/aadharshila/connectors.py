"""Typed, consent-gated evidence adapters: local fixture or explicit unavailability.

No live provider contract or authentication exists in this demonstrator.
"""
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Protocol
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Evidence,Application,Consent,ProviderInvocation
from .service import bump,build_assessment,audit

@dataclass(frozen=True)
class ConnectorResult:
    mode:str
    status:str
    verification:str
    provider:str
    value:dict
    error_category:str|None=None

class Connector(Protocol):
    mode:str
    def fetch(self,db:Session,application:Application,key:str)->ConnectorResult: ...

class DeterministicFixtureConnector:
    mode='SIMULATED'
    def fetch(self,db:Session,application:Application,key:str)->ConnectorResult:
        original=db.scalar(select(Evidence).where(Evidence.application_id==application.id,
                 Evidence.key==key,Evidence.provider=='synthetic-fixture-v1',Evidence.mode=='SIMULATED')
                 .order_by(Evidence.captured_at.desc(),Evidence.revision.desc()))
        if original is None:
            return ConnectorResult(mode='UNAVAILABLE',status='UNRESOLVED',verification='FAILED',provider='unconfigured-provider',
                value={'error':'NO_AUTHORIZED_FIXTURE'},error_category='PROVIDER_NOT_CONFIGURED')
        if original.verification=='FAILED':
            return ConnectorResult(mode='SIMULATED',status='UNRESOLVED',verification='FAILED',provider='synthetic-fixture-v1',
                value={'error':'UPSTREAM_UNAVAILABLE'},error_category='SIMULATED_PROVIDER_FAILURE')
        return ConnectorResult(mode='SIMULATED',status='SUCCESS',verification=original.verification,provider='synthetic-fixture-v1',value=original.value)

REQUIRED_PURPOSE='financial_underwriting'
SUPPORTED_KEYS={'identity','bank_income','income_support','bureau','ownership','legal','valuation','screening'}

def consent_authorized(db,app):
    now=datetime.now(timezone.utc)
    for c in db.scalars(select(Consent).where(Consent.application_id==app.id,Consent.purpose==REQUIRED_PURPOSE,Consent.revoked_at==None)):
        expiry=c.expires_at
        if expiry and expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
        if not expiry or expiry>now:return True
    return False

def fetch_and_record(db,app,key,actor):
    """Fetch through the fixture adapter. Never treat an outage as verification."""
    if key not in SUPPORTED_KEYS:raise ValueError('Unsupported provider operation')
    if not consent_authorized(db,app):raise PermissionError('Borrower consent for financial underwriting is not active')
    adapter=DeterministicFixtureConnector()
    reply=adapter.fetch(db,app,key)
    invocation=ProviderInvocation(application_id=app.id,evidence_key=key,provider_name=reply.provider,mode=reply.mode,
        status=reply.status,error_category=reply.error_category,
        response_metadata={'verification':reply.verification,'typed_error':reply.error_category,'live':False},
        completed_at=datetime.now(timezone.utc))
    db.add(invocation)
    bump(db,app,actor,'Provider refresh: '+key)
    ev=Evidence(application_id=app.id,key=key,value=reply.value,provider=reply.provider,mode=reply.mode,
      verification=reply.verification,revision=app.revision)
    db.add(ev);db.flush()
    assessment=build_assessment(db,app,actor) if app.workflow!='DRAFT' else None
    audit(db,app.id,actor,'CONNECTOR_INVOKED',detail={'request_id':invocation.request_id,'provider':reply.provider,
        'mode':reply.mode,'status':reply.status,'error_category':reply.error_category})
    db.flush()
    return {'invocation_id':invocation.id,'request_id':invocation.request_id,'mode':reply.mode,'status':reply.status,
        'verification':reply.verification,'error_category':reply.error_category,'assessment_id':assessment.id if assessment else None,
        'message':'Local deterministic fixture. No real provider contacted.'}
