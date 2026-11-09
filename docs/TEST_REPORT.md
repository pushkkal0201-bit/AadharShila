# Local test and inspection report

**Environment:** Python 3.13.5, FastAPI 0.128.2, SQLAlchemy 2.0.50, pytest 9.0.2. Local SQLite file plus isolated temporary SQLite test database. Chromium executable present; direct browser navigation was blocked by the runtime administrator policy. Static browser rendering using authenticated API data injection was successful without page errors.

## Executed checks

| Validation | Status | Notes |
| --- | --- | --- |
| Financial calculation unit tests | PASS | EMI, zero-rate, negative/invalid terms, FOIR, LTV, reverse principal, alternatives, stress comparisons |
| Deterministic decision unit tests | PASS | Mandatory gaps, conflicting income, terminal failure precedence, screening potential match, expired income, revoked consent |
| API integration tests | PASS | Authentication/CSRF, access boundaries, fixture cases, evidence revisions, history/diff/replay, authenticated document download and hash integrity, evidence request ranking, redacted borrower reports |
| Policy governance tests | PASS | Separate policy-author and approver, validation, simulation without historical mutation |
| Background worker tests | PASS | Stale revision supersession and queued-reassessment completion |
| Browser JS syntax check | PASS | `node --check web/app.js` |
| HTTP smoke | PASS | `GET /`, `/health/live`, `/health/ready`, authenticated list and case detail |
| Full browser user journey | NOT VERIFIED | Browser navigation denied `net::ERR_BLOCKED_BY_ADMINISTRATOR`; not a full user journey |
| Static Chromium layout inspection | PASS (limited) | HTML/CSS/JS rendered with authenticated case data injected; overview/queue/decision screenshots captured and no JS page errors |
| Windows D: drive startup | NOT TESTED | PowerShell/Batch launchers added and source-inspected; no Windows runtime available |
| Docker Compose deployment | NOT TESTED | Docker executable not available in authoring environment |
| Real provider calls | NOT TESTED | All provider categories are synthetic fixtures only |
| Real-world model quality | NOT APPLICABLE | No trained credit-default model |
| Independent security audit | NOT PERFORMED | Functional security tests are not a penetration test |

Tests use the actual service and persistence pipeline. The suite must be re-run after material code changes; the numerical result in the final handoff reflects the latest run, not a hypothetical future CI result.

## Reproduction

```bash
PYTHONPATH=src pytest -q --disable-warnings
node --check web/app.js
```

### Important limits

**Latest suite:** 42 tests passed (2026-11-10, local Linux Python 3.13.5). **Measured engine-only performance:** 480 evaluations, median 0.1274 ms, p95 0.4416 ms, 0 outcome mismatches in the authoring environment. This is *not* HTTP, database, provider or complete underwriting turnaround time; machine and workload are recorded in `docs/benchmark-local.json`.

Synthetic fixtures guarantee repeatability, **not** representative operational accuracy. Fixture results are not a substitute for licensed bureau data, regulator acceptance, or applicable lender policy. No latency or throughput measurements are presented as production performance.
