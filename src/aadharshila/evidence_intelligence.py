"""Advisory ML-assisted transaction review for synthetic mortgage demos.

The reference distribution is artificially generated and intentionally never
used as evidence, a credit-risk probability, or an underwriting input. The
Isolation Forest identifies unusual *relative monthly receipt magnitudes*;
separate deterministic controls describe why specific transactions merit review.
"""
from __future__ import annotations

import math
import random
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any

from .income import TransactionBatch, reconcile

MODEL_NAME = 'isolation-forest-synthetic-reference-v1'
REFERENCE_SEED = 20261110


def _month_values(batch: TransactionBatch, report: dict) -> list[tuple[str, float]]:
    return sorted((month, float(amount)) for month, amount in report['monthly_receipts'].items())


def _train_model():
    """Train a deterministic reference detector, *never* on borrower outcomes."""
    from sklearn.ensemble import IsolationForest
    rng = random.Random(REFERENCE_SEED)
    # Simulated non-negative monthly receipt ratios around a recurring baseline.
    reference = [[math.log1p(max(0.0, rng.lognormvariate(0.0, 0.16)))] for _ in range(384)]
    return IsolationForest(n_estimators=96, contamination=0.05,
                           random_state=REFERENCE_SEED, n_jobs=1).fit(reference)


def review_transactions(batch: TransactionBatch, bank_income: Any = None,
                        supporting_income: Any = None, income_tolerance: float = 0.15) -> dict:
    """Produce a bounded, side-effect-free reviewer report.

    Only the existing reconciler computes eligible amounts. Its output remains
    a preview. An outlier model never changes the verified status or any
    saved assessment, and anomaly scores are not confidence probabilities.
    """
    report = reconcile(batch)
    values = _month_values(batch, report)
    positive = [amount for _, amount in values if amount > 0]
    signals = []
    for code in report['findings']:
        signals.append({'code': code, 'origin': 'DETERMINISTIC_RECONCILIATION',
                        'explanation': _reason_for(code)})

    amounts = {}
    for label, raw in [('bank_income', bank_income), ('income_support', supporting_income)]:
        try:
            value = Decimal(str(raw))
            if value.is_finite() and value >= 0:
                amounts[label] = float(value)
        except (ValueError, TypeError, ArithmeticError):
            continue
    if set(amounts) == {'bank_income', 'income_support'}:
        higher = max(amounts.values())
        discrepancy = round(abs(amounts['bank_income'] - amounts['income_support']) / higher, 6) if higher else 0.0
        if discrepancy > income_tolerance:
            signals.append({'code': 'INCOME_CONTRADICTION', 'origin': 'PERSISTED_EVIDENCE',
                            'explanation': 'The latest bank-income and income-support assertions disagree beyond the active policy tolerance.'})
    else:
        discrepancy = None
        signals.append({'code': 'SOURCE_COMPARISON_INCOMPLETE', 'origin': 'PERSISTED_EVIDENCE',
                        'explanation': 'Both numeric income evidence assertions are required for a source comparison.'})

    outliers = []
    model_status = 'INSUFFICIENT_DATA'
    if len(positive) >= 3 and median(positive) > 0:
        try:
            detector = _train_model()
        except ImportError:
            model_status = 'ML_DEPENDENCY_UNAVAILABLE'
        else:
            baseline = median(positive)
            examples = [[math.log1p(amount / baseline)] for _, amount in values]
            raw_scores = detector.decision_function(examples)
            model_status = 'SYNTHETIC_REFERENCE_EVALUATED'
            for (month, amount), score in zip(values, raw_scores):
                # Reference-model output is an *un-calibrated* anomaly margin.
                if float(score) < 0:
                    outliers.append({'month': month, 'observed_receipts_inr': round(amount, 2),
                                     'relative_to_median': round(amount / baseline, 3),
                                     'anomaly_margin': round(float(-score), 6),
                                     'code': 'UNUSUAL_MONTHLY_RECEIPT_PATTERN'})
            outliers.sort(key=lambda row: (-row['anomaly_margin'], row['month']))

    return {'status': 'REVIEW_REQUIRED' if signals or outliers else 'ADVISORY_ONLY',
            'assessment_effect': 'NONE', 'source_mode': 'ANALYST_SUBMITTED_PREVIEW',
            'model': {'name': MODEL_NAME, 'status': model_status, 'reference': 'GENERATED_SYNTHETIC_DATA',
                      'method': 'IsolationForest on log monthly receipts divided by observed median',
                      'not_a_probability': True, 'credit_decision_use': False},
            'reconciliation': report, 'evidence_comparison': {
                'bank_income_inr': amounts.get('bank_income'),
                'income_support_inr': amounts.get('income_support'),
                'difference_ratio': discrepancy, 'active_policy_tolerance': float(income_tolerance)},
            'outlier_months': outliers,
            'signals': signals,
            'recommended_actions': _review_actions(signals, outliers),
            'disclaimer': ('Demonstration-only anomaly prioritization using artificial reference data. '
                           'Does not verify a bank statement, measure fraud probability, update accepted income, '
                           'or alter a saved underwriting outcome.')}


