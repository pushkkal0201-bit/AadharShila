"""Reproducible independent-date synthetic cohort exercise; no borrower data."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

from .risk_external_validation import evaluate_external
from .synthetic_risk_benchmark import generate_synthetic


def run(artifact_file: Path, output_dir: Path, *, rows: int=300, seed: int=99) -> dict:
    import pandas as pd

    if not 300 <= rows <= 20000:
        raise ValueError('Synthetic external cohort requires 300-20000 rows')
    artifact_file = Path(artifact_file)
    artifact = json.loads(artifact_file.read_text(encoding='utf-8'))
    if artifact.get('evaluation',{}).get('synthetic') is not True:
        raise ValueError('Synthetic demonstration requires a synthetic-trained research artifact')
    output_dir = Path(output_dir)
    data, manifest_file = generate_synthetic(output_dir,rows=rows,seed=seed)
    frame = pd.read_csv(data)
    # Strict separation from the model development holdout by time and ID.
    last_date = date.fromisoformat(artifact['evaluation']['decision_date_ranges']['test'][1][:10])
    start = last_date + timedelta(days=400)
    frame['decision_date'] = [(start + timedelta(days=i)).isoformat() for i in range(rows)]
    frame['review_segment'] = ['synthetic_A' if i%2 else 'synthetic_B' for i in range(rows)]
    frame.to_csv(data,index=False)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    manifest.update(dataset_id=f'SYNTHETIC_INDEPENDENT_GENERATOR_SEED_{seed}',
                    independent_of_training_declared=True,
                    segment_column='review_segment')
    manifest_file.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    report_path=output_dir/'independent_evaluation.json'
    report = evaluate_external(artifact_file,
                               expected_artifact_sha256=hashlib.sha256(artifact_file.read_bytes()).hexdigest(),
                               data_file=data,manifest_file=manifest_file,output=report_path)
    return {'status':'SYNTHETIC_INDEPENDENT_DATE_TEST_ONLY',
            'rows':rows,'seed':seed,'latest_training_test_date':str(last_date),
            'earliest_external_date':report['earliest_decision_date'],
            'roc_auc':report['metrics']['roc_auc'],
            'brier_score':report['metrics']['brier_score'],
            'uncertainty':report['bootstrap_95pct'],
            'model_activated':False,'independent_validation_completed':False,
            'report':str(report_path),
            'note':'All rows and labels are generated. This is NOT genuine independent mortgage validation.'}


def main() -> None:
    p=argparse.ArgumentParser(description='Synthetic external-date validation of a research artifact')
    p.add_argument('--artifact',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--rows',type=int,default=300)
    p.add_argument('--seed',type=int,default=99)
    args=p.parse_args()
    print(json.dumps(run(args.artifact,args.output_dir,rows=args.rows,seed=args.seed),indent=2))

if __name__=='__main__':main()
