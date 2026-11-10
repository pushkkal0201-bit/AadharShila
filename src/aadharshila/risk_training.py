"""Reproducible, temporally held-out mortgage model research.

A trained artifact is an inert JSON research result. It is never installed into
Aadharshila's deterministic loan-decision engine. Synthetic labels do not
represent an empirical probability of mortgage default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_FEATURES = ['foir', 'ltv', 'monthly_surplus_ratio', 'obligation_to_income_ratio',
                    'income_volatility', 'credit_utilization']
ARTIFACT_VERSION = 'aadharshila-risk-research-v2'


def validate_manifest(manifest: dict):
    required = {'source', 'license', 'permission', 'label_definition', 'horizon_months',
                'features', 'synthetic', 'decision_date_column', 'borrower_id_column'}
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        raise ValueError('Model dataset manifest lacks required provenance: ' + str(sorted(required - set(manifest))))
    if any(not isinstance(manifest[k], str) or not manifest[k].strip()
           for k in ('source', 'license', 'permission', 'label_definition')):
        raise ValueError('Dataset provenance, rights and use permission are required')
    if manifest['horizon_months'] != 12 or isinstance(manifest['horizon_months'], bool):
        raise ValueError('This evaluation pipeline requires a 12-month matured outcome definition')
    if not isinstance(manifest['synthetic'], bool):
        raise ValueError('synthetic flag must be a boolean')
    features = manifest['features']
    if not isinstance(features, list) or not features or len(features) != len(set(features)) or any(
        f not in DEFAULT_FEATURES for f in features if isinstance(f, str)) or any(not isinstance(f, str) for f in features):
        raise ValueError('Features must be unique, explicitly allowed decision-time numeric features')
    if manifest['decision_date_column'] == manifest['borrower_id_column']:
        raise ValueError('Decision date and borrower identifier must be separate')
    if not manifest['synthetic'] and not manifest.get('observation_end_date'):
        raise ValueError('Real-world datasets require an explicit observation_end_date for 12-month label maturity')


def calibration_table(y, probabilities, bins=10):
    entries = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        index = [j for j, p in enumerate(probabilities) if lo <= p < hi or (i == bins-1 and p == 1)]
        if index:
            entries.append({'range': [lo, hi], 'n': len(index),
                            'mean_prediction': round(sum(probabilities[j] for j in index)/len(index), 6),
                            'observed_rate': round(sum(y[j] for j in index)/len(index), 6)})
    return entries


def expected_calibration_error(table: list[dict]) -> float:
    n = sum(row['n'] for row in table)
    return round(sum(row['n'] * abs(row['observed_rate'] - row['mean_prediction'])
                     for row in table) / n, 6) if n else 0.0


def sigmoid(value: float) -> float:
    z = max(-700.0, min(700.0, float(value)))
    return 1 / (1 + math.exp(-z))


def logit(p: float) -> float:
    q = max(1e-7, min(1-1e-7, float(p)))
    return math.log(q/(1-q))


def _metrics(actual, probs, *, calibration_bins=10):
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss
    y, p = list(map(int, actual)), list(map(float, probs))
    table = calibration_table(y,p,bins=calibration_bins)
    return {'n':len(y), 'positive_count':sum(y),
            'roc_auc':round(float(roc_auc_score(y,p)),6),
            'average_precision':round(float(average_precision_score(y,p)),6),
            'brier_score':round(float(brier_score_loss(y,p)),6),
            'log_loss':round(float(log_loss(y,p,labels=[0,1])),6),
            'expected_calibration_error':expected_calibration_error(table),
            'calibration':table}


def _atomic_json(path: Path, value: dict):
    """No pickle, partial writes or private temporary artifact permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.risk-artifact-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as dest:
            json.dump(value,dest,indent=2,sort_keys=True,allow_nan=False)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def train(csv: Path, manifest_file: Path, output: Path) -> dict:
    """Train on earliest decisions, calibrate on validation, evaluate untouched latest holdout."""
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    csv, manifest_file, output = Path(csv), Path(manifest_file), Path(output)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    validate_manifest(manifest)
    df = pd.read_csv(csv)
    date_key, id_key = manifest['decision_date_column'], manifest['borrower_id_column']
    required = set(manifest['features']) | {date_key, id_key, 'default_12m'}
    if not required.issubset(df.columns):
        raise ValueError('Dataset lacks required columns: ' + str(sorted(required - set(df.columns))))
    if len(df) < 300:
        raise ValueError('Need at least 300 unique, matured decision records for this development evaluation')
    borrower_ids=df[id_key].astype('string').str.strip()
    if borrower_ids.isna().any() or borrower_ids.eq('').any() or borrower_ids.duplicated().any():
        raise ValueError('Duplicate or missing borrower IDs: refuse possible train/test leakage')
    decision_dates = pd.to_datetime(df[date_key], utc=True, errors='coerce')
    if decision_dates.isna().any():
        raise ValueError('Every decision date must be valid')
    if not manifest['synthetic']:
        observation_end = pd.to_datetime(manifest['observation_end_date'], utc=True, errors='coerce')
        if pd.isna(observation_end):raise ValueError('Invalid observation_end_date')
        if (decision_dates + pd.DateOffset(months=12) > observation_end).any():
            raise ValueError('Real-world default labels must have a complete 12-month observation window')
    if df['default_12m'].isna().any() or not set(df['default_12m'].unique()) <= {0,1}:
        raise ValueError('Expected mature binary default_12m labels, no null/unknown outcomes')
    values = df[manifest['features']].apply(pd.to_numeric, errors='coerce')
    if (df[manifest['features']].notna() & values.isna()).to_numpy().any():
        raise ValueError('Non-numeric training feature is not a missing observation')
    numeric_values=values.to_numpy(dtype=float)
    if np.isinf(numeric_values).any():raise ValueError('Non-finite model features')
    observed=numeric_values[np.isfinite(numeric_values)]
    if np.any((observed<0) | (observed>5)):
        raise ValueError('Training feature outside documented [0,5] inference contract')
    if values.isnull().all(axis=0).any():raise ValueError('At least one feature column has no observed values')
    ordered = np.argsort(decision_dates.to_numpy(), kind='stable')
    n=len(df)
    sections={'train':ordered[:int(n*.65)], 'validation':ordered[int(n*.65):int(n*.8)],
              'test':ordered[int(n*.8):]}
    # A date shared by a partition boundary risks future-period leakage.
    for previous, later in [('train','validation'),('validation','test')]:
        if decision_dates.iloc[sections[previous]].max() >= decision_dates.iloc[sections[later]].min():
            raise ValueError('Temporal split boundaries must not share a decision date')
    y=df['default_12m'].astype(int).to_numpy()
    for label,ix in sections.items():
        if len(np.unique(y[ix]))<2 or min(np.bincount(y[ix]))<10:
            raise ValueError(f'{label} does not have at least 10 samples of each class')
    features=values.to_numpy(dtype=float)
    imp=SimpleImputer(strategy='median',keep_empty_features=False)
    scaler=StandardScaler()
    xt=scaler.fit_transform(imp.fit_transform(features[sections['train']]))
    model=LogisticRegression(max_iter=2000, random_state=42)
    model.fit(xt,y[sections['train']])

    def raw(ix):return model.predict_proba(scaler.transform(imp.transform(features[ix])))[:,1]
    val_raw,test_raw=raw(sections['validation']),raw(sections['test'])
    # Platt scaling is fitted only on the separate validation period. Test labels
    # are never used for training, transformation, calibration or model selection.
    val_logit=np.array([logit(p) for p in val_raw]).reshape(-1,1)
    calibrator=LogisticRegression(max_iter=2000,random_state=42,C=1e3)
    calibrator.fit(val_logit,y[sections['validation']])
    slope=float(calibrator.coef_[0,0]); offset=float(calibrator.intercept_[0])
    def calibrated(prob):return [sigmoid(slope*logit(p)+offset) for p in prob]
    val_cal,test_cal=calibrated(val_raw),calibrated(test_raw)
    baseline=float(np.mean(y[sections['train']]))
    train_frame=values.iloc[sections['train']]
    feature_bounds={name:{'p01':round(float(train_frame[name].quantile(.01)),8),
                          'p99':round(float(train_frame[name].quantile(.99)),8)}
                    for name in manifest['features']}
    reference_distributions={}
    for name in manifest['features']:
        measured=imp.transform(features[sections['train']])[:,manifest['features'].index(name)]
        inner=np.quantile(measured,[.2,.4,.6,.8]).tolist()
        edges=[float('-inf'),*inner,float('inf')]
        counts=np.histogram(measured,bins=edges)[0].tolist()
        reference_distributions[name]={'interior_edges':[round(float(x),8) for x in inner],
                                       'counts':[int(x) for x in counts]}

    dates={name:[str(decision_dates.iloc[ix].min()),str(decision_dates.iloc[ix].max())]
           for name,ix in sections.items()}
    report={
        'model_family':'LOGISTIC_REGRESSION_PLATT_CALIBRATED',
        'deployment_status':'NOT_AUTHORIZED',
        'capability':'SYNTHETIC_EVALUATION_ONLY' if manifest['synthetic'] else 'EXTERNAL_DATA_EVALUATION_PENDING_INDEPENDENT_REVIEW',
        'synthetic':manifest['synthetic'],
        'source':manifest['source'],'license':manifest['license'],
        'label_definition':manifest['label_definition'],'horizon_months':12,
        'label_maturity':'SYNTHETIC_SIMULATION' if manifest['synthetic'] else '12_MONTH_WINDOW_CHECKED_AGAINST_DECLARED_OBSERVATION_END_DATE',
        'data_sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),
        'manifest_sha256':hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
        'decision_date_ranges':dates,
        'features':manifest['features'],
        'splits':{key:len(ix) for key,ix in sections.items()},
        'calibration_protocol':'Train first 65%, fit Platt scaling on next 15%, evaluate once on last 20%',
        'validation_uncalibrated':_metrics(y[sections['validation']],val_raw),
        'validation':_metrics(y[sections['validation']],val_cal),
        'holdout_test_uncalibrated':_metrics(y[sections['test']],test_raw),
        'holdout_test':_metrics(y[sections['test']],test_cal),
        'holdout_constant_prevalence_baseline':_metrics(y[sections['test']],[baseline]*len(test_cal)),
        'training_timestamp':datetime.now(timezone.utc).isoformat(),
        'limitations':['Training data rights and labels require independent audit',
            'Calibration on the validation split is optimistic on that split; holdout is independent',
            'No causal inference or fairness certification',
            'No automatic production deployment',
            'No model use in legal credit decisions',
            'Synthetic outcomes do not establish real-world mortgage default accuracy']}
    artifact={'artifact_format':ARTIFACT_VERSION,'features':manifest['features'],
              'imputation_medians':imp.statistics_.tolist(),
              'scale_means':scaler.mean_.tolist(),'scale_stds':scaler.scale_.tolist(),
              'weights':model.coef_[0].tolist(),'intercept':float(model.intercept_[0]),
              'calibration':{'method':'PLATT_VALIDATION_ONLY','slope':slope,'intercept':offset},
              'feature_bounds':feature_bounds,'reference_distributions':reference_distributions,
              'training_prevalence':baseline,
              'evaluation':report}
    # Version model parameters independently of the human-readable training timestamp.
    core={key:artifact[key] for key in ['artifact_format','features','imputation_medians',
          'scale_means','scale_stds','weights','intercept','calibration']}
    parameter_sha=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),
                                          allow_nan=False).encode('utf-8')).hexdigest()
    artifact['parameter_sha256']=parameter_sha
    report['parameter_sha256']=parameter_sha
    _atomic_json(output,artifact)
    return report


