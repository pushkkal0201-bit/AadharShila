"""Hackathon advisory ML review, provenance, permissions and no-mutation checks."""
from __future__ import annotations
import pytest
from aadharshila.evidence_intelligence import synthetic_case_batch, review_transactions


def test_synthetic_as1004_review_is_explainable_and_inert():
    batch=synthetic_case_batch('SELF_EMPLOYED')
    r=review_transactions(batch,100000,55000,0.15)
    assert r['model']['status']=='SYNTHETIC_REFERENCE_EVALUATED'
    assert r['model']['not_a_probability'] is True
    assert r['model']['credit_decision_use'] is False
    assert r['assessment_effect']=='NONE'
    assert r['evidence_comparison']['difference_ratio']==0.45
    assert {'INCOME_CONTRADICTION','DUPLICATE_INCOME_RECEIPT','EXCEPTIONAL_INCOME_SPIKE_REVIEW'} <= {s['code'] for s in r['signals']}
    assert r['outlier_months']
    assert r['outlier_months'][0]['month']=='2026-08'
    assert r['outlier_months'][0]['relative_to_median']>8
    assert r['reconciliation']['excluded_credits']['LOAN_PROCEEDS']==240000
    assert r['reconciliation']['accepted_monthly_income']==100000


def test_synthetic_model_is_repeatable():
    batch=synthetic_case_batch('SALARIED')
    r1=review_transactions(batch,100000,55000)
    r2=review_transactions(batch,100000,55000)
    assert r1['outlier_months']==r2['outlier_months']
    assert r1['model']==r2['model']


def test_unverified_months_do_not_establish_income_or_verification():
    batch=synthetic_case_batch('SELF_EMPLOYED')
    for transaction in batch.transactions:transaction.verified=False
    r=review_transactions(batch,100000,55000)
    assert r['reconciliation']['accepted_monthly_income']==0
    assert r['model']['status']=='INSUFFICIENT_DATA'
    assert r['assessment_effect']=='NONE'


def test_inference_dependency_missing_does_not_fake_ml(monkeypatch):
    from aadharshila import evidence_intelligence as ai
    def unavailable():raise ImportError('test: research dependency absent')
    monkeypatch.setattr(ai,'_train_model',unavailable)
    r=ai.review_transactions(ai.synthetic_case_batch('SELF_EMPLOYED'),100000,55000)
    assert r['model']['status']=='ML_DEPENDENCY_UNAVAILABLE'
    assert r['outlier_months']==[]
    assert any(s['code']=='INCOME_CONTRADICTION' for s in r['signals'])


def test_api_restricts_borrowers_and_preserves_assessment(client,login,cases):
    app_id=cases['AS-1004']['id']
    payload=synthetic_case_batch('SELF_EMPLOYED').model_dump(mode='json')
    login('borrower')
    assert client.get(f'/api/v1/applications/{app_id}/evidence-intelligence/demo').status_code==403
    assert client.post(f'/api/v1/applications/{app_id}/evidence-intelligence',json=payload).status_code==403
    headers=login('analyst')
    assert client.get(f'/api/v1/applications/{app_id}/evidence-intelligence/demo').status_code==200
    before=client.get(f'/api/v1/applications/{app_id}').json()
    before_history=client.get(f'/api/v1/applications/{app_id}/assessments').json()
    response=client.post(f'/api/v1/applications/{app_id}/evidence-intelligence',json=payload,headers=headers)
    assert response.status_code==200,response.text
    report=response.json()
    assert report['assessment_effect']=='NONE'
    # Earlier tests can legitimately revise AS-1004; comparison must use live saved evidence.
    current_evidence=client.get(f'/api/v1/applications/{app_id}/evidence').json()['evidence']
    bank=float(current_evidence['bank_income']['value']['amount'])
    support=float(current_evidence['income_support']['value']['amount'])
    expected=round(abs(bank-support)/max(bank,support),6) if max(bank,support) else 0.0
    assert report['evidence_comparison']['difference_ratio']==expected
    assert report['model']['reference']=='GENERATED_SYNTHETIC_DATA'
    after=client.get(f'/api/v1/applications/{app_id}').json()
    after_history=client.get(f'/api/v1/applications/{app_id}/assessments').json()
    assert before['application']['revision']==after['application']['revision']
    assert before['latest_assessment']['id']==after['latest_assessment']['id']
    assert before_history==after_history


def test_api_refuses_wrong_applicant_category_and_oversized_batch(client,login,cases):
    app_id=cases['AS-1004']['id']
    headers=login('analyst')
    batch=synthetic_case_batch('SALARIED').model_dump(mode='json')
    assert client.post(f'/api/v1/applications/{app_id}/evidence-intelligence',json=batch,headers=headers).status_code==422
    batch=synthetic_case_batch('SELF_EMPLOYED').model_dump(mode='json')
    batch['transactions']=batch['transactions']*46  # 368 rows
    assert client.post(f'/api/v1/applications/{app_id}/evidence-intelligence',json=batch,headers=headers).status_code==422
