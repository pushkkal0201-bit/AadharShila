"""Synthetic model evaluation validates the pipeline only, not real credit performance."""
import json
from pathlib import Path
import pytest
from aadharshila.risk_training import validate_manifest, train, predict_one


def test_manifest_requires_usage_rights():
    with pytest.raises(ValueError):
        validate_manifest({'source':'synthetic'})


def test_synthetic_temporal_holdout_runs_reproducibly(tmp_path):
    pd=pytest.importorskip('pandas');np=pytest.importorskip('numpy')
    rng=np.random.default_rng(2048)
    n=600
    f=rng.uniform(0.20,0.65,n)
    loan=rng.uniform(0.3,0.9,n)
    volatility=rng.uniform(0.02,0.45,n)
    prob=1/(1+np.exp(-(-4+5*f+2*loan+2*volatility)))
    labels=rng.binomial(1,prob)
    rows=pd.DataFrame({'borrower_id':[f'SYN-{i:04d}' for i in range(n)],
                       'decision_date':pd.date_range('2021-01-01',periods=n,freq='D').astype(str),
                       'foir':f,'ltv':loan,'income_volatility':volatility,'default_12m':labels})
    csv=tmp_path/'training.csv';rows.to_csv(csv,index=False)
    manifest={'source':'tests/test_risk_training.py seeded synthetic generator',
              'license':'generated test fixtures', 'permission':'test-only',
              'label_definition':'synthetic 12-month delinquency simulation',
              'horizon_months':12,'features':['foir','ltv','income_volatility'],
              'synthetic':True,'decision_date_column':'decision_date','borrower_id_column':'borrower_id'}
    m=tmp_path/'manifest.json';m.write_text(json.dumps(manifest))
    output=tmp_path/'research_model.json'
    result=train(csv,m,output)
    assert result['capability']=='SYNTHETIC_EVALUATION_ONLY'
    assert result['deployment_status']=='NOT_AUTHORIZED'
    assert result['holdout_test']['n']==120
    assert 0 <= result['holdout_test']['roc_auc'] <= 1
    assert 0 <= predict_one(json.loads(output.read_text()),{'foir':0.25,'ltv':0.45,'income_volatility':0.2}) <= 1
    rows.loc[8,'borrower_id']=rows.loc[9,'borrower_id']
    rows.to_csv(csv,index=False)
    with pytest.raises(ValueError,match='Duplicate'):
        train(csv,m,tmp_path/'forbidden.json')


def test_real_data_maturity_must_be_declared_and_complete(tmp_path):
    base={'source':'authorized-lender-dataset','license':'contractual',
          'permission':'lender-permitted-development','label_definition':'default by 12 months',
          'horizon_months':12,'features':['foir'],'synthetic':False,
          'decision_date_column':'decision_date','borrower_id_column':'borrower_id'}
    with pytest.raises(ValueError,match='observation_end_date'):
        validate_manifest(base)
    pd=pytest.importorskip('pandas')
    dates=pd.date_range('2024-01-01',periods=400,freq='D')
    rows=pd.DataFrame({'decision_date':dates.astype(str),
                       'borrower_id':[f'example-{i}' for i in range(400)],
                       'foir':[0.4 if i%2 else 0.3 for i in range(400)],
                       'default_12m':[i%2 for i in range(400)]})
    csv=tmp_path/'input.csv';rows.to_csv(csv,index=False)
    base['observation_end_date']='2025-01-31'
    meta=tmp_path/'manifest.json';meta.write_text(json.dumps(base))
    with pytest.raises(ValueError,match='observation window'):
        train(csv,meta,tmp_path/'not-mature.json')
    assert not (tmp_path/'not-mature.json').exists()
