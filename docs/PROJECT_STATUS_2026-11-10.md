# Engineering status — 10 November 2026

**Project:** Aadharshila — evidence-driven Home Loan and Loan Against Property underwriting demonstration.

**Repository:** [pushkkal0201-bit/AadharShila](https://github.com/pushkkal0201-bit/AadharShila).

**Purpose:** A reproducible evidence-to-decision workflow with explicit reasons, human review gates, policy history and research-only ML. Demonstration evidence, borrower records and credit-policy values are synthetic.

## Implemented and available

| Workstream | Implemented behavior | Main source |
| --- | --- | --- |
| Application intake | Home Loan/LAP cases, borrower/analyst workflow, consent records and 16 synthetic case fixtures | `main.py`, `models.py`, `seed.py` |
| Financial analysis | EMI, FOIR, LTV, alternatives and scenario stresses with Decimal calculations | `finance.py`, `engine.py` |
| Decision engine | Deterministic `APPROVE`, `REFER`, `REJECT` routing; reason codes and mandatory evidence checks | `engine.py`, `service.py` |
| Evidence management | Source provenance, contradictions, expiry, consent, revisions, review requests and replay | `service.py`, `connectors.py` |
| Banking income | Six-month receipt normalization, duplicate/reversal/transfer exclusion and coverage checks | `income.py` |
| Advisory ML | Isolation Forest over monthly receipts relative to generated reference data; explanations, read-only preview | `evidence_intelligence.py` |
| Mortgage-risk research | Logistic regression, Platt calibration, chronological train/validation/holdout, research artifact registry | `risk_training.py`, `risk_registry.py` |
| ML evaluation | Synthetic independent-date cohort, comparison baselines, uncertainty intervals, calibration, missingness and PSI | `risk_external_validation.py`, `risk_monitor.py` |
| Research serving | Digest-pinned, synthetic-only inference and staff-restricted UI; disabled in production | `risk_serving.py`, `web/app.js` |
| Policy governance | Versioned lender-scoped policies, impact simulation, separate author/approver, audit history | `compliance_controls.py`, `service.py` |
| Identity and documents | Role/tenant checks, OIDC/PKCE framework, AES-256-GCM storage and bounded PDF extraction | `security.py`, `browser_sso.py`, `secure_documents.py` |
| Delivery | Windows launchers, Alembic migrations, Docker/PostgreSQL development stack, browser/CI/recovery checks | `scripts/`, `.github/workflows/quality.yml` |

## Verification as of this checkpoint

- The code prior to this documentation/setup update was merged through the independent-cohort model release at Git commit `ff72667c`.
- Its [GitHub Actions run](https://github.com/pushkkal0201-bit/AadharShila/actions/runs/42860845343) passed all four jobs: Ubuntu, Windows, real Chromium browser smoke, Docker/PostgreSQL recovery.
- The latest authoring-environment test checkpoint reported **132 passing Python tests**. This is a historical recorded result, not a promise about another computer's environment.
- A separate Windows checkout using an earlier setup script produced `ModuleNotFoundError: No module named 'pandas'` for ML training tests, because `setup.bat` had installed only `requirements.txt`. The local setup script now installs `requirements-ml.txt`, and the test runner checks for required imports before pytest.
- Synthetic mortgage-risk benchmark: 640 generated observations; 128 holdout observations; reported holdout ROC AUC approximately **0.685803** and Brier **0.137158**, with constant baseline Brier **0.139880**. These are artificial outcomes and cannot be cited as real credit-risk validation.
- Separately generated, later-dated **300-row synthetic** evaluation was exercised; this is not an independently sourced real lending dataset.

For exact reproduction, follow [Windows testing](TESTING_WINDOWS.md), [ML pipeline](hackathon/FULL_ML_PIPELINE.md), [external-date validation](hackathon/INDEPENDENT_MODEL_VALIDATION.md) and the [demonstration runbook](hackathon/DEMO_RUNBOOK.md).

## Not completed or not represented as completed

| Area | Missing dependency or action | Scope |
| --- | --- | --- |
| Official hackathon delivery | Recorded walkthrough and submission confirmation | Participant/organizer workflow |
| Lender and provider access | Executed lender/provider contracts, authorized purpose, real KYC/bureau/AA/property sources | External institutional approval |
| Real-world mortgage-risk model | Authorized historical outcomes, matured labels, borrower-disjoint validation, independent model-risk review and monitored deployment | Institutional data/validation |
| Production security | Approved identity provider, secrets/key management, isolated document worker, scanning, independent penetration testing | Operational deployment |
| Legal/governance | Approved lender policy, jurisdiction-specific compliance mapping, legal authority and signed institutional release | Institutional sign-off |
| Disbursement | Legally binding sanction, customer acceptance, funds flow | **Not implemented** |

The synthetic model does **not** drive underwriting outcomes. A simulated `APPROVE` is a demonstration result and cannot sanction or disburse a loan. Do not commit actual borrower documents, credentials, encryption keys or licensed performance files to the repository.
