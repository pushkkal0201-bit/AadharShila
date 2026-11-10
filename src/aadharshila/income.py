"""Conservative transaction normalization for mortgage underwriting.

This module produces a REVIEWABLE estimate, never a certified income assertion.
Only transactions already authenticated through a separate source process should
be treated as verified inputs. Values are INR and Decimal throughout.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any
from pydantic import BaseModel, Field, field_validator
from .finance import D, cash

CATEGORIES = {'SALARY','BUSINESS_RECEIPT','OWN_TRANSFER','LOAN_PROCEEDS','REFUND',
              'REIMBURSEMENT','CASH_DEPOSIT','EMI','OTHER_OBLIGATION','OTHER','UNCERTAIN'}
EXCLUDED_CREDITS = {'OWN_TRANSFER','LOAN_PROCEEDS','REFUND','REIMBURSEMENT','CASH_DEPOSIT','OTHER','UNCERTAIN'}

class Transaction(BaseModel):
    transaction_id: str = Field(min_length=1,max_length=100)
    account_id: str = Field(min_length=1,max_length=100)
    posting_date: date
    amount: Decimal = Field(gt=0,le=Decimal('100000000000'))
    direction: str
    category: str
    reference: str = Field(default='',max_length=140)
    counterparty_id: str = Field(default='',max_length=140)
    verified: bool = False

    @field_validator('direction')
    @classmethod
    def direction_valid(cls,v):
        if v not in ('CREDIT','DEBIT'): raise ValueError('Unsupported transaction direction')
        return v

    @field_validator('category')
    @classmethod
    def category_valid(cls,v):
        if v not in CATEGORIES: raise ValueError('Unsupported transaction category')
        return v

class TransactionBatch(BaseModel):
    transactions: list[Transaction] = Field(min_length=1,max_length=5000)
    applicant_type: str
    as_of: date
    @field_validator('applicant_type')
    @classmethod
    def applicant_type_valid(cls,v):
        if v not in ('SALARIED','SELF_EMPLOYED'): raise ValueError('Unsupported applicant type')
        return v


def reconcile(batch: TransactionBatch) -> dict[str, Any]:
    """Normalize source-tagged transactions; ambiguous inputs stay unresolved.

    All paid months in the 6 full calendar months preceding as_of are evaluated.
    Zero-value months are included to avoid selection bias. The method requires
    >=3 distinct paid months; it does not establish issuer authenticity or PD.
    """
    today=batch.as_of
    year,month=today.year,today.month
    months=[]
    for _ in range(6):
        month-=1
        if month==0: month=12;year-=1
        months.append(f'{year:04d}-{month:02d}')
    month_set=set(months)
    income_type='SALARY' if batch.applicant_type=='SALARIED' else 'BUSINESS_RECEIPT'
    sources=defaultdict(set)
    receipts=defaultdict(lambda:Decimal(0))
    paid_months=set(); obligation=defaultdict(lambda:Decimal(0))
    seen_ids=set(); obligation_keys=set()
    excluded=defaultdict(lambda:Decimal(0)); findings=[]
    verified_count=0; unverified_count=0; out_of_window=0
    for tx in batch.transactions:
        key=(tx.account_id,tx.transaction_id)
        if key in seen_ids:
            findings.append('DUPLICATE_TRANSACTION_ID'); continue
        seen_ids.add(key)
        if not tx.verified:
            unverified_count+=1; continue
        verified_count+=1
        ym=tx.posting_date.strftime('%Y-%m')
        if ym not in month_set:
            out_of_window+=1; continue
        amount=D(tx.amount)
        if tx.direction=='CREDIT':
            if tx.category==income_type:
                receipts[ym]+=amount
                paid_months.add(ym)
                sources[ym].add(tx.counterparty_id)
            else:
                excluded[tx.category]+=amount
        elif tx.category in ('EMI','OTHER_OBLIGATION'):
            # Deduplicate cross-account reporting of the same contractual debit.
            # Distinct reference-less debits remain distinct, avoiding undercount.
            identity=(ym,tx.category,tx.counterparty_id,tx.reference) if tx.reference else (tx.account_id,tx.transaction_id)
            if identity in obligation_keys:
                findings.append('DUPLICATE_OBLIGATION');continue
            obligation_keys.add(identity)
            obligation[ym]+=amount
    values=[receipts[m] for m in months]
    months_with_income=sum(v>0 for v in values)
    credible=months_with_income>=3 and unverified_count==0
    # Income baseline is conservative and transparent; no applicant-income
    # uplift from incomplete supporting months or exceptional inflows.
    mean=sum(values)/D(6)
    accepted=cash(min(D(median(values)),mean)) if credible else D(0)
    ob=max(obligation.values(),default=D(0))
    if months_with_income<3: findings.append('INSUFFICIENT_INCOME_COVERAGE')
    if unverified_count: findings.append('UNVERIFIED_TRANSACTIONS_EXCLUDED')
    if batch.applicant_type=='SALARIED' and len({p for s in sources.values() for p in s if p})>1:
        findings.append('MULTIPLE_SALARY_COUNTERPARTIES_REVIEW')
    if len(seen_ids)<len(batch.transactions): findings.append('DUPLICATE_IDS_EXCLUDED')
    return {'status':'REVIEW_REQUIRED' if findings or not credible else 'CALCULATED',
            'verified_records':verified_count,'unverified_records':unverified_count,
            'out_of_window':out_of_window,'covered_months':sorted(paid_months),
            'monthly_receipts':{m:float(cash(receipts[m])) for m in reversed(months)},
            'excluded_credits':{k:float(cash(v)) for k,v in sorted(excluded.items())},
            'accepted_monthly_income':float(accepted),
            'observed_monthly_obligations':float(cash(ob)),
            'findings':sorted(set(findings)),
            'basis':'Median capped at six-month average; only independently verified, categorized inflows',
            'not_a_loan_decision':True}
