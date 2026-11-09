"""Binding a verified partner response to the exact evidence payload."""
import hashlib
import json
from aadharshila.db import SessionLocal
from aadharshila.models import Application, Evidence, ProviderInvocation
from aadharshila.service import collect_snapshot


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def test_partner_provenance_fails_closed_if_evidence_is_changed(cases):
    case_id=cases['AS-1001']['id']
    with SessionLocal() as db:
        application=db.get(Application,case_id)
        original={'amount':81000,'currency':'INR'}
        invocation=ProviderInvocation(application_id=case_id,evidence_key='bank_income',
            provider_name='signed-partner',mode='LIVE',status='SUCCESS',
            response_metadata={'signature_validated':True,'verification':'VERIFIED',
                               'payload_sha256':digest(original)})
        db.add(invocation)
        db.flush()
        evidence=Evidence(application_id=case_id,key='bank_income',value=original,
            provider='signed-partner',mode='LIVE',verification='VERIFIED',
            revision=application.revision+1,provider_invocation_id=invocation.id)
        db.add(evidence)
        db.flush()
        assert collect_snapshot(db,application)['evidence']['bank_income']['live_authenticated'] is True
        evidence.value={'amount':300000,'currency':'INR'}
        db.flush()
        assert collect_snapshot(db,application)['evidence']['bank_income']['live_authenticated'] is False
        evidence.value=original
        invocation.response_metadata={'signature_validated':True,'verification':'VERIFIED'}
        db.flush()
        assert collect_snapshot(db,application)['evidence']['bank_income']['live_authenticated'] is False
        db.rollback()
