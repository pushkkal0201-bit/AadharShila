# Internal security verification and external review boundary

Reviewed locally on 10 November 2026. This document describes **developer tests**, not an independent penetration test, SOC 2 certification or lender-approved security assessment.

| Threat / control | Verification | Remaining boundary |
| --- | --- | --- |
| Borrower object-level authorization | API tests reject access to another borrower's document and application | Independent authorization review and tenant isolation test |
| Sensitive screening data in borrower responses | Regression tests exercise application detail, assessment, history, decision and evidence endpoints | Complete endpoint inventory and privacy counsel sign-off |
| Consent withdrawal | Existing automated consent enforcement tests | Provider-level revocation and retention obligations |
| Forged partner response | HMAC-SHA256 signature and correlation tests | Provider onboarding, key rotation, replay-store and provider-specific legal contract |
| External URL / SSRF | Fixed HTTPS host allowlist, denial of literal IP, local and HTTP target, no redirects, transport tests | DNS resolution hardening, proxy firewall and independent network test |
| Simulated evidence in production | Production-scope decision test verifies REFER even when synthetic assertions read VERIFIED | Lender approval before any automatic decision |
| Uploaded document tampering | Download hash check and restore-document checksum tests | Antivirus, isolated extraction worker, scanned PDF sandbox and object-store versioning |
| Audit/replay | Previous assessment snapshots retained and deterministic replay tests | External log retention, write-once storage and forensic controls |
| Backup restore | SQLite backup/restore with cross-path documents and tamper detection | PostgreSQL staging restore and disaster recovery rehearsal outside CI |
| Dependencies | CI environment installation and tests | Dependency vulnerability scan and software supply-chain independent review |

## Open security decisions

1. Enterprise authentication, account recovery, MFA and privileged-access management are not implemented.
2. Data classification, lawful basis and retention requirements depend on the regulated lender's governance process.
3. End-to-end TLS at a reverse proxy, secret vault, monitoring, HSM where appropriate and outbound network policies require an approved deployment.
4. No actual credit-bureau, CKYCR, DigiLocker, Account Aggregator, property registry or screening provider has been granted access.
5. Internal tests are necessary but do not substitute for a qualified external penetration test and formal remediation sign-off.

**Scope of current tests:** `tests/test_security_recovery_gateway.py`, `tests/test_api.py`, `tests/test_next_stage.py`. Run `python -m pytest -q`.
