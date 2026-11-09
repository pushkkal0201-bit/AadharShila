"""Pure underwriting engine: no I/O, mutable globals or LLM decisions.

Policy limits below are *demonstration assumptions*, not Hero Housing rules.
"""
from .finance import D, metrics, alternative, stress

ENGINE_VERSION='deterministic-1'
MANDATORY=['identity','bank_income','income_support','bureau','ownership','legal','valuation','screening']
EXPLANATIONS={
 'MISSING_CONSENT':'Consent is needed before authorized financial evidence can be used.',
 'IDENTITY_UNRESOLVED':'Identity verification has not been completed.',
 'BANK_INCOME_UNRESOLVED':'Verified bank income evidence is missing or stale.',
 'INCOME_SUPPORT_UNRESOLVED':'Independent supporting income evidence is missing or stale.',
 'BUREAU_UNRESOLVED':'A licensed bureau result has not been received.',
 'OWNERSHIP_UNRESOLVED':'Property ownership evidence needs verification.',
 'LEGAL_UNRESOLVED':'Property legal review remains unresolved.',
 'VALUATION_UNRESOLVED':'Property valuation evidence remains unresolved.',
 'SCREENING_UNRESOLVED':'Identity screening is not concluded.',
 'INCOME_CONTRADICTION':'Bank and supporting income evidence disagree beyond the configured tolerance.',
 'PROPERTY_CONTRADICTION':'The declared property value differs materially from accepted valuation evidence.',
 'SCREENING_POTENTIAL_MATCH':'Potential screening match requires an authorized reviewer.',
 'PROVIDER_UNAVAILABLE':'A required evidence provider is unavailable.',
 'FOIR_EXCEEDED':'Monthly debt service exceeds the policy affordability threshold.',
 'LTV_EXCEEDED':'Requested principal exceeds the configured collateral limit.',
 'INCOME_BELOW_MIN':'Verified income is below the demonstration policy minimum.',
 'INVALID_FINANCIALS':'Financial data cannot be assessed safely.',
 'TECHNICAL_FAILURE':'A required dependency failed; automatic approval is blocked.',
 'DOCUMENT_REUSE_REVIEW':'An identical document was found in an unrelated application; authorized review is required.',
 'NONLIVE_EVIDENCE':'A production assessment requires authorized, live, independently verified evidence.',
 'PRODUCTION_AUTHORIZATION_REQUIRED':'A lender-approved policy and authorized production decision scope are not configured.'}

