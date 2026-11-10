"""Integrity-pinned, synthetic-only research model preview and drift diagnostics.

This module is deliberately NOT imported by the deterministic decision engine.
It never loads pickle, accepts arbitrary model upload, or persists borrower data.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from bisect import bisect_right
from pathlib import Path
from typing import Any

from .risk_monitor import population_stability_index
from .risk_training import ARTIFACT_VERSION, DEFAULT_FEATURES, predict_details

MAX_ARTIFACT_BYTES = 512_000


class ResearchModelUnavailable(ValueError):
    """A research model is unconfigured, untrusted or malformed."""


def load_pinned_research_model() -> tuple[dict, str]:
    """Require operator-owned file path + sha256. Even valid models remain demo only."""
    if os.getenv('APP_ENV','development') == 'production':
        raise ResearchModelUnavailable('Research preview disabled in production')
    path=os.getenv('AADHARSHILA_RESEARCH_MODEL_PATH','').strip()
    expected=os.getenv('AADHARSHILA_RESEARCH_MODEL_SHA256','').strip().lower()
    if not path or not expected:
        raise ResearchModelUnavailable('Configure a synthetic research artifact and its SHA-256 digest')
    if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
        raise ResearchModelUnavailable('Invalid pinned SHA-256 digest')
    try:
        artifact_path=Path(path)
        if artifact_path.is_symlink() or not artifact_path.is_file() or artifact_path.stat().st_size>MAX_ARTIFACT_BYTES:
            raise ResearchModelUnavailable('Research artifact is missing or oversized')
        raw=artifact_path.read_bytes()
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(),expected):
            raise ResearchModelUnavailable('Research artifact integrity mismatch')
        artifact=json.loads(raw)
        validate_research_artifact(artifact)
        return artifact,expected
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ResearchModelUnavailable('Research artifact cannot be read') from exc


def validate_research_artifact(a: Any, *, allow_external_offline: bool = False) -> None:
    if not isinstance(a,dict) or a.get('artifact_format')!=ARTIFACT_VERSION:
        raise ResearchModelUnavailable('Unsupported research artifact format')
    report=a.get('evaluation',{})
    if not isinstance(report,dict) or report.get('deployment_status')!='NOT_AUTHORIZED':
        raise ResearchModelUnavailable('Research model must remain not authorized for deployment')
    if report.get('synthetic') is True and report.get('capability')=='SYNTHETIC_EVALUATION_ONLY':
        pass
    elif (allow_external_offline and report.get('synthetic') is False and
          report.get('capability')=='EXTERNAL_DATA_EVALUATION_PENDING_INDEPENDENT_REVIEW'):
        pass
    else:
        raise ResearchModelUnavailable('Only non-authorized synthetic research models are allowed in the application')
    if not isinstance(a.get('parameter_sha256'),str) or len(a['parameter_sha256'])!=64:
        raise ResearchModelUnavailable('Model parameter fingerprint missing')
    keys=a.get('features')
    if (not isinstance(keys,list) or not keys or len(keys)!=len(set(keys)) or
        not set(keys).issubset(DEFAULT_FEATURES) or
        (not allow_external_offline and len(keys)!=len(DEFAULT_FEATURES))):
        raise ResearchModelUnavailable('Research model feature contract mismatch')
    for field in ['imputation_medians','scale_means','scale_stds','weights']:
        vals=a.get(field)
        if not isinstance(vals,list) or len(vals)!=len(keys) or any(
            isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vals):
            raise ResearchModelUnavailable('Invalid numeric preprocessing or weight values')
    if any(x<=0 for x in a['scale_stds']):
        raise ResearchModelUnavailable('Non-positive scaling parameter')
    core={key:a[key] for key in ['artifact_format','features','imputation_medians',
         'scale_means','scale_stds','weights','intercept','calibration']}
    computed=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),
                                       allow_nan=False).encode('utf-8')).hexdigest()
    if not hmac.compare_digest(computed,a['parameter_sha256']):
        raise ResearchModelUnavailable('Model parameter digest mismatch')
    cal=a.get('calibration',{})
    if not isinstance(cal,dict) or cal.get('method')!='PLATT_VALIDATION_ONLY':
        raise ResearchModelUnavailable('Research calibration metadata missing')
    values=[a.get('intercept'),cal.get('slope'),cal.get('intercept'),a.get('training_prevalence')]
    if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in values):
        raise ResearchModelUnavailable('Invalid inference parameters')
    if not 0 <= a['training_prevalence'] <= 1:
        raise ResearchModelUnavailable('Invalid training prevalence')
    for key in keys:
        bounds=a.get('feature_bounds',{}).get(key,{})
        distribution=a.get('reference_distributions',{}).get(key,{})
        if not isinstance(bounds,dict) or not all(t in bounds for t in ['p01','p99']):
            raise ResearchModelUnavailable('Missing reference quantiles')
        if not isinstance(distribution,dict) or len(distribution.get('interior_edges',[]))!=4 or len(distribution.get('counts',[]))!=5:
            raise ResearchModelUnavailable('Invalid reference drift bins')
        edges,counts=distribution['interior_edges'],distribution['counts']
        if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in edges) or edges!=sorted(edges):
            raise ResearchModelUnavailable('Invalid reference drift edges')
        if any(type(x)!=int or x<0 for x in counts) or sum(counts)<100:
            raise ResearchModelUnavailable('Insufficient reference drift observations')


def model_status() -> dict:
    artifact,digest=load_pinned_research_model()
    report=artifact['evaluation']
    return {'status':'SYNTHETIC_RESEARCH_READY', 'artifact_sha256':digest,
            'model_family':report['model_family'],'features':list(artifact['features']),
            'holdout_test':report['holdout_test'],
            'holdout_constant_prevalence_baseline':report['holdout_constant_prevalence_baseline'],
            'model_activated':False,'production_authorized':False,
            'training_reference':'SYNTHETIC_OUTCOMES',
            'note':'Holdout values measure invented labels, never observed mortgage defaults.'}


def preview(features: dict) -> dict:
    artifact,digest=load_pinned_research_model()
    try:result=predict_details(artifact,features)
    except (ValueError,KeyError,TypeError,OverflowError) as exc:raise ValueError(str(exc)) from exc
    return {**result,'artifact_sha256':digest,'model_activated':False,
            'training_reference':'SYNTHETIC_OUTCOMES',
            'disclaimer':'Research-only synthetic-label score. Not validated for real borrowers, nor used for approval, pricing, denial or referral.'}


def research_drift(rows: list[dict]) -> dict:
    artifact,digest=load_pinned_research_model()
    features=artifact['features']
    if not 100<=len(rows)<=2000:raise ValueError('Drift review requires 100-2000 synthetic rows')
    results={}
    for key in features:
        samples=[]
        for row in rows:
            if not isinstance(row,dict) or set(row)!=set(features):
                raise ValueError('Drift rows must contain exactly the configured research features')
            raw=row[key]
            if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw) or raw<0 or raw>5:
                raise ValueError('Invalid synthetic monitoring values')
            samples.append(raw)
        ref=artifact['reference_distributions'][key]
        counts=[0]*5
        for value in samples:
            counts[bisect_right(ref['interior_edges'],value)]+=1
        results[key]={**population_stability_index(ref['counts'],counts),
                      'reference_counts':ref['counts'],'observed_counts':counts}
    return {'status':'SYNTHETIC_DRIFT_REPORT', 'artifact_sha256':digest,
            'features':results,'assessment_effect':'NONE',
            'note':'Population Stability Index measures only distribution shift; it is not credit model accuracy, fairness, or an automatic retraining trigger.'}
