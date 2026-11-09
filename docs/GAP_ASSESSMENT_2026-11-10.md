# Aadharshila — engineering gap assessment

Reviewed: 10 November 2026. Source: pushkkal0201-bit/AadharShila, baseline commit d4af0bea614a. This is an engineering review, not institutional authorization or an independent security certification.

## Baseline

- The available source package passed 66 pytest tests before changes. The latest GitHub workflow for that baseline was successful.
- FastAPI, deterministic mortgage decisioning, illustrative Home Loan/LAP policies, historical replay, evidence collection, document handling, simulated connectors, Windows scripts and recovery tooling exist.
- Direct Git clone and browser navigation to localhost were blocked in this execution environment. GitHub connector inspection and local Python/API tests were available. Full browser-to-API E2E remains unverified.

## Changes in this branch

| Priority | Risk | Engineering change |
| --- | --- | --- |
| P0 | Cross-tenant credit policies | Organization FK, scoped reads and policy lifecycle actions, lender-specific policy versions |
| P0 | Wrong lender policy selected for an assessment | Organization must match in policy resolver and assessment constructor |
| P0 | More than one active policy per lender/product | Database partial unique index and ordered retirement/activation |
| P0 | Legacy policies lacked ownership | Alembic backfill from author/approver; ambiguity fails instead of guessing |
| P0 | Signed gateway assertion not bound to stored evidence | Canonical JSON payload digest checked during evidence snapshot |
| P1 | Cross-site logout | Session and CSRF checks required |
| P1 | Borrower dashboard requested restricted policy records | Browser skips staff-only policy list for borrower |

The provider payload digest is an application integrity check, not database immutability or legal proof of provider authorization.

## Remaining external and operational dependencies

1. Regulated lender sponsorship, lender-owned Home Loan/LAP policies, delegated authority and legal/compliance acceptance.
2. Licensed identity, KYC/AML, credit bureau, Account Aggregator, tax and property evidence access with contracts and authorized credentials. The present gateway is an adapter contract, not direct official access.
3. Enterprise identity: MFA/OIDC, staff onboarding and revocation, session revocation, access approval and abuse detection. Never deploy demo passwords for real borrowers.
4. Real and legally obtained mortgage outcome data; borrower-disjoint out-of-time validation, label maturity, calibration, leakage review and independent model-risk acceptance.
5. Malware scanning, encrypted and isolated documents, validated issuer signatures, lawful data retention, deletion and legal holds.
6. Production infrastructure: hardened PostgreSQL, object/key backups, deployment security, incident response, DR drills and agreed RPO/RTO.
7. Clause-specific RBI compliance mapping, disclosure/KFS checks and regulated lender sign-off.
8. Full browser E2E, accessibility, load/fault and independent security testing.

No live credit-bureau service, lender license, independent security certification, regulatory authorization or real mortgage PD validation has been obtained.

## Official primary references checked 10 November 2026

- RBI Housing Finance Companies Directions 2025 (updated 1 October 2026): https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12939
- RBI Digital Lending Directions 2025: https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12848
- RBI Housing Finance Companies Second Amendment Directions 2026: https://www.rbi.org.in/scripts/BS_CircularIndexDisplay.aspx?Id=13494 — stated effective date 1 January 2027; it should not be treated as already effective in November 2026.

The lender legal/compliance function must determine applicability, effective dates and executable interpretations. Demonstration FOIR/LTV thresholds are not RBI-certified policies.

## Verification

Run python -m pytest -q; node --check web/app.js; python -m alembic upgrade head; python -m alembic current. Migration revision: c91e8a2048f1. Trial migrations against a backed-up staging copy. Always check CI results associated with this branch, not a previous successful commit.
