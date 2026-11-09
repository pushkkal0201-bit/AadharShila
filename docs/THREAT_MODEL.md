# Threat model and implemented controls

## Sensitive assets

Borrower application details, identity/income evidence, document originals, legal and property data, underwriter decisions, consent, source metadata, policy changes and audit events.

## Trust boundaries

Browser ↔ API; API ↔ database; uploaded document ↔ text parser; staff ↔ simulated fixture acceptance; background worker ↔ assessment snapshots. Real external providers are not integrated.

## Tested / implemented safeguards

- Strong PBKDF2-HMAC-SHA256 salted password derivation for development accounts.
- Eight-hour JWT session signed with deployment-configured secret, kept in HttpOnly cookie; `SameSite=Lax`, `Secure` in production mode.
- CSRF double-submit token for cookie-authenticated data-changing operations.
- Role matrix and organization/borrower ownership checks on application, assessment, document, audit, review and report routes.
- Borrower cannot mark evidence verified; simulated reviewer evidence requires an explicit fixture provider identifier.
- Only borrower may grant/revoke own case consent.
- Upload restricted to 8 MiB and verified PDF header or UTF-8 plain text; filename reduced to basename; random server-side storage name.
- Deterministic, bounded PDF/text parsing; extracted fields remain unverified and untrusted; no embedded text is treated as an instruction.
- Avoid exposing saved document storage paths and raw local files through public endpoints.
- HTML report safely escapes borrower names and reason strings.
- Historical replay evaluates frozen inputs, not freshly read external data.

## Outstanding / not validated

| Risk | Current gap | Required production control |
| --- | --- | --- |
| Unauthorized staff actions | Demo roles and fixture handling are simplified | Enterprise SSO/MFA, verified onboarding, scoped entitlements, maker-checker approvals |
| Malicious uploaded content | No malware scanning or signature validation | Isolated scanning, file quarantine, content disposition and independent parsing security review |
| User privacy | No retention policy scheduler or legal-hold process | Jurisdiction-specific retention, deletion eligibility, consent lifecycle and DPO review |
| Credential compromise | Demo password is published | Unique credentials, rate-limits, lockout/abuse monitoring and secret rotation |
| Cross-origin attacks | Same-origin deployment assumed | Full reverse-proxy, CSP, headers, TLS, cookie and CSRF validation under real hostname |
| Provider compromise | No real integration | Signed/authenticated responses, egress restrictions, retries, observability and incident procedures |
| Worker concurrency | Local queue uses basic row claims | PostgreSQL concurrency/load testing, lease watchdog, idempotent side-effects and robust monitoring |
| Log leakage | Operational logging not comprehensively structured/redacted | Centralized PII-safe logging with retention rules |
| Audit tampering | Audit events are append-only by application logic, not immutable storage | WORM/externally anchored storage and integrity controls |
| Application security | Automated functional tests only | Independent security assessment, dependency scanning, authorized penetration testing |

This document is a threat model, **not** evidence of security certification.
