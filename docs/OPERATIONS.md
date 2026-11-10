# Operations runbook

## Local development

```bash
pip install -r requirements.txt
pip install --no-deps -e .
export DATABASE_URL=sqlite:///./aadharshila.db
alembic upgrade head
uvicorn aadharshila.main:app --host 127.0.0.1 --port 8000
```

Endpoints: `/` browser, `/docs` OpenAPI, `/health/live` liveness, `/health/ready` database readiness. On first start in development, synthetic fixtures are seeded once. `APP_ENV=production` disables automatic seeding and requires a non-development `SESSION_SECRET`; a full production user-provisioning mechanism is not included.

## Docker Compose (instructions supplied; NOT exercised here)

```bash
cp .env.example .env
# Modify SESSION_SECRET in .env and appropriate deployment settings.
docker compose up --build -d
docker compose logs -f api worker
docker compose ps
```

Requires Docker Engine and Compose. The Compose definition uses PostgreSQL 16 and a separate reassessment worker, with a migration during API startup. Persistent volumes: `pgdata` and `documents`.

## Explicit asynchronous jobs

An authorized analyst can issue `POST /api/v1/applications/{id}/queue-reassessment` and poll `GET /api/v1/jobs/{job_id}`. Run worker separately with `python -m aadharshila.worker` in SQLite mode. Jobs are tied to a specific input revision and supersede themselves when that revision is outdated. Reattempted failures are bounded; stale `RUNNING` jobs older than 60 seconds are reclaimed.

## Seed / reset

The startup seed is idempotent. Never reset a database with real user information. To create a fresh **development-only SQLite** dataset, stop the app and worker, back up any data needed, then initialize a **new** file by setting `DATABASE_URL=sqlite:///./fresh-demo.db`, running `alembic upgrade head`, and restarting. The application then seeds that new database. No destructive public reset API is provided.

## Backups and restore

SQLite development:

```bash
# Stop API and worker before copying
cp aadharshila.db aadharshila.backup.db
# restore to a new disposable path; do not overwrite an active database
```

PostgreSQL Compose:

```bash
docker compose exec -T db pg_dump -U aadharshila -d aadharshila -Fc > aadharshila.dump
# Restore only to a carefully identified, empty/recovery database:
# pg_restore --clean --if-exists --dbname=<recovery_database> aadharshila.dump
```

Document volume must be backed up separately and kept in sync with database references. Backup **commands supplied, not exercised or integrity-verified**.

## Troubleshooting

- `401`: authenticate, inspect session expiry.
- `403`: verify the role, borrower ownership and `X-CSRF-Token` for cookie-backed POST/PATCH.
- `REFER`: inspect `result.reasons` and corresponding review tasks; do not treat it as a failed request.
- A `FAILED` evidence source is unresolved, not a valid pass.
- Migration error: inspect `alembic current` and database connection; avoid `drop_all` or destructive schema operations.
- Queued job not advancing: ensure the worker process is running and the database is reachable.
- Container build: requires package registry access; offline images need an internal package mirror.

## Rollback

Database schema changes should use reviewed versioned migrations with backups and a planned forward/backward compatibility window. Historical decision snapshots must not be deleted or silently rewritten. No rollback or restore drill was performed in this authoring environment.

## Additional development recovery and provider notes

Use `python -m aadharshila.recovery backup/verify/restore` for SQLite on either Windows or Linux; see `docs/RECOVERY_DRILL.md`. Docker Compose PostgreSQL backup/drill scripts are `scripts/docker_backup.sh` and `scripts/docker_restore_drill.sh` and run in GitHub CI. Untrusted providers cannot be enabled by specifying arbitrary URLs through an API; the signed partner contract is configured through environment variables and a strict HTTPS host allowlist. See `docs/PROVIDER_ONBOARDING.md`.

`APP_ENV=production` enforces a governance referral condition; no actual approval is permitted by the current code even if all evidence flags read LIVE. Independent lender-policy, legal and security authorizations remain unfulfilled.

## Engineering checkpoint: SSO, metrics and recovery

- Browser SSO uses the lender-controlled pinned OIDC issuer (`OIDC_AUTHORIZATION_ENDPOINT`, `OIDC_TOKEN_ENDPOINT`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`) and a pinned local JWKS. The registered redirect path is `/api/v1/auth/oidc/callback`; no remote role claims create accounts. See `ENGINEERING_RELEASE_2026-11-10.md`.
- Metrics exporter: `GET /internal/metrics` returns only route-template counters and request durations when `METRICS_ACCESS_TOKEN` (minimum 24 characters) is supplied through `X-Metrics-Token`. Without configuration it returns 503. Staff-only process metrics are at `/api/v1/operations/http-metrics`. Metrics are process-local, not aggregated across workers, and do not represent production SLOs. Expose only on an internal access-controlled network.
- HTTP load smoke: `python scripts/http_benchmark.py --requests 60 --concurrency 6` starts an isolated synthetic database and measures authenticated real HTTP requests. No production traffic is involved.
- Browser E2E: `python scripts/browser_smoke.py` requires `playwright` and Chromium; hosted GitHub Actions runs this separately. Do not claim browser approval without reading the current job results.
- The development PostgreSQL restore script now compares the SHA-256 of each restored document object to the checksum stored in the restored database, in addition to checking archive checksums and restoring the database into a disposable name. It does **not** prove a production-consistent point-in-time backup, exercise KMS recovery, or establish an RPO/RTO. Coordinate write freezes or transaction-consistent snapshots for an institutional DR plan.
- `infra/compose.production.example.yml` is deliberately an illustration requiring a managed DB, approved identity provider, restricted host-mounted keys, ClamAV socket, TLS reverse proxy, network segmentation and external monitoring. Never deploy the demonstration password accounts or synthetic integrations to borrowers.
