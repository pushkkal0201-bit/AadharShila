import pytest
from decimal import Decimal
from aadharshila.finance import emi, metrics,principal_for_emi,alternative,stress

def test_zero_rate_and_exact_precision():
    assert emi('120000',0,12)==Decimal('10000.00')
    assert emi(0,9,12)==0
    assert emi('100000',12,12)==Decimal('8884.88')

def test_invalid_terms():
    for args in [(-1,8,120),(100,8,0),(100,-4,12),(10,1,601)]:
        with pytest.raises(ValueError):emi(*args)

def test_foir_and_ltv_math():
    m=metrics(100000,0,10,50000,10000,200000)
    assert m['emi']==10000
    assert m['foir']==.4
    assert m['ltv']==.5
    assert m['total_interest']==0
    assert m['monthly_surplus']==30000

def test_zero_income_not_false_pass():
    m=metrics(100000,0,10,0,1000,200000)
    assert m['foir'] is None

def test_reverse_emi_matches_forward():
    p=principal_for_emi(30000,8.5,240)
    assert emi(p,8.5,240)<=Decimal('30000.01')

def test_alternative_respects_foir_and_ltv():
    x=alternative(5000000,8.5,240,90000,20000,5000000,.45,.65,360)
    assert x['principal']<=3250000
    assert x['foir']<=.4501 and x['ltv']<=.65
    assert x['disclaimer'].startswith('Illustrative')

def test_stress_never_claims_forecast():
    m=stress(100000,8.5,240,80000,10000,500000,{'max_foir':.5,'max_ltv':.65})
    assert len(m)==5
    assert m[1]['foir']>m[0]['foir']
    assert m[2]['emi']>m[0]['emi']
