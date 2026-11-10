# Capability and production-readiness boundaries

| Area | Current classification | Evidence | Production work still required |
| --- | --- | --- | --- |
| Home Loan + LAP workflows | Locally implemented and tested | Intake/submit/reassessment endpoints; synthetic scenarios | Broader UI role and browser E2E coverage |
| Financial calculations | Locally implemented and unit tested | `finance.py`, numerical tests | Independent regulated math validation |
| Rule engine and outcomes | Locally implemented and unit tested | `engine.py`, approved/refer/reject precedence tests | Lender-approved rules and scope of automated approval |
| Evidence revision and replay | Locally implemented and tested | Frozen snapshots, before/after decision diff and historical tests | Evidence dependency DAG, long-term retention review |
| Auth and role access | Locally implemented and tested in demo mode | Sessions, CSRF, borrower ownership tests | Browser SSO flow, IdP onboarding/revocation, OIDC key rotation, fine-grained permissions and independent security review |
| Document upload / text extraction | Locally implemented and tested | Bounded PDF/TXT, hash and text parsing, scoped downloads and integrity checks | Production OCR/ClamAV services and isolation, cryptographic PDF signature validation, encrypted object storage |
| Consent | Locally implemented and tested | Purpose-specific grant/revoke and enforcement test | Regulated notice, provider-specific authorization, retention and deletion |
| Identity, bureau, AA, GST, registry, CERSAI, RERA, PEP | Implemented with synthetic fixture data only | `seed.py`, UI mode labels | Real contracts, permitted purpose, accredited providers and source-specific verification |
| Credit-risk prediction | Demonstration rule scorecard only | `MODEL_CARD.md`, engine code | Licensed data, statistical training, validation, calibration and independent sign-off |
| Regulatory controls | Primary sources researched, not legally encoded | `REGULATORY_SOURCES.md` | Formal interpretation, lender-specific legal applicability, approved borrower disclosures and independent audit |
| Property assessment | Synthetic valuation evidence and documented legal/title gates | Decision rules and cases | Authenticated registry responses, legal opinions, accredited valuation |
| Alternative terms and stress | Locally implemented and tested | Financial functions and scenarios | Approved product scope, legal disclosures, acceptance workflow |
| Policy versioning / governance | Locally implemented and integration tested | Distinct author/approver, simulate/activate lifecycle | Org-specific permissions, effective-date logic, change board |
| Durable worker | Local queue/revision protection and fixture provider trace tested | `worker.py`, stale job tests | Multi-worker locking, dead-letter UX, production fault/load test |
| Database migrations | Initial Alembic migration generated | `migrations/versions/` | Production staging migration/rollback drill |
| UI | Bundled interactive browser interface; static resource and syntax checks | `web/`, HTTP root smoke | Full browser end-to-end and accessibility audit; direct Chromium navigation restricted in current runtime |
| Dev operations | Readiness endpoint, startup instructions, Windows D: scripts and OS-matrix CI config | `OPERATIONS.md`, `WINDOWS_D_DRIVE.md`, local test suite | Windows execution, GitHub Actions run, Docker run, TLS, backup/restore drill |
| Disbursement | Not implemented | No real fund-transfer path | Legal contracts, authorized payments and regulated disbursement processing |

## Claim boundaries

- A loan `APPROVE` in this program is a **simulated underwriting result** and no actual lender commitment.
- `SIMULATED` evidence is not real source verification even when a fixture’s internal verification field reads `VERIFIED`.
- No real-world performance, PD accuracy, fairness, cost reduction, adoption or legal certification is asserted.
- The local functional acceptance tests do not replace a production security audit.

## 10 November 2026 hardening checkpoint