def _infer(artifact: dict, features: dict, *, require_all: bool=False) -> dict:
    if artifact.get('artifact_format')!=ARTIFACT_VERSION:
        raise ValueError('Unsupported research model artifact version')
    keys=artifact['features']
    if require_all and set(features)!=set(keys):
        raise ValueError('Preview requires every declared model feature, without extras')
    x=[];contributions=[];warnings=[]
    for key,med,avg,scale,weight in zip(keys,artifact['imputation_medians'],
                                        artifact['scale_means'],artifact['scale_stds'],artifact['weights']):
        value=features.get(key,med)
        if value is None:value=med
        if isinstance(value,bool):raise ValueError('Boolean model input is invalid')
        number=float(value)
        if not math.isfinite(number) or number<0 or number>5:
            raise ValueError(f'Invalid bounded decision-time numeric feature: {key}')
        if not math.isfinite(scale) or scale<=0:raise ValueError('Invalid preprocessing scale')
        standardized=(number-avg)/scale
        contribution=weight*standardized
        x.append(contribution)
        contributions.append({'feature':key,'input':round(number,6),'log_odds_contribution':round(contribution,6)})
        bounds=artifact.get('feature_bounds',{}).get(key)
        if bounds and (number<bounds['p01'] or number>bounds['p99']):
            warnings.append({'feature':key,'code':'OUTSIDE_TRAINING_P01_P99',
                             'reference_range':[bounds['p01'],bounds['p99']]})
    raw=sigmoid(artifact['intercept']+sum(x))
    cal=artifact['calibration']
    score=sigmoid(cal['slope']*logit(raw)+cal['intercept'])
    contributions.sort(key=lambda x:-abs(x['log_odds_contribution']))
    return {'research_score':round(score,6),'uncalibrated_score':round(raw,6),
            'contributions':contributions,'distribution_warnings':warnings}


def predict_one(artifact: dict, features: dict) -> float:
    """Offline research only; probability here means synthetic-label model output."""
    return _infer(artifact,features)['research_score']


def predict_details(artifact: dict, features: dict) -> dict:
    """Explainable, input-bounded preview for an explicitly synthetic scenario."""
    result=_infer(artifact,features,require_all=True)
    return {**result,'calibration':artifact['calibration']['method'],
            'assessment_effect':'NONE','decision_use':False,'label_source':'SYNTHETIC_GENERATOR',
            'score_semantics':'Model output for an invented outcome label; NOT a validated mortgage PD',
            'requires_human_review':True}


def main():
    parser=argparse.ArgumentParser(description='Offline mortgage risk research: never live loan decisions')
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(train(args.data,args.manifest,args.output),indent=2))

if __name__=='__main__':main()
