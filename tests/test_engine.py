from copy import deepcopy
from aadharshila.engine import evaluate
POLICY={'product':'HOME_LOAN','version':1,'annual_rate_percent':8.5,'max_foir':.5,'max_ltv':.8,'min_income':20000,'max_tenure_months':360,'income_tolerance':.15,'property_tolerance':.20}
def base():
    return {'application':{'product':'HOME_LOAN','amount':1500000,'tenure_months':240,'declared_income':100000,'existing_obligations':10000,'property_value':3500000,'revision':1},
            'consents':['financial_underwriting'],
            'evidence':{k:{'verification':'VERIFIED','value':v,'expired':False} for k,v in {
                'identity':{},'bank_income':{'amount':100000},'income_support':{'amount':99000},'bureau':{},'ownership':{},'legal':{},'valuation':{'amount':3500000},'screening':{}}.items()}}

def test_clean_application_approved():
    out=evaluate(base(),POLICY)
    assert out['outcome']=='APPROVE'
    assert not out['reasons']
    assert out['risk']['type']=='ILLUSTRATIVE_RULE_BASED_RISK_BANDS'

def test_missing_kcy_refers():
    s=base();s['evidence'].pop('identity')
    out=evaluate(s,POLICY)
    assert out['outcome']=='REFER'
    assert any(r['code']=='IDENTITY_UNRESOLVED' for r in out['reasons'])

def test_bank_slip_contradiction_refers():
    s=base();s['evidence']['income_support']['value']['amount']=40000
    out=evaluate(s,POLICY)
    assert out['outcome']=='REFER'
    assert out['conflicts'][0]['code']=='INCOME_CONTRADICTION'

def test_mandatory_foir_failure_precedence_over_missing_docs():
    s=base();s['application']['amount']=5000000;s['evidence'].pop('identity')
    out=evaluate(s,POLICY)
    assert out['outcome']=='REJECT'
    assert 'FOIR_EXCEEDED' in [r['code'] for r in out['reasons']]

def test_potential_screening_match_not_direct_rejection():
    s=base();s['evidence']['screening']['value']['potential_match']=True
    assert evaluate(s,POLICY)['outcome']=='REFER'

def test_expired_income_refers():
    s=base();s['evidence']['bank_income']['expired']=True
    assert evaluate(s,POLICY)['outcome']=='REFER'

def test_no_permission_refers():
    s=base();s['consents']=[]
    assert 'MISSING_CONSENT' in [r['code'] for r in evaluate(s,POLICY)['reasons']]

def test_self_reported_never_autoverified():
    s=base();s['evidence']['bank_income']={'verification':'UNRESOLVED','value':{'amount':100000},'mode':'SELF_REPORTED'}
    assert evaluate(s,POLICY)['outcome']=='REFER'

def test_tiny_foir_breach_does_not_round_to_approval():
    case=base()
    case['application'].update(amount='100000.01',tenure_months=1,existing_obligations=0)
    case['evidence']['bank_income']['value']['amount']=200000
    case['evidence']['income_support']['value']['amount']=200000
    policy={**POLICY,'annual_rate_percent':0}
    result=evaluate(case,policy)
    assert result['financials']['foir']==0.5  # UI rounds to four places
    assert result['outcome']=='REJECT'
    assert any(r['code']=='FOIR_EXCEEDED' and r['status']=='FAIL' for r in result['reasons'])


def test_tiny_ltv_breach_does_not_round_to_approval():
    case=base()
    case['application'].update(amount='160000.01',property_value=200000)
    case['evidence']['valuation']['value']['amount']=200000
    result=evaluate(case,POLICY)
    assert result['financials']['ltv']==0.8
    assert result['outcome']=='REJECT'
    assert any(r['code']=='LTV_EXCEEDED' and r['status']=='FAIL' for r in result['reasons'])


def test_negative_obligations_fail_closed():
    case=base()
    case['application']['existing_obligations']=-1
    result=evaluate(case,POLICY)
    assert result['outcome']=='REFER'
    assert any(r['code']=='INVALID_FINANCIALS' for r in result['reasons'])


def test_production_untrusted_optional_obligations_require_review():
    case=base()
    case['operating_mode']='PRODUCTION'
    case['production_authorization']={'valid':True}
    for value in case['evidence'].values():
        value.update(mode='LIVE',live_authenticated=True)
    case['evidence']['obligations']={'verification':'VERIFIED',
          'value':{'amount':2000},'expired':False,'mode':'SIMULATED'}
    result=evaluate(case,POLICY)
    assert result['outcome']=='REFER'
    assert any(r['code']=='NONLIVE_EVIDENCE' and 'obligations' in r['explanation']
               for r in result['reasons'])
