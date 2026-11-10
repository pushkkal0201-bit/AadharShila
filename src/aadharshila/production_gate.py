"""Verify institution-supplied production release attestations.

Cryptographic verification is not proof of lender licensing or actual professional
sign-off. Institution-managed public-key trust anchors are required.
"""
from __future__ import annotations
from .runtime import is_production
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REQUIREMENTS = {
    'lender_adopted_policy':'CREDIT_AUTHORITY',
    'regulated_provider_access':'PROVIDER_AUTHORITY',
    'independent_security_review':'INDEPENDENT_SECURITY',
    'credit_risk_validation':'INDEPENDENT_MODEL_RISK',
    'legal_regulatory_signoff':'LEGAL_COMPLIANCE',
    'production_disaster_recovery':'OPERATIONS_OWNER',
}
MAX_BUNDLE_BYTES=250_000
MAX_ATTESTATION_AGE_DAYS=366

def canonical(value:dict[str,Any])->bytes:
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def policy_fingerprint(policy:dict)->str:
    return hashlib.sha256(canonical(policy)).hexdigest()

def _utc(iso:str)->datetime:
    value=datetime.fromisoformat(iso.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Naive date/time')
    return value.astimezone(timezone.utc)

def evaluate_bundle(bundle:dict,trust_store:dict,*,organization_id:str,product:str,policy:dict,at:datetime|None=None)->dict:
    now=(at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    statuses={name:'NOT_ATTESTED' for name in REQUIREMENTS}
    issues=[]
    used_issuers=set();used_pubkeys=set()
    expected_hash=policy_fingerprint(policy)
    failed={'valid':False,'requirements':statuses,'issues':['INVALID_CONFIGURATION'],'policy_sha256':expected_hash}
    if not isinstance(bundle,dict) or not isinstance(trust_store,dict):return failed
    anchors=trust_store.get('issuers',[])
    if not isinstance(anchors,list) or not isinstance(bundle.get('attestations'),list):return failed
    by_id={i.get('issuer_id'):i for i in anchors if isinstance(i,dict) and i.get('issuer_id')}
    for record in bundle['attestations']:
        if not isinstance(record,dict) or not isinstance(record.get('claim'),dict):
            issues.append('INVALID_ATTESTATION');continue
        claim=record['claim']
        requirement=claim.get('requirement')
        if requirement not in REQUIREMENTS:
            issues.append('UNKNOWN_REQUIREMENT');continue
        if statuses[requirement]=='VERIFIED_SIGNATURE':
            issues.append('DUPLICATE_REQUIREMENT');statuses[requirement]='DUPLICATE';continue
        issuer_id=claim.get('issuer_id');anchor=by_id.get(issuer_id)
        if not anchor or anchor.get('role')!=REQUIREMENTS[requirement]:
            statuses[requirement]='UNTRUSTED_ISSUER';continue
        pubkey_b64=anchor.get('public_key_base64','')
        if issuer_id in used_issuers or pubkey_b64 in used_pubkeys:
            statuses[requirement]='SIGNER_NOT_INDEPENDENT';continue
        if (claim.get('organization_id')!=organization_id or claim.get('product')!=product or
            claim.get('policy_sha256')!=expected_hash or claim.get('environment')!='production' or
            claim.get('scope')!='automated_mortgage_underwriting'):
            statuses[requirement]='SCOPE_MISMATCH';continue
        try:
            effective,expires=_utc(claim['valid_from']),_utc(claim['valid_until'])
            if not (effective<=now<expires) or not 0<(expires-effective).days<=MAX_ATTESTATION_AGE_DAYS:
                statuses[requirement]='EXPIRED_OR_NOT_EFFECTIVE';continue
            public_key=Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64,validate=True))
            sig=base64.b64decode(record.get('signature_base64',''),validate=True)
            public_key.verify(sig,canonical(claim))
        except (KeyError,ValueError,TypeError,InvalidSignature,OverflowError):
            statuses[requirement]='INVALID_SIGNATURE_OR_PERIOD';continue
        statuses[requirement]='VERIFIED_SIGNATURE'
        used_issuers.add(issuer_id);used_pubkeys.add(pubkey_b64)
    valid=all(v=='VERIFIED_SIGNATURE' for v in statuses.values()) and not issues
    return {'valid':valid,'requirements':statuses,'issues':issues,'policy_sha256':expected_hash,
            'meaning':'Signature and scope verified, not independent confirmation of licensing or professional competence.'}

def evaluate_configured(*,organization_id:str,product:str,policy:dict)->dict:
    empty={'valid':False,'requirements':{name:'NOT_ATTESTED' for name in REQUIREMENTS},
           'issues':[],'policy_sha256':policy_fingerprint(policy)}
    if not is_production():
        return {**empty,'issues':['DEVELOPMENT_MODE']}
    bundle_file=os.getenv('AADHARSHILA_RELEASE_BUNDLE','')
    trust_file=os.getenv('AADHARSHILA_TRUST_STORE','')
    if not bundle_file or not trust_file:return {**empty,'issues':['RELEASE_BUNDLE_OR_TRUST_STORE_MISSING']}
    try:
        def load(path):
            p=Path(path)
            if not p.is_file() or p.stat().st_size>MAX_BUNDLE_BYTES:raise ValueError('missing or oversized')
            return json.loads(p.read_text(encoding='utf-8'))
        bundle,trust=load(bundle_file),load(trust_file)
        return evaluate_bundle(bundle,trust,organization_id=organization_id,product=product,policy=policy)
    except (OSError,ValueError,TypeError,UnicodeError) as exc:
        return {**empty,'issues':['RELEASE_BUNDLE_INVALID:'+type(exc).__name__]}

def main()->int:
    import argparse
    parser=argparse.ArgumentParser(description='Verify external release signatures; this is not legal certification')
    parser.add_argument('--organization-id',required=True)
    parser.add_argument('--product',choices=['HOME_LOAN','LAP'],required=True)
    parser.add_argument('--policy-json',type=Path,required=True)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--trust-store',type=Path,required=True)
    args=parser.parse_args()
    try:
        policy=json.loads(args.policy_json.read_text(encoding='utf-8'))
        bundle=json.loads(args.bundle.read_text(encoding='utf-8'))
        trust=json.loads(args.trust_store.read_text(encoding='utf-8'))
        report=evaluate_bundle(bundle,trust,organization_id=args.organization_id,
                               product=args.product,policy=policy)
    except (OSError,ValueError,UnicodeError) as error:
        report={'valid':False,'issues':[type(error).__name__],'requirements':{}}
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if report['valid'] else 2

if __name__=='__main__':
    raise SystemExit(main())
