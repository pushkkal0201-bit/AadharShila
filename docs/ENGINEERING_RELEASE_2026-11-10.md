# Underwriting platform hardening — engineering checkpoint

Date: 10 November 2026. This checkpoint builds on the encrypted-document release, without changing the institution's legal authorization boundary.

## Delivered in this change set

| Workstream | Implementation | Acceptance evidence | Remaining production dependency |
| --- | --- | --- | --- |
| Document safety | AES-256-GCM document storage already in main; new PDF parsing via `isolated_document_worker.py` with an isolated Python process, bounded document size, process timeout, sanitized environment and POSIX memory/CPU limits | PDF upload and subprocess timeout tests | Separate host/container namespace, seccomp/AppArmor, no-network policy, KMS-managed keys, operational ClamAV and cryptographic issuer signatures |
| Federated browser identity | OIDC authorization-code + PKCE, state and nonce, signed ID-token verification using pinned JWKS, MFA claims, approved subject mapping and opaque revocable session cookies | Signed-token, wrong-state, wrong-nonce, CSRF, logout and account-deactivation tests | Lender-controlled IdP, real registered redirect URL, group provisioning/approvals, IdP account revocation lifecycle and security audit |
| Income reconciliation | Six complete calendar months, duplicate-income suppression, own-account payee conflict, reversals, optional statement-month coverage, volatility and income spike review | New reconciliation unit tests and previous calculation tests | Verified provider categories and account ownership, approved lender aggregation policies and income-review SOPs |
| Credit-policy governance | Stored, fingerprinted impact simulation before approval; separate author and approver; organization-scoped simulation history; audit of approval and activation | Changed-policy fingerprint prevents approval, missing simulation blocks approval; policy/tenant tests | Approved lender rules, independent validation of sampled portfolio and effective-date/change-control board |
| Credit-risk research | Deterministic generator for invented outcome labels, 65/15/20 chronological holdout logistic evaluation, inert JSON model artifact | Synthetic pipeline run (seed 42); repeatability tests | Real legally obtained labeled mortgage outcomes, independent validation, calibration, bias assessment and deployment approval |
| Browser/security/performance | Real Chromium smoke script, auth and CSRF regressions, bounded authenticated-HTTP benchmark and no-PII process metrics | 109 local pytest tests; 60-request local load smoke with no errors | Browser CI job result, controlled external security review, cloud load/fault testing |
| Operating controls | Metrics protected by token; security response headers; production-style Compose illustration; PostgreSQL restore drill checks document bytes against restored metadata | Local tests and Alembic migrations; Docker verification to be read from new CI run | Managed PostgreSQL, vault, ClamAV/IdP, TLS and external monitoring, staged disaster-recovery exercise with agreed RPO/RTO |

## Actual test results

Local environment: Linux, Python 3.13.5, SQLite and synthetic fixtures.

- `PYTHONPATH=src python -m pytest -q`: 109 passed (some deprecation warnings).
- `node --check web/app.js`: passed.
- `DATABASE_URL=sqlite:////tmp/aadharshila-next-migrations.db python -m alembic upgrade head`: passed, revision `4d92b41f8aa7`.
- `python -m aadharshila.synthetic_risk_benchmark --output-dir <temporary>`: completed, 640 synthetic observations, 128 holdout observations, synthetic holdout ROC AUC 0.685803. These are measurements of an invented generator, not real-world mortgage performance.
- `python scripts/http_benchmark.py --requests 60 --concurrency 6`: 60/60 authenticated HTTP GETs succeeded; local p50 24.932 ms, p95 47.596 ms, p99 51.237 ms. This is only a bounded Linux/SQLite synthetic-data smoke, not a production capacity claim.
- `CHROMIUM_PATH=/usr/bin/chromium python scripts/browser_smoke.py`: attempted; local Chromium navigation failed with `ERR_BLOCKED_BY_ADMINISTRATOR`. The browser CI result is not yet known.
- No production container was deployed; the production Compose file is an untested design reference, not a release artifact.

## Commands

From the repository root:

```sh
python -m pip install -r requirements-ml.txt
python -m pip install --no-deps -e .
python -m alembic upgrade head
python -m pytest -q
python -m aadharshila.synthetic_risk_benchmark --output-dir .risk-ci
python scripts/http_benchmark.py --requests 60 --concurrency 6
```

Browser check (requires Chromium and `playwright`):

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python scripts/browser_smoke.py
```

The development application starts with `run.bat` under `D:\Projects\Aadharshila` after `setup.bat`; the new subprocess uses `sys.executable` and absolute module import paths instead of hardcoded `C:` paths.

## OIDC setup contract

Set `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_PATH`, `OIDC_AUTHORIZATION_ENDPOINT`, `OIDC_TOKEN_ENDPOINT`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` and `OIDC_REQUIRE_MFA=true`. Both provider endpoints must share the exact configured issuer hostname and use HTTPS. Production callbacks require an HTTPS redirect whose path is `/api/v1/auth/oidc/callback`. Only subjects manually provisioned to `users.oidc_subject` can log in. Neither the provider's role claims nor self-registration assign lending permissions.

`GET /api/v1/auth/oidc/start` redirects the browser to the IdP with a five-minute signed state/nonce/PKCE cookie. The callback verifies the state, exchanges the code at the configured fixed token endpoint, validates the signed ID token and nonce, and creates a revocable DB session, capped to one hour. Revoked users and sessions are denied. User termination requires an administrator in the same lender organization; an administrator cannot deactivate their own account.

## Document-parser boundary

Parsing occurs in a subprocess with a fresh scratch working directory. Only the bytes of the document and a minimal environment reach it, and stdout is schema-checked and bounded. On POSIX, memory and CPU limits apply. **This is not a kernel sandbox**: a malicious native parser could still access the filesystem under the parent service account. A real deployment must use a separately permissioned parsing container/worker with syscall filtering, non-root UID, enforced no-network access and audited temporary storage. Production uploads already fail closed when malware scanning or encryption is unavailable.

## Security / compliance boundary

No issued lender approvals, KYC credentials, live bureaus, real mortgage-default observations or regulatory sign-offs are included. No binding sanction/disbursement or production PD predictions are enabled. Work with the institution to establish lawful data rights, independent security testing, approved credit rules, property/legal evidence, operational recovery exercises and lender-owned release signers. See `INSTITUTIONAL_GO_LIVE.md`.

### Policy approval notes and organizational audit

Policy approval and activation require a separately recorded, non-empty human justification (12–2000 characters). Events retain the reviewer role, actor ID, policy/simulation reference and a timestamp. Authorized same-organization staff can read these events through `GET /api/v1/operations/governance-audit`; borrowers cannot view the governance audit. Signed institutional approval remains separate from this internal review history.
