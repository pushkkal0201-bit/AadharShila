# Capability and production-readiness boundaries

| Area | Current classification | Evidence | Production work still required |
| --- | --- | --- | --- |
| Home Loan + LAP workflows | Locally implemented and tested | Intake/submit/reassessment endpoints; synthetic scenarios | Broader UI role and browser E2E coverage |
| Financial calculations | Locally implemented and unit tested | `finance.py`, numerical tests | Independent regulated math validation |
| Rule engine and outcomes | Locally implemented and unit tested | `engine.py`, approved/refer/reject precedence tests | Lender-approved rules and scope of automated approval |
| Evidence revision and replay | Locally implemented and tested | Frozen snapshots, before/after decision diff and historical tests | Evidence dependency DAG, long-term retention review |
| Auth and role access | Locally implemented and tested in demo mode | Sessions, CSRF, borrower ownership tests | Enterprise SSO, MFA, fine-grained permissions and independent security review |
| Document upload / text extraction | Locally implemented and tested | Bounded PDF/TXT, hash and text parsing, scoped downloads and integrity checks | OCR, signature validation, malware scanning, encrypted object storage |
| Consent | Locally implemented and tested | Purpose-specific grant/revoke and enforcement test | Regulated notice, provider-specific authorization, retention and deletion |
| Identity, bureau, AA, GST, registry, CERSAI, RERA, PEP | Implemented with synthetic fixture data only | `seed.py`, UI mode labels | Real contracts, permitted purpose, accredited providers, reliability controls |
| Credit-risk prediction | Demonstration rule scorecard only | `MODEL_CARD.md`, engine code | Licensed data, statistical training, validation, calibration and independent sign-off |
| Regulatory controls | Primary sources researched, not legally encoded | `REGULATORY_SOURCES.md` | Clause-specific controls, applicability review, approval and independent audit |
| Property assessment | Synthetic valuation evidence and documented legal/title gates | Decision rules and cases | Local registry coverage, legal opinions, accredited valuation |
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