def _reason_for(code: str) -> str:
    known = {
        'DUPLICATE_INCOME_RECEIPT': 'Identical referenced income credits appear across statements; inspect source records.',
        'DUPLICATE_IDS_EXCLUDED': 'Repeated transaction IDs were excluded from the preview.',
        'EXCEPTIONAL_INCOME_SPIKE_REVIEW': 'A monthly income spike exceeds the conservative reconciliation heuristic.',
        'LOAN_PROCEEDS': 'Loan proceeds do not count as recurring income.',
        'UNVERIFIED_TRANSACTIONS_EXCLUDED': 'Unverified transaction rows are excluded from calculation.',
        'INCOME_LABEL_CONFLICTS_WITH_OWN_ACCOUNT': 'A supposed income credit originates from an account included in the submitted batch.',
        'INSUFFICIENT_INCOME_COVERAGE': 'Fewer than three months contain qualifying income receipts.',
        'INCOMPLETE_STATEMENT_MONTH_COVERAGE': 'The declared statement set does not cover all six preceding full months.',
    }
    return known.get(code, 'Check the corresponding normalized source transaction and its evidence provenance.')


def _review_actions(signals: list, outliers: list) -> list[str]:
    actions = []
    if any(s['code'] == 'INCOME_CONTRADICTION' for s in signals):
        actions.append('Request an independent income-support explanation for the conflicting values.')
    if outliers:
        actions.append('Inspect original statements and source references for flagged months; do not infer fraud.')
    if any('DUPLICATE' in s['code'] for s in signals):
        actions.append('Reconcile repeated transaction references against the source statement before recalculation.')
    if not actions:
        actions.append('Confirm statement ownership, coverage, and consent before using any evidence in underwriting.')
    return actions


def synthetic_case_batch(applicant_type: str, as_of: date | None = None) -> TransactionBatch:
    """Six-month synthetic fixture intended ONLY for interactive judge demos."""
    as_of = as_of or date(2026, 11, 10)
    year, month = as_of.year, as_of.month
    months = []
    for _ in range(6):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append(f'{year:04d}-{month:02d}')
    months.reverse()
    income_category = 'BUSINESS_RECEIPT' if applicant_type == 'SELF_EMPLOYED' else 'SALARY'
    records = []
    for i, ym in enumerate(months):
        records.append({'transaction_id': f'SYN-INCOME-{i+1}', 'account_id': 'synthetic-bank-A',
                        'posting_date': ym+'-10', 'amount': 820000 if i == 3 else 100000,
                        'direction': 'CREDIT', 'category': income_category,
                        'reference': f'SYNTHETIC-RECEIPT-{i+1}', 'counterparty_id': 'synthetic-customer-X',
                        'verified': True})
    records.append({'transaction_id': 'SYN-LOAN-1', 'account_id': 'synthetic-bank-A',
                    'posting_date': months[2]+'-13', 'amount': 240000, 'direction': 'CREDIT',
                    'category': 'LOAN_PROCEEDS', 'reference': 'SYNTHETIC-LOAN-1',
                    'counterparty_id': 'synthetic-lender', 'verified': True})
    records.append({'transaction_id': 'SYN-DUP-1', 'account_id': 'synthetic-bank-B',
                    'posting_date': months[0]+'-10', 'amount': 100000, 'direction': 'CREDIT',
                    'category': income_category, 'reference': 'SYNTHETIC-RECEIPT-1',
                    'counterparty_id': 'synthetic-customer-X', 'verified': True})
    return TransactionBatch.model_validate({'transactions': records, 'applicant_type': applicant_type,
                                            'as_of': as_of.isoformat(), 'statement_months': months})
