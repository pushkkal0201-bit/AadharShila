"""Bounded real-HTTP synthetic load smoke, not a capacity certification.

Captures distributions for a specified machine, process and workload. Does not
compare against invented production SLAs or contact any outside service.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]


def percentile(values:list[float],percent:float)->float:
    if not values:raise ValueError('No latency measurements')
    ordered=sorted(values)
    index=(len(ordered)-1)*percent
    left=int(index);right=min(len(ordered)-1,left+1)
    return ordered[left]+(ordered[right]-ordered[left])*(index-left)


def measure(requests:int=80,concurrency:int=8)->dict:
    if requests<1 or requests>1000 or concurrency<1 or concurrency>32:
        raise ValueError('Benchmark workload outside bounded development range')
    with tempfile.TemporaryDirectory(prefix='aadharshila-load-') as temporary:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'DATABASE_URL':'sqlite:///'+str(Path(temporary)/'benchmark.sqlite'),
             'UPLOAD_DIR':str(Path(temporary)/'documents'),'SEED_DEMO':'true','APP_ENV':'development',
             'PYTHONPATH':str(ROOT/'src')}
        process=subprocess.Popen([sys.executable,'-m','uvicorn','aadharshila.main:app','--host','127.0.0.1',
                           '--port',str(port)],env=env,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        url=f'http://127.0.0.1:{port}'
        try:
            with httpx.Client(base_url=url,timeout=8.0) as client:
                for _ in range(100):
                    try:
                        if client.get('/health/ready').status_code==200:break
                    except httpx.RequestError:pass
                    time.sleep(.1)
                else:raise RuntimeError('API startup failed')
                auth=client.post('/api/v1/auth/login',json={'username':'analyst','password':'Demo@12345'})
                auth.raise_for_status()
                def run_one(i):
                    start=time.perf_counter()
                    try:
                        response=client.get('/api/v1/applications?limit=20')
                        return (response.status_code,time.perf_counter()-start)
                    except httpx.RequestError:
                        return (0,time.perf_counter()-start)
                began=time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                    results=list(executor.map(run_one,range(requests)))
                elapsed=time.perf_counter()-began
            durations=[duration*1000 for code,duration in results]
            failures=sum(code!=200 for code,_ in results)
            return {'workload':'GET /api/v1/applications?limit=20 with demo analyst cookie',
                    'source':'SYNTHETIC_LOCAL_INTEGRATION_TEST','os':platform.system(),
                    'python':platform.python_version(),'requests':requests,'concurrency':concurrency,
                    'failed_requests':failures,'duration_s':round(elapsed,4),
                    'request_rate_per_s':round(requests/elapsed,2),
                    'latency_ms':{'p50':round(percentile(durations,.50),3),
                                  'p95':round(percentile(durations,.95),3),
                                  'p99':round(percentile(durations,.99),3),
                                  'max':round(max(durations),3)},
                    'limitations':['SQLite local database and synthetic data',
                                   'No external provider calls','No cloud or network latency',
                                   'Not a production SLA or capacity certification']}
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':
    args=argparse.ArgumentParser()
    args.add_argument('--requests',type=int,default=80)
    args.add_argument('--concurrency',type=int,default=8)
    opts=args.parse_args()
    result=measure(opts.requests,opts.concurrency)
    print(json.dumps(result,indent=2))
    if result['failed_requests']:raise SystemExit(1)
