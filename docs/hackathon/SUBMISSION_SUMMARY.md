# Aadharshila — hackathon submission summary

**Challenge:** Housing Fintech Challenge — Digitally Automated Mortgage Underwriting Engine (Problem Statement 2).

## Problem

A mortgage decision depends on the reliability of many sources: borrower declarations, bank credits, income support, property records, identity, legal checks, and credit-bureau data. A numerical affordability pass does not resolve conflicting, expired, or missing evidence. Manual hand-offs also make it difficult to reproduce what a reviewer knew at the time of a decision.

## What Aadharshila does

Aadharshila is a runnable Home Loan and Loan Against Property underwriting demonstrator. It captures applications and consent, evaluates evidence readiness, calculates EMI/FOIR/LTV, applies versioned credit policies, and returns explainable `APPROVE`, `REFER`, or `REJECT` **simulation** results. Every assessment retains its policy version, input snapshot, reason codes, and evidence revision. Analysts can correct synthetic evidence and compare or replay the earlier result.

## Technical design

- **API:** Python, FastAPI, Pydantic; server-enforced organization/role checks.
- **Persistence:** SQLAlchemy, Alembic, PostgreSQL 16 in Docker; SQLite for a single-machine demo.
- **Policy and finance:** Decimal arithmetic, deterministic conditional controls, lender-scoped versioned policies, simulation with fingerprinted approval.
- **Evidence:** source modes, consent checks, signed partner-gateway contract, encrypted document storage, bounded PDF extraction and provenance-aware review.
- **AI-assisted review:** Isolation Forest trained on a fixed artificial reference distribution, ranking unusual six-month receipt patterns. Reconciliation and stored bank/support comparisons provide grounded reviewer explanations; the model never changes the loan decision.
- **Verification:** Python API/finance/security regression tests, a real Chromium CI smoke, Windows/Ubuntu jobs, Docker/PostgreSQL restore drill.

## Differentiation

The defensible engineering contribution is the traceable chain **evidence → normalized inputs → explicit rule → decision → historical replay**, with contradictions handled as review tasks rather than silently ignored. A separate advisory ML view demonstrates how anomalies can help analysts prioritize document checks without creating an unvalidated automated risk score.

## Demonstration

1. Open `AS-1004`: synthetic Loan Against Property, ₹20 lakh requested, initial decision `REFER`.
2. Compare the originally seeded ₹100,000 bank-income assertion to ₹55,000 income support; the 45% difference exceeds illustrative tolerance.
3. Open **Evidence intelligence · ML**, load the synthetic sample and run. Review the excluded loan credit, duplicated income reference and unusual month.
4. Show the deterministic decision reason `INCOME_CONTRADICTION`; update synthetic evidence through the permitted analyst flow.
5. Show the new assessment revision, historical replay, audit events, policy simulation and explicit synthetic integration labels.

See [demonstration runbook](DEMO_RUNBOOK.md) and [ML model card](AI_EVIDENCE_REVIEW.md).

## What is and is not validated

The repository tests software logic and simulated workflow behavior. The generated transactions and outcome labels are invented; they cannot be used to claim real-bank anomaly accuracy, credit-default prediction, regulatory certification, lender adoption, or measurable processing-time savings. No real KYC, bureau, Account Aggregator, registry, or disbursement connection is supplied. Any institutional deployment would require authorized data, security and legal review, approved policies, operational controls and independent model validation.

## Submission logistics

- **Repository:** https://github.com/pushkkal0201-bit/AadharShila
- **Run:** `setup.bat` then `run.bat` on Windows. Default development analyst account uses the synthetic `Demo@12345` password.
- **Reproduce ML check:** `python scripts/hackathon_demo.py`
- **Tests:** `python -m pytest -q`
- **Pitch deck:** provided separately as `Aadharshila_Hackathon_Pitch.pptx` and PDF.
- **Video:** record the genuine local application on the operator's Windows machine. No recorded demo video is included.
- **Submission:** upload artifacts using the organizer's authenticated portal; a public GitHub repo or this summary does not itself count as an official submission.