def evaluate(snapshot, policy):
    app=snapshot['application']; ev=snapshot.get('evidence',{}); consents=snapshot.get('consents',[])
    reasons=[]; rules=[]; conflicts=[]
    def check(code,result,category,detail=None):
        rules.append({'code':code,'status':result,'category':category,'detail':detail or EXPLANATIONS.get(code,code)})
        if result!='PASS' and result!='NOT_APPLICABLE': reasons.append({'code':code,'status':result,'explanation':detail or EXPLANATIONS.get(code,code)})
    if app['product']!=policy['product']: raise ValueError('Policy product mismatch')
    production=snapshot.get('operating_mode','DEVELOPMENT').upper()=='PRODUCTION'
    active_consent='financial_underwriting' in consents
    check('MISSING_CONSENT','PASS' if active_consent else 'UNRESOLVED','consent')
    numeric={}
    for key in MANDATORY:
        item=ev.get(key)
        verified=(item is not None and item.get('verification')=='VERIFIED' and not item.get('expired',False)
                  and (not production or (item.get('mode')=='LIVE' and item.get('live_authenticated') is True)))
        if production and item and (item.get('mode')!='LIVE' or item.get('live_authenticated') is not True):
            check('NONLIVE_EVIDENCE','UNRESOLVED','provenance',f'{key} requires an authorized live source')
        numeric[key]=item['value'].get('amount') if verified and isinstance(item.get('value'),dict) else None
        check(key.upper()+'_UNRESOLVED','PASS' if verified else 'UNRESOLVED','evidence')
        if item and item.get('verification')=='FAILED':
            check('TECHNICAL_FAILURE','UNRESOLVED','provider',f'{key} provider returned an unresolved failure')
    if any(x.get('verification')=='FAILED' for x in ev.values()):
        check('PROVIDER_UNAVAILABLE','UNRESOLVED','provider')
    if snapshot.get('shared_document_hashes'):
        conflicts.append({'code':'DOCUMENT_REUSE_REVIEW','severity':'BLOCKING','sources':['stored_document_hash'],
            'matches':snapshot['shared_document_hashes']})
        check('DOCUMENT_REUSE_REVIEW','UNRESOLVED','fraud')
    for key in ('screening',):
        item=ev.get(key)
        if item and item.get('value',{}).get('potential_match'):
            check('SCREENING_POTENTIAL_MATCH','UNRESOLVED','screening')
    if ev.get('bank_income') and ev.get('income_support') and numeric.get('bank_income') is not None and numeric.get('income_support') is not None:
        b,s=D(numeric['bank_income']),D(numeric['income_support'])
        if b>0 and abs(b-s)/max(b,s)>D(policy['income_tolerance']):
            conflicts.append({'code':'INCOME_CONTRADICTION','bank_income':float(b),'supporting_income':float(s),'severity':'BLOCKING','sources':['bank_income','income_support']})
            check('INCOME_CONTRADICTION','UNRESOLVED','conflict')
    accepted_income=D(numeric['bank_income']) if numeric.get('bank_income') is not None else D(0)
    # No optimistic income selection: any mismatch blocks approval.
    if accepted_income<0: accepted_income=D(0)
    property_value=D(numeric['valuation']) if numeric.get('valuation') is not None else D(0)
    if property_value and app['property_value']:
        declared=D(app['property_value'])
        if abs(declared-property_value)/max(declared,property_value)>D(policy['property_tolerance']):
            conflicts.append({'code':'PROPERTY_CONTRADICTION','declared':float(declared),'accepted':float(property_value),'severity':'BLOCKING','sources':['borrower','valuation']})
            check('PROPERTY_CONTRADICTION','UNRESOLVED','conflict')
    obligations=D(app['existing_obligations'])
    if ev.get('obligations') and ev['obligations'].get('verification')=='VERIFIED' and not ev['obligations'].get('expired',False):
        obligations=max(obligations,D(ev['obligations']['value'].get('amount',0)))
    try:
        fin=metrics(app['amount'],policy['annual_rate_percent'],app['tenure_months'],accepted_income,obligations,property_value)
    except (ValueError,ArithmeticError,OverflowError) as exc:
        fin=None
        check('INVALID_FINANCIALS','UNRESOLVED','financial',f'Invalid financial inputs: {type(exc).__name__}')
    if fin:
        if accepted_income>0:
            check('INCOME_BELOW_MIN','FAIL' if accepted_income<D(policy['min_income']) else 'PASS','policy')
        else:
            check('INCOME_BELOW_MIN','UNRESOLVED','policy')
        check('FOIR_EXCEEDED','FAIL' if fin['foir'] is not None and fin['foir']>policy['max_foir'] else ('UNRESOLVED' if fin['foir'] is None else 'PASS'),'policy')
        check('LTV_EXCEEDED','FAIL' if fin['ltv'] is not None and fin['ltv']>policy['max_ltv'] else ('UNRESOLVED' if fin['ltv'] is None else 'PASS'),'policy')
        if app['tenure_months']>policy['max_tenure_months']:
            check('TENURE_EXCEEDED','FAIL','policy','Tenure exceeds configured policy maximum.')
        offer=alternative(app['amount'],policy['annual_rate_percent'],app['tenure_months'],accepted_income,obligations,property_value,policy['max_foir'],policy['max_ltv'],policy['max_tenure_months'])
        stresses=stress(app['amount'],policy['annual_rate_percent'],app['tenure_months'],accepted_income,obligations,property_value,policy) if accepted_income>0 and property_value>0 else []
    else: offer=None; stresses=[]
    # Confirmed terminal policy failures take precedence over unrelated missing evidence.
    # No code path silently authorizes actual lender decisions. External policy approval,
    # risk validation and legal sign-off are not delivered with this repository.
    signed_authorization=(snapshot.get('production_authorization') or {}).get('valid') is True
    if production and not signed_authorization:
        check('PRODUCTION_AUTHORIZATION_REQUIRED','UNRESOLVED','governance')
    outcome=('REFER' if production and not signed_authorization else
             ('REJECT' if any(r['status']=='FAIL' for r in rules) else
              ('REFER' if any(r['status']=='UNRESOLVED' for r in rules) else 'APPROVE')))
    score=None
    if fin and fin['foir'] is not None and fin['ltv'] is not None:
        score={"type":"ILLUSTRATIVE_RULE_BASED_RISK_BANDS","band":('HIGH' if fin['foir']>0.48 or fin['ltv']>0.85 else ('MODERATE' if fin['foir']>0.35 or fin['ltv']>0.65 else 'LOW')),
               "disclaimer":"Demonstration scorecard only; not a trained probability of default."}
    return {'outcome':outcome,'reasons':reasons,'rules':rules,'conflicts':conflicts,'financials':fin,
            'alternative':offer,'stress':stresses,'risk':score,'policy_version':policy['version'],
            'engine_version':ENGINE_VERSION,'evidence_revision':app['revision'],
            'capability_mode':'CONTROLLED_LIVE_CANDIDATE' if production and signed_authorization else 'SIMULATED/LOCAL',
            'note':'Policy assessment only; no executed sanction or disbursement. Independent legal and lender approval is required.'}
