# Aadharshila — transaction, document, identity, property and governance stage

Reviewed against the repository baseline as of 10 November 2026. The functions here are engineering controls. They do **not** authorize real borrower onboarding, regulated mortgage approval, legally effective sanctions or disbursement.

## Verified local implementation

| Component | Code / route | Verification | Boundary |
| --- | --- | --- | --- |
| Transaction normalization | `src/aadharshila/income.py`; `POST /api/v1/applications/{id}/income-reconciliation` | Six-month window, self-transfers/loans excluded, duplicates and uncertain rows tracked; unit and API tests | Analyst-submitted preview is not source-verified. A provider-authenticated `bank_transactions` evidence item can reduce, but never increase, accepted income; inadequate coverage routes to REFER. |
| Document intelligence | `documents_pipeline.py`; existing document upload | PDF extraction, OCR option for scanned PDFs, signature-presence signal only | OCR requires optional Tesseract/pdfium and is not issuer authentication; signatures are not cryptographically verified. |
| Malware scanning | ClamAV INSTREAM over Unix socket | Local protocol and failure-path tests | Required for production document uploads; if unavailable, upload fails closed. A real ClamAV daemon and isolated processing are deployment dependencies. |
| Federated API identity | `federated_auth.py`, `security.py`, `oidc_subject` Alembic migration | RSA/JWKS signature, issuer/audience, expiry, MFA/ACR tests | Requires lender-controlled IdP, pinned public keys, separate user provisioning, managed deactivation and a browser SSO UI. Password demo login is disabled in production. |
| Provider extensions | `connectors.py` | Consent scope and provider category tests | CKYCR, DigiLocker, AA, GST, bureau, property registry, CERSAI and RERA are **contract interfaces**, not live provider access. LIVE requires exact provider/category consent and signed response evidence. |
| Property comparables | `property_intelligence.py`; property-preview API | Verified-comparable filter, median/m² and legal-control status | Never claims accepted collateral/title, and does not override professional legal opinions or valuer sign-off. |
| Risk drift | `risk_monitor.py`; feature-drift API | Sample threshold and PSI tests | Research monitoring only; no real model deployed; PSI does not measure fairness or credit accuracy. |
| Regulatory evidence mapping | `compliance_controls.py`; compliance-checks API | Source metadata plus per-case evidence completeness tests | All checks report legal certification **NOT_ASSESSED**; applicability and formal approval remain institutional tasks. |
| Sanction readiness | `sanction.py`; sanction-preview API | API test asserts binding=False and disbursement blocked | No KFS, executed sanction, bank transfer or live disbursement capability. |
| D: drive | Existing Windows relative-path setup | Python tests in local Linux, prior Windows CI on repository baseline | Actual updated Windows CI must pass; OCR scanner Unix socket requires Linux service/container if enabled. |

## Integration boundaries

No official CKYCR, DigiLocker, Account Aggregator, licensed credit bureau, GST, CERSAI, RERA, identity, valuation or sanctions provider account, contract or signed response was available. Configurable gateways use a single internal signed-envelope contract; this does **not** assert that any official provider implements the contract.

For a LIVE provider: authorize borrower consent for `financial_underwriting` with **exact** `provider` and `categories` matching the adapter's name and evidence key, configure approved `AADHARSHILA_PARTNER_<KEY>_URL`, `_TOKEN`, `_HMAC_KEY`, `_NAME`, and whitelist exact host in `AADHARSHILA_PARTNER_ALLOWED_HOSTS`. Only real contracted endpoints should be configured. Production checks remain blocked without institutional signing. No credentials or borrower data are shipped.

## Production authentication

- Run from a PostgreSQL-backed production deployment, with `APP_ENV=production`, `SEED_DEMO=false`, a unique `SESSION_SECRET` of at least 32 characters and proper TLS termination.
- Pin a provider issuer, audience and an operator-managed local JWKS file via `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_PATH`.
- `OIDC_REQUIRE_MFA=true` is the default. If supported by the lender IdP, set `OIDC_REQUIRED_ACR` to the approved authentication-assurance claim.
- A verified OIDC `sub` must map to a manually approved `users.oidc_subject`. No public sign-up or role creation from untrusted token claims.
- This is a **bearer API integration**, not a complete browser redirect/callback session system. Production browser SSO, user provisioning and revocation still require the lender's enterprise IAM.

## OCR and malware services

OCR is opt-in with `ENABLE_DOCUMENT_OCR=true`; install optional `requirements-ocr.txt` and the Tesseract runtime. This is resource-heavy and should run in isolated workers for any real document operation. Use `CLAMAV_UNIX_SOCKET` for an actually reachable ClamAV daemon (typically a Linux sidecar/container). Production document ingestion rejects uploads when a scanner isn't configured, is unavailable, returns an ambiguous result, or finds malware.

## Regulatory research register

Primary RBI references inspected 10 November 2026:

- [Housing Finance Companies Directions, 2025 (updated 1 October 2026)](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12939).
- [Digital Lending Directions, 2025](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12848), especially clauses 7 (creditworthiness), 8 (disclosures), 9 (disbursal/repayment), 12 (data collection) and 13 (data storage).
- [Non-Banking Financial Companies KYC Directions, 2025](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12943), updated version and applicability require lender compliance review.

The executable checks are incomplete administrative evidence-presence controls, not an authoritative interpretation or certification of RBI compliance. There is no RBI-specified universal FOIR/LTV ratio hardcoded in Aadharshila.

## Local test commands

```shell
python -m pip install -r requirements-ml.txt
python -m pip install --no-deps -e .
python -m alembic upgrade head
python -m pytest -q
node --check web/app.js
```

Direct Chromium-to-localhost browser testing was blocked by the authoring environment (`ERR_BLOCKED_BY_ADMINISTRATOR`). Automated API workflows were exercised with FastAPI TestClient. Docker is unavailable locally; the updated repository CI must verify its PostgreSQL recovery job separately.

## Still requires real external action

1. Licensed lender participation and approved credit policies, including two-person overrides and borrower protection controls.
2. Contracts, provider credentials, real consent flows and receipt-of-provider-data audits.
3. Lender-supplied, lawfully usable, matured mortgage performance datasets and independent credit model validation/calibration.
4. Real encrypted object storage, upload sandboxing, validated PDF signing trust chains and issuer verification.
5. Independent security testing, enterprise IAM, production monitoring, tested RPO/RTO, incident response and retention/legal hold.
6. Final RBI/other legal applicability mapping, KFS/loan documentation review and accredited property/legal checks.
7. Approved sanction/disbursement execution by a regulated lender (not included and intentionally blocked).

Do not ship to real borrowers before these obligations are independently fulfilled.

## Additional borrower privacy regression

The non-binding sanction preview filters staff-only sanctions/screening, provider-failure and document-reuse codes from borrower views while preserving an actionable generic review indicator. The analyst's full evidence/reason view is retained. Covered by `test_sanction_preview_redacts_staff_screening_signals`.
