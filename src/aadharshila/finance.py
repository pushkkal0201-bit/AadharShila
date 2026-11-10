"""Exact-decimal, deterministic loan calculations (demonstration policy context)."""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

Q = Decimal('0.01')
def D(v):
    try:
        d=Decimal(str(v))
        if not d.is_finite(): raise ValueError('Non-finite amount')
        return d
    except (InvalidOperation, TypeError): raise ValueError('Invalid numeric value')
def cash(v): return D(v).quantize(Q,rounding=ROUND_HALF_UP)
def emi(principal, annual_rate_percent, months):
    p,r,n=D(principal),D(annual_rate_percent),int(months)
    if p<0 or r<0 or n<=0 or n>600 or p>Decimal('1e13'): raise ValueError('Loan terms out of permitted bounds')
    if p==0: return Decimal(0)
    m=r/Decimal(1200)
    if not m: return cash(p/D(n))
    z=(Decimal(1)+m)**n
    return cash(p*m*z/(z-1))
def principal_for_emi(monthly_emi,annual_rate_percent,months):
    cap,r,n=D(monthly_emi),D(annual_rate_percent),int(months)
    if n<=0 or n>600 or r<0: raise ValueError('Invalid loan terms')
    if cap<=0: return Decimal(0)
    m=r/Decimal(1200)
    if not m: return cash(cap*n)
    z=(Decimal(1)+m)**n
    return cash(cap*(z-1)/(m*z))
def metrics(principal,annual_rate_percent,months,monthly_income,existing_obligations,property_value):
    p, inc,ob,collateral=D(principal),D(monthly_income),D(existing_obligations),D(property_value)
    if any(value < 0 for value in (p, inc, ob, collateral)):
        raise ValueError('Financial amounts and obligations must be nonnegative')
    payment=emi(p,annual_rate_percent,months)
    total=payment*D(months)
    return {
        'emi':float(payment), 'foir':float(((payment+ob)/inc).quantize(Decimal('0.0001'))) if inc>0 else None,
        'ltv':float((p/collateral).quantize(Decimal('0.0001'))) if collateral>0 else None,
        'monthly_surplus':float(cash(inc-ob-payment)), 'total_repayment':float(cash(total)),
        'total_interest':float(cash(total-p)), 'accepted_income':float(cash(inc)),
        'existing_obligations':float(cash(ob)), 'accepted_property_value':float(cash(collateral))
    }

def alternative(principal,rate,tenure,income,obligations,property_value,max_foir,max_ltv,max_tenure):
    if D(income)<=0 or D(property_value)<=0: return None
    t=min(int(tenure),int(max_tenure))
    cap=max(Decimal(0),D(income)*D(max_foir)-D(obligations))
    eligible=min(D(principal),principal_for_emi(cap,rate,t),D(property_value)*D(max_ltv))
    if eligible<=0: return None
    eligible=cash(eligible)
    return {'principal':float(eligible),'tenure_months':t,'rate_percent':float(D(rate)),
        **metrics(eligible,rate,t,income,obligations,property_value),
        'disclaimer':'Illustrative terms only. This is not an approved offer.'}

def stress(principal,rate,tenure,income,obligations,property_value,policy):
    scenarios={'Baseline':(D(income),D(rate),D(property_value)),
      'Income -20%':(D(income)*D('0.80'),D(rate),D(property_value)),
      'Rate +2 percentage points':(D(income),D(rate)+D(2),D(property_value)),
      'Income -20% and rate +2 pp':(D(income)*D('0.80'),D(rate)+D(2),D(property_value)),
      'Collateral -15%':(D(income),D(rate),D(property_value)*D('0.85'))}
    out=[]
    for name,(i,r,v) in scenarios.items():
        m=metrics(principal,r,tenure,i,obligations,v)
        # Compare the unrounded ratios. Display rounding must never change a policy result.
        outcome=('PASS' if i>0 and v>0 and
                 D(m['emi'])+D(obligations)<=i*D(policy['max_foir']) and
                 D(principal)<=v*D(policy['max_ltv']) else 'FAIL')
        out.append({'scenario':name,**m,'policy_result':outcome})
    return out
