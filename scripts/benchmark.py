"""Measure the pure deterministic evaluation function, not provider or HTTP latency.

Run: PYTHONPATH=src python scripts/benchmark.py
"""
import json,platform,statistics,time
from sqlalchemy import select
from aadharshila.db import SessionLocal
from aadharshila.models import Assessment
from aadharshila.engine import evaluate

with SessionLocal() as db:
    cases=db.scalars(select(Assessment).order_by(Assessment.created_at).limit(16)).all()
if not cases:raise SystemExit('No stored assessments. Start the development application to seed.')
# Warmup for module and interpreter effects, excluding it from measurements.
for a in cases:
    evaluate(a.snapshot['input'],a.snapshot['policy'])
samples=[];mismatches=0
for _ in range(30):
    for a in cases:
        begin=time.perf_counter_ns()
        res=evaluate(a.snapshot['input'],a.snapshot['policy'])
        samples.append((time.perf_counter_ns()-begin)/1_000_000)
        mismatches+=res['outcome']!=a.outcome
samples.sort()
report={
    'workload':'In-process pure deterministic underwriting engine; no I/O, web, queue or real providers',
    'machine':platform.platform(), 'python':platform.python_version(), 'case_count':len(cases),
    'total_evaluations':len(samples), 'median_ms':round(statistics.median(samples),4),
    'p95_ms':round(samples[int(.95*(len(samples)-1))],4),
    'max_ms':round(max(samples),4),'outcome_mismatches':mismatches,
    'important_limit':'Not an HTTP endpoint or production STP latency benchmark.'}
print(json.dumps(report,indent=2))
