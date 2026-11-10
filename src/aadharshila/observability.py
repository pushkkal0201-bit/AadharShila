"""Bounded process-local HTTP counters without borrower identity or path parameters.

For production use a metrics agent and central log aggregation; this module
cannot provide cross-worker or persistent service-level measurements.
"""
from __future__ import annotations
from collections import defaultdict
from threading import Lock

BUCKETS=(.01,.05,.1,.25,.5,1,3,10)
_lock=Lock()
_counters=defaultdict(lambda:{'count':0,'duration_sum':0.0,'buckets':[0]*len(BUCKETS)})


def record(method: str, route: str, status: int, seconds: float) -> None:
    # Only registered template routes may be recorded: never raw borrower IDs.
    if not route.startswith('/') or len(route)>140 or len(_counters)>200:return
    key=(method,route,str(status//100)+'xx')
    with _lock:
        metric=_counters[key]
        metric['count']+=1
        metric['duration_sum']+=max(0.0,seconds)
        for i,bound in enumerate(BUCKETS):
            if seconds<=bound:metric['buckets'][i]+=1


def snapshot() -> dict:
    with _lock:
        return {f'{method} {route} {kind}':{'requests':v['count'],
                'duration_seconds_total':round(v['duration_sum'],6)}
                for (method,route,kind),v in _counters.items()}


def prometheus() -> str:
    lines=['# HELP aadharshila_http_requests_total HTTP requests by registered route and status class',
           '# TYPE aadharshila_http_requests_total counter',
           '# HELP aadharshila_http_duration_seconds_total Request duration per registered route',
           '# TYPE aadharshila_http_duration_seconds_total counter']
    with _lock:
        for (method,route,klass),m in sorted(_counters.items()):
            labels=f'method="{method}",route="{route}",status_class="{klass}"'
            lines.append(f'aadharshila_http_requests_total{{{labels}}} {m["count"]}')
            lines.append(f'aadharshila_http_duration_seconds_total{{{labels}}} {m["duration_sum"]:.6f}')
    return '\n'.join(lines)+'\n'
