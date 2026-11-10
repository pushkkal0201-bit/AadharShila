"""Reproducible non-networked advisory ML walkthrough for hackathon judges."""
from __future__ import annotations
import json
from pathlib import Path
from aadharshila.evidence_intelligence import review_transactions,synthetic_case_batch


def run() -> dict:
    sample=synthetic_case_batch('SELF_EMPLOYED')
    result=review_transactions(sample,bank_income=100000,supporting_income=55000,income_tolerance=0.15)
    assert result['assessment_effect']=='NONE'
    assert result['model']['credit_decision_use'] is False
    assert any(s['code']=='INCOME_CONTRADICTION' for s in result['signals'])
    assert any(x['code']=='UNUSUAL_MONTHLY_RECEIPT_PATTERN' for x in result['outlier_months'])
    return {'case_reference':'AS-1004 (synthetic fixture)',
            'review_status':result['status'],
            'source_contradiction_pct':round(result['evidence_comparison']['difference_ratio']*100,2),
            'income_preview_inr':result['reconciliation']['accepted_monthly_income'],
            'advisory_outlier_months':result['outlier_months'],
            'reason_codes':[s['code'] for s in result['signals']],
            'model_status':result['model']['status'],
            'model_reference':result['model']['reference'],
            'credit_decision_modified':False,
            'read_only':True}


if __name__=='__main__':
    print(json.dumps(run(),indent=2,sort_keys=True))
