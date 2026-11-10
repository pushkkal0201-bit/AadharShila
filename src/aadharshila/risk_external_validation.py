"""Independent, offline, out-of-time evaluation of a research mortgage model.

This module cannot certify legal data rights, independence, fairness or lender use.
It never serves a model, changes underwriting decisions or stores individual rows.
No real borrower dataset is included in this repository.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .risk_monitor import population_stability_index
from .risk_serving import MAX_ARTIFACT_BYTES, validate_research_artifact
from .risk_training import _atomic_json, _metrics, calibration_table, expected_calibration_error


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_model(artifact_path: Path, expected_digest: str) -> tuple[dict, str]:
    """Fail closed on missing operator digest, symlink, malformed or oversized artifact."""
    if (len(expected_digest) != 64 or any(c not in '0123456789abcdef' for c in expected_digest.lower())):
        raise ValueError('An exact 64-character pinned artifact SHA-256 is required')
    if artifact_path.is_symlink() or not artifact_path.is_file() or artifact_path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError('Research artifact is missing, symbolic or oversized')
    raw = artifact_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_digest.lower():
        raise ValueError('Research artifact SHA-256 mismatch')
    try:
        artifact = json.loads(raw)
        validate_research_artifact(artifact, allow_external_offline=True)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid research artifact') from exc
    return artifact, digest


def _validate_evaluation_manifest(meta: dict, artifact: dict) -> None:
    required_strings = ['dataset_id', 'source', 'license', 'permission', 'label_definition',
                        'decision_date_column', 'borrower_id_column']
    if not isinstance(meta, dict) or any(not isinstance(meta.get(k), str) or not meta[k].strip()
                                         for k in required_strings):
        raise ValueError('Independent evaluation manifest requires dataset ID, provenance, rights and schema')
    if meta.get('horizon_months') != 12 or isinstance(meta.get('horizon_months'), bool):
        raise ValueError('Independent evaluation requires the same 12-month outcome horizon')
    if not isinstance(meta.get('synthetic'), bool) or meta['synthetic'] != artifact['evaluation']['synthetic']:
        raise ValueError('Model and evaluation cohorts must share synthetic/real-data status')
    if meta.get('independent_of_training_declared') is not True:
        raise ValueError('Independent cohort declaration is required and needs separate audit')
    if meta.get('features') != artifact['features']:
        raise ValueError('Independent cohort features must match the pinned model in the exact order')
    if meta.get('decision_date_column') == meta.get('borrower_id_column'):
        raise ValueError('Decision date and borrower ID cannot be the same column')
    if not meta['synthetic'] and (not isinstance(meta.get('observation_end_date'), str) or not meta['observation_end_date'].strip()):
        raise ValueError('Real evaluation cohorts require a documented observation_end_date')
    group = meta.get('segment_column')
    if group is not None and (not isinstance(group,str) or not group.strip() or
                              group in {*artifact['features'], meta['decision_date_column'],
                                        meta['borrower_id_column'], 'default_12m'}):
        raise ValueError('Segment column must be distinct from decision and model fields')


def _bootstrap(y, probabilities, *, seed: int, replications: int) -> dict:
    """Stratified resampling preserves rare class counts; descriptive uncertainty only."""
    import numpy as np
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

    actual = np.asarray(y, dtype=int)
    scores = np.asarray(probabilities, dtype=float)
    rng = np.random.default_rng(seed)
    neg = np.flatnonzero(actual == 0)
    pos = np.flatnonzero(actual == 1)
    metrics = {'roc_auc': [], 'average_precision': [], 'brier_score': [], 'expected_calibration_error': []}
    for _ in range(replications):
        take = np.concatenate((rng.choice(neg, len(neg), replace=True), rng.choice(pos, len(pos), replace=True)))
        yy, pp = actual[take], scores[take]
        metrics['roc_auc'].append(float(roc_auc_score(yy, pp)))
        metrics['average_precision'].append(float(average_precision_score(yy, pp)))
        metrics['brier_score'].append(float(brier_score_loss(yy, pp)))
        metrics['expected_calibration_error'].append(expected_calibration_error(calibration_table(yy, pp)))
    return {name: {'lower_95pct': round(float(np.quantile(samples, .025)), 6),
                   'upper_95pct': round(float(np.quantile(samples, .975)), 6)}
            for name, samples in metrics.items()}


def _drift(artifact: dict, frame, features: list[str]) -> dict:
    import numpy as np
    results = {}
    for name in features:
        raw = frame[name]
        ref = artifact['reference_distributions'][name]
        counts = [0] * 5
        # Missing values are imputed using training-only reference medians.
        med = float(artifact['imputation_medians'][features.index(name)])
        for value in raw:
            numeric = med if not np.isfinite(value) else float(value)
            counts[bisect_right(ref['interior_edges'], numeric)] += 1
        results[name] = {**population_stability_index(ref['counts'], counts),
                         'observed_counts': counts, 'reference_counts': ref['counts']}
    return results


def evaluate_external(artifact_file: Path, *, expected_artifact_sha256: str, data_file: Path,
                      manifest_file: Path, output: Path, bootstrap_seed: int = 42,
                      bootstrap_replicates: int = 200) -> dict:
    """Evaluate a pinned model on strictly later, independently supplied matured outcomes.

    'Independent' and rights status are assertions in a manifest, not verified certificates.
    The score remains a research metric even if software checks all pass.
    """
    import numpy as np
    import pandas as pd

    if not 100 <= bootstrap_replicates <= 2000:
        raise ValueError('Bootstrap replicates must be between 100 and 2000')
    artifact_file, data_file, manifest_file, output = map(Path, [artifact_file,data_file,manifest_file,output])
    artifact, artifact_sha = _load_model(artifact_file,expected_artifact_sha256)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    _validate_evaluation_manifest(manifest, artifact)
    data_sha = _file_digest(data_file)
    if data_sha == artifact['evaluation'].get('data_sha256'):
        raise ValueError('Evaluation data cannot be the model training/evaluation source file')
    frame = pd.read_csv(data_file)
    features = list(artifact['features'])
    date_key, id_key = manifest['decision_date_column'], manifest['borrower_id_column']
    needed = {*features, date_key, id_key, 'default_12m'}
    if manifest.get('segment_column'):
        needed.add(manifest['segment_column'])
    if not needed.issubset(frame.columns):
        raise ValueError('Evaluation cohort missing columns: ' + str(sorted(needed-set(frame.columns))))
    if len(frame) < (100 if manifest['synthetic'] else 300):
        raise ValueError('External evaluation cohort is too small for the configured research protocol')
    if frame[id_key].isna().any() or frame[id_key].astype(str).str.strip().eq('').any() or frame[id_key].duplicated().any():
        raise ValueError('Evaluation cohort has missing or repeated borrower IDs')
    dates = pd.to_datetime(frame[date_key], utc=True, errors='coerce')
    if dates.isna().any():
        raise ValueError('Invalid evaluation decision dates')
    train_last = pd.to_datetime(artifact['evaluation']['decision_date_ranges']['test'][1],utc=True)
    if dates.min() <= train_last:
        raise ValueError('External evaluation must begin strictly after model development holdout')
    if not manifest['synthetic']:
        observation_end = pd.to_datetime(manifest['observation_end_date'], utc=True, errors='coerce')
        if pd.isna(observation_end) or (dates + pd.DateOffset(months=12) > observation_end).any():
            raise ValueError('All real labels require a mature 12-month observation window')
    label = pd.to_numeric(frame['default_12m'], errors='coerce')
    if label.isna().any() or not set(label.unique()) <= {0,1}:
        raise ValueError('Evaluation labels must be observed binary 12-month outcomes')
    y = label.astype(int).to_numpy()
    counts = np.bincount(y,minlength=2)
    if min(counts) < 10:
        raise ValueError('Insufficient event/non-event representation in the evaluation cohort')
    matrix = frame[features].apply(pd.to_numeric, errors='coerce')
    if np.isinf(matrix.to_numpy()).any():
        raise ValueError('Infinite feature values are not supported')
    if matrix.isna().all(axis=0).any():
        raise ValueError('Cannot independently assess a feature with no measured values')
    matrix_values = matrix.to_numpy(dtype=float)
    valid_numbers = matrix_values[np.isfinite(matrix_values)]
    if np.any((valid_numbers < 0) | (valid_numbers > 5)):
        raise ValueError('Feature outside documented [0,5] research inference contract')
    # Evaluate the pinned model at full floating-point precision, without retraining.
    probabilities = []
    for _,row in matrix.iterrows():
        contribution = 0.0
        for j, name in enumerate(features):
            raw = row[name]
            x = artifact['imputation_medians'][j] if pd.isna(raw) else float(raw)
            contribution += artifact['weights'][j] * (x-artifact['scale_means'][j])/artifact['scale_stds'][j]
        from .risk_training import sigmoid, logit
        raw_p = sigmoid(artifact['intercept']+contribution)
        calibration = artifact['calibration']
        probabilities.append(sigmoid(calibration['slope']*logit(raw_p)+calibration['intercept']))
    evaluated = _metrics(y,probabilities)
    baseline = [artifact['training_prevalence']] * len(y)
    baseline_metrics = _metrics(y,baseline)
    missingness = {name: round(float(matrix[name].isna().mean()),6) for name in features}
    drift = _drift(artifact,matrix,features)
    groups = {}
    segment_col = manifest.get('segment_column')
    if segment_col:
        for cohort, idx in frame.groupby(segment_col,dropna=False).groups.items():
            ix = np.array(list(idx))
            # Suppress all small segments and unstable single-class metrics.
            if len(ix) < 50 or min(np.bincount(y[ix],minlength=2)) < 5:
                continue
            group_name = str(cohort)
            if len(group_name)>64: raise ValueError('Segment label exceeds 64 characters')
            groups[group_name] = _metrics(y[ix],[probabilities[j] for j in ix])
    result = {
        'status':'OFFLINE_EXTERNAL_RESEARCH_EVALUATION_ONLY',
        'model_activated':False,'decision_use':False,'independent_validation_completed':False,
        'artifact_sha256':artifact_sha,'data_sha256':data_sha,
        'manifest_sha256':_file_digest(manifest_file),'dataset_id':manifest['dataset_id'],
        'source':manifest['source'], 'synthetic':manifest['synthetic'],
        'declared_independent_of_training':True,
        'earliest_decision_date':str(dates.min().date()),'latest_decision_date':str(dates.max().date()),
        'reference_holdout_end':str(train_last.date()),
        'label_definition':manifest['label_definition'],'horizon_months':12,
        'outcome_prevalence':round(float(np.mean(y)),6),
        'metrics':evaluated,'constant_training_prevalence_baseline':baseline_metrics,
        'metric_differences_from_baseline':{
            'brier_score':round(evaluated['brier_score']-baseline_metrics['brier_score'],6),
            'log_loss':round(evaluated['log_loss']-baseline_metrics['log_loss'],6)},
        'bootstrap_95pct':_bootstrap(y,probabilities,seed=bootstrap_seed,replications=bootstrap_replicates),
        'input_missingness':missingness,'feature_drift_psi':drift,
        'review_only_group_metrics':groups,
        'limitations':[
            'No data rights, identity, borrower overlap or independently supplied label provenance can be verified from manifest declarations alone',
            'No rejection bias, data selection effects, causal explanation, subgroup fairness, or deployment approval is established',
            'A temporal holdout is not an independent institutional model validation',
            'US public mortgage loan performance data may be structurally unlike Indian Home Loan and LAP applicant data',
            'No real-world model is approved for serving, loan decisions, sanction or disbursement'
        ],
        'report_created_at':datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(output,result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Evaluate an OFFLINE research model on a strictly later, separately supplied labeled cohort')
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--sha256',required=True,help='Pinned artifact digest, computed separately by the operator')
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bootstrap-seed',type=int,default=42)
    parser.add_argument('--bootstrap-replicates',type=int,default=200)
    args = parser.parse_args()
    report=evaluate_external(args.artifact,expected_artifact_sha256=args.sha256,data_file=args.data,
                            manifest_file=args.manifest,output=args.output,
                            bootstrap_seed=args.bootstrap_seed,bootstrap_replicates=args.bootstrap_replicates)
    print(json.dumps({'status':report['status'],'n':report['metrics']['n'],
                      'roc_auc':report['metrics']['roc_auc'],
                      'brier_score':report['metrics']['brier_score'],
                      'model_activated':False,'report':str(args.output)},indent=2))

if __name__ == '__main__':
    main()
