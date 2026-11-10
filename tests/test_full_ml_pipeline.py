"""Research model lifecycle: calibration, integrity, access, drift and decision non-interference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aadharshila.risk_training import train, predict_details
from aadharshila.risk_registry import register, verify
from aadharshila.risk_serving import (ResearchModelUnavailable, load_pinned_research_model,
                                      model_status, preview, research_drift)
from aadharshila.synthetic_risk_benchmark import generate_synthetic

DEMO_FEATURES={
    'foir':0.36,'ltv':0.50,'monthly_surplus_ratio':0.55,
    'obligation_to_income_ratio':0.10,'income_volatility':0.20,'credit_utilization':0.25,
}


@pytest.fixture(scope='module')
def trained(tmp_path_factory):
    p=tmp_path_factory.mktemp('risk-research')
    csv,manifest=generate_synthetic(p,rows=640,seed=42)
    artifact=p/'research_model.json'
    report=train(csv,manifest,artifact)
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    return p,csv,manifest,artifact,report,digest


def pin(monkeypatch,trained):
    _,_,_,artifact,_,digest=trained
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_PATH',str(artifact))
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_SHA256',digest)
    monkeypatch.setenv('APP_ENV','development')


def test_training_protocol_reports_calibration_holdout_and_baseline(trained):
    _,_,_,artifact,report,_=trained
    a=json.loads(artifact.read_text())
    assert report['splits']=={'train':416,'validation':96,'test':128}
    assert report['holdout_test']['n']==128
    assert report['holdout_test']['positive_count']>=10
    assert 0<=report['holdout_test']['roc_auc']<=1
    assert 0<=report['holdout_test']['expected_calibration_error']<=1
    assert report['holdout_test_uncalibrated']['n']==128
    assert report['holdout_constant_prevalence_baseline']['n']==128
    assert a['calibration']['method']=='PLATT_VALIDATION_ONLY'
    assert set(a['reference_distributions'])==set(DEMO_FEATURES)
    assert a['evaluation']['synthetic'] is True
    assert a['evaluation']['deployment_status']=='NOT_AUTHORIZED'
    assert a['evaluation']['capability']=='SYNTHETIC_EVALUATION_ONLY'
    details=predict_details(a,DEMO_FEATURES)
    assert 0<details['research_score']<1
    assert len(details['contributions'])==len(DEMO_FEATURES)
    assert details['decision_use'] is False
    assert details['assessment_effect']=='NONE'


def test_model_does_not_learn_from_holdout_outcomes(trained,tmp_path):
    import pandas as pd
    _,csv,manifest,artifact,report,_=trained
    frame=pd.read_csv(csv)
    original=json.loads(artifact.read_text())
    # Modify only the latest-period labels, keeping both classes in that partition.
    frame.loc[frame.index[-12:],'default_12m']=1-frame.loc[frame.index[-12:],'default_12m']
    revised=tmp_path/'changed_holdout.csv';frame.to_csv(revised,index=False)
    destination=tmp_path/'model.json'
    train(revised,manifest,destination)
    changed=json.loads(destination.read_text())
    for key in ['weights','intercept','scale_means','imputation_medians','calibration']:
        assert original[key]==changed[key],f'Holdout data leaked into model parameter: {key}'
    assert original['evaluation']['data_sha256']!=changed['evaluation']['data_sha256']


def test_pinned_artifact_preview_and_tamper_rejection(trained,monkeypatch,tmp_path):
    pin(monkeypatch,trained)
    assert model_status()['status']=='SYNTHETIC_RESEARCH_READY'
    score=preview(DEMO_FEATURES)
    assert score['model_activated'] is False
    assert score['assessment_effect']=='NONE'
    assert len(score['artifact_sha256'])==64
    with pytest.raises(ValueError,match='requires every declared'):
        preview({'foir':.2})
    with pytest.raises(ValueError,match='Invalid bounded'):
        preview({**DEMO_FEATURES,'foir':-1})
    raw=trained[3].read_bytes()
    altered=tmp_path/'altered.json';altered.write_bytes(raw+b' ')
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_PATH',str(altered))
    with pytest.raises(ResearchModelUnavailable,match='integrity mismatch'):
        load_pinned_research_model()
    # A matching digest does not permit a real-data or production-designated model.
    raw_document=json.loads(trained[3].read_text())
    raw_document['evaluation']['synthetic']=False
    forbidden=tmp_path/'not-synthetic.json'
    forbidden.write_text(json.dumps(raw_document),encoding='utf-8')
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_PATH',str(forbidden))
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_SHA256',hashlib.sha256(forbidden.read_bytes()).hexdigest())
    with pytest.raises(ResearchModelUnavailable,match='Only non-authorized synthetic'):
        load_pinned_research_model()
    monkeypatch.setenv('APP_ENV','production')
    with pytest.raises(ResearchModelUnavailable,match='disabled in production'):
        load_pinned_research_model()


def test_research_only_registry_and_tamper_rejection(trained,tmp_path):
    result=register(trained[3],tmp_path/'registry')
    assert result['status']=='REGISTERED_RESEARCH_ONLY'
    assert register(trained[3],tmp_path/'registry')['status']=='ALREADY_REGISTERED'
    entry=Path(result['registry_entry'])
    assert verify(entry)['status']=='INTEGRITY_VERIFIED_NOT_AUTHORIZED'
    (entry/'artifact.json').write_bytes((entry/'artifact.json').read_bytes()+b' ')
    with pytest.raises(ResearchModelUnavailable,match='integrity mismatch'):
        verify(entry)


def test_population_drift_returns_research_diagnostics(trained,monkeypatch):
    pin(monkeypatch,trained)
    samples=[dict(DEMO_FEATURES) for _ in range(130)]
    drift=research_drift(samples)
    assert drift['status']=='SYNTHETIC_DRIFT_REPORT'
    assert drift['assessment_effect']=='NONE'
    assert set(drift['features'])==set(DEMO_FEATURES)
    assert all(row['status']=='CALCULATED' for row in drift['features'].values())
    with pytest.raises(ValueError,match='100-2000'):
        research_drift(samples[:30])


def test_application_and_research_endpoint_isolation(trained,monkeypatch,client,login,cases):
    pin(monkeypatch,trained)
    app=cases['AS-1004']['id']
    login('borrower')
    assert client.get('/api/v1/research/risk-model/status').status_code==403
    assert client.post('/api/v1/research/risk-model/preview',json={
        'features':DEMO_FEATURES,'synthetic_acknowledged':True}).status_code==403
    h=login('analyst')
    before=client.get(f'/api/v1/applications/{app}').json()
    assert client.get('/api/v1/research/risk-model/status').json()['status']=='SYNTHETIC_RESEARCH_READY'
    assert client.post('/api/v1/research/risk-model/preview',headers=h,json={
        'features':DEMO_FEATURES,'synthetic_acknowledged':False}).status_code==422
    response=client.post('/api/v1/research/risk-model/preview',headers=h,json={
        'features':DEMO_FEATURES,'synthetic_acknowledged':True})
    assert response.status_code==200,response.text
    assert response.json()['assessment_effect']=='NONE'
    assert response.json()['decision_use'] is False
    after=client.get(f'/api/v1/applications/{app}').json()
    assert before['latest_assessment']==after['latest_assessment']
    assert before['application']['revision']==after['application']['revision']
    drift=client.post('/api/v1/research/risk-model/drift',headers=h,json={
        'rows':[dict(DEMO_FEATURES) for _ in range(101)],'synthetic_acknowledged':True})
    assert drift.status_code==200,drift.text
    monkeypatch.setenv('APP_ENV','production')
    # Production also disables local demo session authentication before route dispatch.
    assert client.post('/api/v1/research/risk-model/preview',headers=h,json={
        'features':DEMO_FEATURES,'synthetic_acknowledged':True}).status_code in (401,404)
    assert client.get('/api/v1/research/risk-model/status').status_code in (401,404)
