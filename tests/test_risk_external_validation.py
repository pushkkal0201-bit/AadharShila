"""External cohort evaluation is a technical check, never institutional approval."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import pytest

from aadharshila.risk_external_validation import evaluate_external
from aadharshila.risk_training import train
from aadharshila.synthetic_risk_benchmark import generate_synthetic


@pytest.fixture(scope='module')
def research_model(tmp_path_factory):
    root = tmp_path_factory.mktemp('out-of-time-model')
    data,manifest = generate_synthetic(root,rows=640,seed=42)
    artifact = root/'research_model.json'
    train(data,manifest,artifact)
    return root,data,manifest,artifact,hashlib.sha256(artifact.read_bytes()).hexdigest()


@pytest.fixture
def independent_synthetic(tmp_path, research_model):
    import numpy as np
    import pandas as pd
    root,_,_,artifact,digest = research_model
    # Independent generator seed and entirely later dates; no actual mortgage records.
    raw,_ = generate_synthetic(tmp_path,rows=300,seed=99)
    frame = pd.read_csv(raw)
    frame['decision_date'] = pd.date_range('2028-01-01',periods=len(frame),freq='D').astype(str)
    frame['synthetic_segment'] = np.where(np.arange(len(frame))%2,'SYNTH_A','SYNTH_B')
    frame.to_csv(raw,index=False)
    manifest = json.loads((tmp_path/'synthetic_manifest.json').read_text())
    manifest.update(dataset_id='SYNTHETIC_EXTERNAL_99',independent_of_training_declared=True,
                    segment_column='synthetic_segment')
    (tmp_path/'synthetic_manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return artifact,digest,raw,tmp_path/'synthetic_manifest.json',tmp_path/'report.json'


def evaluate(cohort, **options):
    artifact,digest,data,manifest,output=cohort
    return evaluate_external(artifact,expected_artifact_sha256=digest,data_file=data,
                             manifest_file=manifest,output=output,bootstrap_replicates=100,**options)


def test_independent_later_cohort_reports_baseline_uncertainty_psi_and_segments(independent_synthetic):
    report=evaluate(independent_synthetic)
    assert report['status']=='OFFLINE_EXTERNAL_RESEARCH_EVALUATION_ONLY'
    assert report['decision_use'] is False
    assert report['model_activated'] is False
    assert report['independent_validation_completed'] is False
    assert report['metrics']['n']==300
    assert report['metrics']['positive_count']>=10
    assert report['constant_training_prevalence_baseline']['n']==300
    assert report['earliest_decision_date']=='2028-01-01'
    assert set(report['feature_drift_psi'])==set(json.loads(independent_synthetic[0].read_text())['features'])
    assert set(report['review_only_group_metrics'])=={'SYNTH_A','SYNTH_B'}
    for metric,interval in report['bootstrap_95pct'].items():
        assert interval['lower_95pct']<=interval['upper_95pct']
    assert report['bootstrap_95pct']==evaluate(independent_synthetic)['bootstrap_95pct']
    assert 'SYN-99-' not in independent_synthetic[-1].read_text()


def test_reject_forged_digest(independent_synthetic):
    with pytest.raises(ValueError,match='SHA-256 mismatch'):
        evaluate_external(independent_synthetic[0],expected_artifact_sha256='0'*64,
                          data_file=independent_synthetic[2],manifest_file=independent_synthetic[3],
                          output=independent_synthetic[4])
    assert not independent_synthetic[-1].exists()


def test_reject_training_file_as_external_test(tmp_path,research_model):
    root,data,manifest,artifact,digest=research_model
    meta=json.loads(manifest.read_text())
    meta.update(dataset_id='TRAIN_SAME',independent_of_training_declared=True)
    metadata=tmp_path/'manifest.json';metadata.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='cannot be the model training'):
        evaluate_external(artifact,expected_artifact_sha256=digest,data_file=data,
                          manifest_file=metadata,output=tmp_path/'report.json')


def test_reject_temporal_overlap(independent_synthetic):
    import pandas as pd
    data=independent_synthetic[2]
    frame=pd.read_csv(data)
    frame.loc[0,'decision_date']='2021-01-01'
    frame.to_csv(data,index=False)
    with pytest.raises(ValueError,match='strictly after'):
        evaluate(independent_synthetic)
    assert not independent_synthetic[-1].exists()


def test_reject_manifest_without_data_permission(independent_synthetic):
    meta=json.loads(independent_synthetic[3].read_text())
    meta['permission']=''
    independent_synthetic[3].write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='provenance, rights'):
        evaluate(independent_synthetic)


def test_reject_unsupported_feature_schema(independent_synthetic):
    meta=json.loads(independent_synthetic[3].read_text())
    meta['features']=list(reversed(meta['features']))
    independent_synthetic[3].write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='exact order'):
        evaluate(independent_synthetic)


def test_reject_invalid_or_unmatured_labels(independent_synthetic):
    import pandas as pd
    raw=independent_synthetic[2]
    df=pd.read_csv(raw)
    df.loc[0,'default_12m']=2
    df.to_csv(raw,index=False)
    with pytest.raises(ValueError,match='binary'):
        evaluate(independent_synthetic)


def test_reject_real_data_with_synthetic_trained_model(independent_synthetic):
    meta=json.loads(independent_synthetic[3].read_text())
    meta['synthetic']=False
    meta['observation_end_date']='2031-01-01'
    independent_synthetic[3].write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='synthetic/real-data'):
        evaluate(independent_synthetic)


def test_reject_duplicate_borrowers_and_unsupported_values(independent_synthetic):
    import pandas as pd
    raw=independent_synthetic[2]
    df=pd.read_csv(raw)
    df.loc[1,'borrower_id']=df.loc[0,'borrower_id']
    df.to_csv(raw,index=False)
    with pytest.raises(ValueError,match='repeated borrower'):
        evaluate(independent_synthetic)
    df.loc[1,'borrower_id']='SYNTH-INDEPENDENT-1'
    df.loc[10,'foir']=6.0
    df.to_csv(raw,index=False)
    with pytest.raises(ValueError,match='outside documented'):
        evaluate(independent_synthetic)


def test_research_preview_cannot_load_real_artifact(monkeypatch,tmp_path,research_model):
    from aadharshila.risk_serving import load_pinned_research_model, ResearchModelUnavailable
    _,_,_,artifact,digest=research_model
    a=json.loads(artifact.read_text())
    a['evaluation']['synthetic']=False
    a['evaluation']['capability']='EXTERNAL_DATA_EVALUATION_PENDING_INDEPENDENT_REVIEW'
    real_artifact=tmp_path/'not-live.json'
    real_artifact.write_text(json.dumps(a))
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_PATH',str(real_artifact))
    monkeypatch.setenv('AADHARSHILA_RESEARCH_MODEL_SHA256',hashlib.sha256(real_artifact.read_bytes()).hexdigest())
    monkeypatch.setenv('APP_ENV','development')
    with pytest.raises(ResearchModelUnavailable,match='Only non-authorized synthetic'):
        load_pinned_research_model()


def test_reproducible_external_date_demo(research_model,tmp_path):
    from aadharshila.risk_validation_demo import run
    _,_,_,artifact,_=research_model
    result=run(artifact,tmp_path/'external',rows=300,seed=99)
    assert result['status']=='SYNTHETIC_INDEPENDENT_DATE_TEST_ONLY'
    assert result['model_activated'] is False
    assert result['independent_validation_completed'] is False
    assert result['rows']==300
    assert (tmp_path/'external/independent_evaluation.json').exists()

def test_external_evaluation_rejects_non_numeric_values(independent_synthetic):
    import pandas as pd
    raw=independent_synthetic[2]
    frame=pd.read_csv(raw)
    frame['foir']=frame['foir'].astype(object)
    frame.loc[0,'foir']='not-a-number'
    frame.to_csv(raw,index=False)
    with pytest.raises(ValueError,match='Non-numeric evaluation'):
        evaluate(independent_synthetic)


def test_external_evaluation_rejects_normalized_duplicate_ids(independent_synthetic):
    import pandas as pd
    raw=independent_synthetic[2]
    frame=pd.read_csv(raw)
    frame.loc[1,'borrower_id']=' '+str(frame.loc[0,'borrower_id'])+' '
    frame.to_csv(raw,index=False)
    with pytest.raises(ValueError,match='repeated borrower'):
        evaluate(independent_synthetic)
