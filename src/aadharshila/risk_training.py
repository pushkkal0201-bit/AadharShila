"""Offline credit-model development and held-out evaluation; NOT an approval engine.

Requires authorized, appropriately licensed, mature outcome-labelled data.
No supplied dataset means no real-world validated model; do not invent metrics.
The generated model is not loaded into underwriting automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_FEATURES = ['foir', 'ltv', 'monthly_surplus_ratio', 'obligation_to_income_ratio',
                    'income_volatility', 'credit_utilization']


def validate_manifest(manifest: dict):
    required = {'source', 'license', 'permission', 'label_definition', 'horizon_months',
                'features', 'synthetic', 'decision_date_column', 'borrower_id_column'}
    if not required.issubset(manifest):
        raise ValueError('Model dataset manifest lacks required provenance: ' + str(sorted(required - set(manifest))))
    if not manifest['source'] or not manifest['license'] or not manifest['permission']:
        raise ValueError('Dataset provenance, rights and use permission are required')
    if manifest['horizon_months'] != 12:
        raise ValueError('This evaluation pipeline requires a 12-month matured outcome definition')
    if not isinstance(manifest['synthetic'], bool):
        raise ValueError('synthetic flag must be a boolean')
    if not manifest['features'] or any(f not in DEFAULT_FEATURES for f in manifest['features']):
        raise ValueError('Only explicitly allowed decision-time numeric features can be used')
    if 'default_12m' in manifest['features']:
        raise ValueError('Outcome must not be a feature')
    if not manifest['synthetic'] and not manifest.get('observation_end_date'):
        raise ValueError('Real-world datasets require an explicit observation_end_date for 12-month label maturity')


def calibration_table(y, probabilities, bins=5):
    entries = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        index = [j for j, p in enumerate(probabilities) if lo <= p < hi or (i == bins-1 and p == 1)]
        if index:
            entries.append({'range': [lo, hi], 'n': len(index),
                            'mean_prediction': round(sum(probabilities[j] for j in index)/len(index), 6),
                            'observed_rate': round(sum(y[j] for j in index)/len(index), 6)})
    return entries


def train(csv: Path, manifest_file: Path, output: Path) -> dict:
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss
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
    if df[id_key].isnull().any() or df[id_key].duplicated().any():
        raise ValueError('Duplicate or missing borrower IDs: refuse possible train/test leakage')
    decision_dates = pd.to_datetime(df[date_key], utc=True, errors='coerce')
    if decision_dates.isna().any():
        raise ValueError('Every decision date must be valid')
    if not manifest['synthetic']:
        observation_end = pd.to_datetime(manifest['observation_end_date'], utc=True, errors='coerce')
        if pd.isna(observation_end):
            raise ValueError('Invalid observation_end_date')
        if (decision_dates + pd.DateOffset(months=12) > observation_end).any():
            raise ValueError('Real-world default labels must have a complete 12-month observation window')
    if df['default_12m'].isna().any() or not set(df['default_12m'].unique()) <= {0,1}:
        raise ValueError('Expected mature binary default_12m labels, no null/unknown outcomes')
    values = df[manifest['features']].apply(pd.to_numeric, errors='coerce')
    if np.isinf(values.to_numpy()).any():
        raise ValueError('Non-finite model features')
    if values.isnull().all(axis=0).any():
        raise ValueError('At least one feature column has no observed values')
    ordered = np.argsort(decision_dates.to_numpy(), kind='stable')
    n = len(df)
    sections = {'train': ordered[:int(n*0.65)],
                'validation': ordered[int(n*0.65):int(n*0.8)],
                'test': ordered[int(n*0.8):]}
    y = df['default_12m'].astype(int).to_numpy()
    for label, ix in sections.items():
        if len(np.unique(y[ix])) < 2 or min(np.bincount(y[ix])) < 10:
            raise ValueError(f'{label} does not have at least 10 samples of each class')
    features = values.to_numpy(dtype=float)
    imp = SimpleImputer(strategy='median', keep_empty_features=False)
    scaler = StandardScaler()
    xt = scaler.fit_transform(imp.fit_transform(features[sections['train']]))
    model = LogisticRegression(max_iter=2000, random_state=42, class_weight=None)
    model.fit(xt, y[sections['train']])

    def predict(ix):
        return model.predict_proba(scaler.transform(imp.transform(features[ix])))[:,1]
    val_p, test_p = predict(sections['validation']), predict(sections['test'])
    def report(ix, pred):
        actual = y[ix]
        return {'n':int(len(actual)), 'positive_count':int(sum(actual)),
                'roc_auc':round(float(roc_auc_score(actual,pred)),6),
                'average_precision':round(float(average_precision_score(actual,pred)),6),
                'brier_score':round(float(brier_score_loss(actual,pred)),6),
                'log_loss':round(float(log_loss(actual,pred,labels=[0,1])),6),
                'calibration':calibration_table(actual.tolist(),pred.tolist())}
    output.parent.mkdir(parents=True,exist_ok=True)
    report_data = {
        'model_family':'LOGISTIC_REGRESSION', 'deployment_status':'NOT_AUTHORIZED',
        'capability':'SYNTHETIC_EVALUATION_ONLY' if manifest['synthetic'] else 'EXTERNAL_DATA_EVALUATION_PENDING_INDEPENDENT_REVIEW',
        'source':manifest['source'],'license':manifest['license'],
        'label_definition':manifest['label_definition'], 'horizon_months':12,
        'label_maturity':('SYNTHETIC_SIMULATION' if manifest['synthetic'] else
            '12_MONTH_WINDOW_CHECKED_AGAINST_DECLARED_OBSERVATION_END_DATE'),
        'data_sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),
        'decision_date_ranges':{s:[str(decision_dates.iloc[ix].min()),str(decision_dates.iloc[ix].max())]
                                for s,ix in sections.items()},
        'features':manifest['features'],
        'splits':{'train':len(sections['train']),'validation':len(sections['validation']),'test':len(sections['test'])},
        'validation':report(sections['validation'],val_p), 'holdout_test':report(sections['test'],test_p),
        'training_timestamp':datetime.now(timezone.utc).isoformat(),
        'limitations':['No causal inference or fairness certification',
                       'No automatic production deployment',
                       'Needs independent model-risk, data-rights and subgroup validation',
                       'Not a verified mortgage default predictor when trained on synthetic data']}
    artifact = {'features':manifest['features'], 'imputation_medians':imp.statistics_.tolist(),
                'scale_means':scaler.mean_.tolist(), 'scale_stds':scaler.scale_.tolist(),
                'weights':model.coef_[0].tolist(),'intercept':float(model.intercept_[0]),
                'evaluation':report_data}
    # JSON rather than pickle keeps this artifact inert when inspected.
    output.write_text(json.dumps(artifact,indent=2,sort_keys=True),encoding='utf-8')
    return report_data


def predict_one(artifact: dict, features: dict) -> float:
    """Pure mathematical inference for offline evaluation. Never used for loan decisions."""
    x = []
    for key, med, avg, scale in zip(artifact['features'], artifact['imputation_medians'],
                                    artifact['scale_means'], artifact['scale_stds']):
        value = features.get(key, med)
        number = float(med if value is None else value)
        if not math.isfinite(number):
            raise ValueError('Non-finite inference input')
        x.append((number-avg)/scale)
    z = artifact['intercept'] + sum(w*v for w,v in zip(artifact['weights'],x))
    return 1 / (1+math.exp(-max(-700,min(700,z))))


def main():
    parser=argparse.ArgumentParser(description='Offline mortgage risk research: not for live decisions')
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(train(args.data,args.manifest,args.output),indent=2))

if __name__=='__main__':
    main()