- **Locally verified:** fail-closed `production` output, borrower screening redaction across additional assessment routes, signed partner-gateway contract with tamper/redirect/SSRF tests, SQLite backup/restore with document hash protection, and synthetic temporal-holdout credit-model training pipeline.
- **Exercised locally:** 55 Python tests pass; SQLite recovery restored 16 synthetic applications into a fresh location. The automated recovery test also restored one uploaded text document.
- **CI staged (not evidence of successful execution until workflow completes):** Linux/Windows Python tests, PostgreSQL Compose startup and disposable PostgreSQL backup/restore exercise.
- **Cannot be claimed complete:** genuine bureau/CKYCR/AA/DigiLocker/registry source integrations, real-mortgage model validation, enterprise IAM, independent cybersecurity assessment, lender credit-policy approval, legal/regulatory sign-off, production hosting, business continuity and disaster recovery with stated RPO/RTO.

See `docs/PROVIDER_ONBOARDING.md`, `docs/RISK_TRAINING.md`, `docs/SECURITY_REVIEW.md`, and `docs/RECOVERY_DRILL.md`.

## Hosted CI exercise note

The PostgreSQL Compose backup/restore job and Ubuntu test job completed successfully in [Actions run 42703365325](https://github.com/pushkkal0201-bit/AadharShila/actions/runs/42703365325). The initial Windows job detected a snapshot file-lock error; the relevant SQLite handles have been explicitly closed in a follow-up patch. The updated Windows result must be read from the next workflow execution before it can be declared passed. No cloud-region disaster recovery, encryption/key restore or approved regulatory control operation was exercised.

## Current release-control extension (10 November 2026)

- Six externally issued Ed25519 attestations can be checked for distinct trust anchors, organization, product, active policy hash, scope, effective period and signature integrity. **No attestation is supplied or self-certified with this repository.**
- Production evidence now requires successful signed gateway invocation provenance linked to each evidence row; merely setting a `LIVE` string cannot satisfy the real decision engine.
- Production SQLite is rejected; the test build retains local SQLite for development.
- Real-data model evaluation refuses labels whose full 12-month observation window has not matured based on the dataset manifest.
- See `docs/INSTITUTIONAL_GO_LIVE.md` for all externally controlled deployment prerequisites. No live lender approval, real bureau data, certified security assessment or real-mortgage validation was obtained in this chat.

## 10 November 2026 follow-up: lender tenancy

Policy data now has a lender organization foreign key; API reads and lifecycle operations are organization-scoped, and assessment construction verifies ownership. The Alembic upgrade backfills prior policies from their author/approver accounts and rejects ambiguous ownership. One ACTIVE policy per lender/product is enforced at the database layer. Signed gateway evidence now includes a stored payload digest. These safeguards have automated tests, but they are not an independent penetration test. See `GAP_ASSESSMENT_2026-11-10.md` for the current matrix and external dependencies.

## November 10: advanced workbench checkpoint

- **Implemented and locally exercised:** `income.py` provides conservative categorized transaction accounting; verified samples can reduce accepted income but analysts cannot promote an exploratory preview to verified evidence. `property_intelligence.py` returns review-only comparables, never accepted title/collateral. `compliance_controls.py` emits evidence-presence diagnostics and expressly sets legal certification to false. `sanction.py` generates non-binding summaries with disbursement always blocked, and borrower previews redact staff-only screening signals.
- **Configured dependency but not completed live operation:** `documents_pipeline.py` adds optional Tesseract/pdfium OCR and ClamAV scanning that fails closed for production uploads; `federated_auth.py` validates locally pinned OIDC token signing keys, audience, issuer, expiry and MFA indicators. The browser redirect/callback flow, IdP lifecycle, a real scanner service and cryptographic PDF signature validation are **not included**.
- **Locally verified:** 91 automated tests, JavaScript syntax check, and Alembic head `f71a63c80927` on SQLite (latest local run). These are not independent security or legal certifications.
- **Still blocked:** live licensed providers, independently validated mortgage outcomes, lender-owned credit policies, official KFS and binding sanction issuance, authorized disbursement, live production hosting and independent operational certification.

Further detail: [`ENGINEERING_STAGE_2026-11-10.md`](ENGINEERING_STAGE_2026-11-10.md).
