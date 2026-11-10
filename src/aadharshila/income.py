"""Conservative transaction normalization for mortgage underwriting.

This module produces a REVIEWABLE estimate, never a certified income assertion.
Only transactions already authenticated through a separate source process should
be treated as verified inputs. Values are INR and Decimal throughout.
"""
from __future__ import annotations
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median, pstdev
from typing import Any
from pydantic import BaseModel, Field, field_validator
from .finance import D, cash

CATEGORIES = {'SALARY','BUSINESS_RECEIPT','OWN_TRANSFER','LOAN_PROCEEDS','REFUND',
              'REIMBURSEMENT','CASH_DEPOSIT','EMI','OTHER_OBLIGATION','OTHER','UNCERTAIN','REVERSAL'}
EXCLUDED_CREDITS = {'OWN_TRANSFER','LOAN_PROCEEDS','REFUND','REIMBURSEMENT','CASH_DEPOSIT','OTHER','UNCERTAIN','REVERSAL'}

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
    statement_months: list[str] | None = None  # Explicitly reported coverage from an authenticated source
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
    seen_ids=set(); obligation_keys=set(); receipt_keys=set()
    owned_accounts={row.account_id for row in batch.transactions}
    reversals=defaultdict(lambda:Decimal(0)); credited_references={}; suspected_self_transfers=0
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
            if tx.category==income_type and tx.counterparty_id and tx.counterparty_id in owned_accounts:
                # An account-to-account credit cannot establish new earnings.
                suspected_self_transfers+=1
                excluded['OWN_TRANSFER']+=amount
                findings.append('INCOME_LABEL_CONFLICTS_WITH_OWN_ACCOUNT')
            elif tx.category==income_type:
                # Cross-account duplicate statements may reflect the same receipt.
                # Require a substantial exact reference; do not merge unrelated pays.
                receipt_key=(ym,tx.reference,tx.counterparty_id,amount) if len(tx.reference)>=8 else (tx.account_id,tx.transaction_id)
                if receipt_key in receipt_keys:
                    findings.append('DUPLICATE_INCOME_RECEIPT')
                    continue
                receipt_keys.add(receipt_key)
                receipts[ym]+=amount
                paid_months.add(ym)
                sources[ym].add(tx.counterparty_id)
                if tx.reference:credited_references[(ym,tx.reference,tx.counterparty_id)]=amount
            else:
                excluded[tx.category]+=amount
        elif tx.category=='REVERSAL' and tx.reference:
            reversals[(ym,tx.reference,tx.counterparty_id)]+=amount
        elif tx.category in ('EMI','OTHER_OBLIGATION'):
            # Deduplicate cross-account reporting of the same contractual debit.
            # Distinct reference-less debits remain distinct, avoiding undercount.
            identity=(ym,tx.category,tx.counterparty_id,tx.reference) if tx.reference else (tx.account_id,tx.transaction_id)
            if identity in obligation_keys:
                findings.append('DUPLICATE_OBLIGATION');continue
            obligation_keys.add(identity)
            obligation[ym]+=amount
    for (ym,ref,payee),amount in reversals.items():
        original=credited_references.get((ym,ref,payee))
        if original is not None:
            receipts[ym]-=min(original,amount)
            findings.append('REVERSED_INCOME_RECEIPT')
    values=[max(D(0),receipts[m]) for m in months]
    disclosed_coverage=None
    if batch.statement_months is not None:
        if len(set(batch.statement_months))!=len(batch.statement_months) or any(not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])',m) for m in batch.statement_months):
            findings.append('INVALID_STATEMENT_COVERAGE')
        disclosed_coverage=sorted(set(batch.statement_months)&month_set)
        if set(batch.statement_months)&month_set != month_set:
            findings.append('INCOMPLETE_STATEMENT_MONTH_COVERAGE')
    months_with_income=sum(v>0 for v in values)
    credible=months_with_income>=3 and unverified_count==0 and not any(x in findings for x in ('INCOMPLETE_STATEMENT_MONTH_COVERAGE','INVALID_STATEMENT_COVERAGE','INCOME_LABEL_CONFLICTS_WITH_OWN_ACCOUNT'))
    # Income baseline is conservative and transparent; no applicant-income
    # uplift from incomplete supporting months or exceptional inflows.
    mean=sum(values)/D(6)
    accepted=cash(min(D(median(values)),mean)) if credible else D(0)
    avg=float(mean)
    volatility=round(pstdev([float(v) for v in values])/avg,6) if avg else None
    nonzero=[float(v) for v in values if v>0]
    if len(nonzero)>=3 and max(nonzero)>2.5*median(nonzero):
        findings.append('EXCEPTIONAL_INCOME_SPIKE_REVIEW')
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
