# AI-assisted evidence review — model and control card

## Purpose

Prioritize transaction-pattern anomalies for a credit analyst while keeping documented source evidence, income calculations and loan decisions under the existing deterministic controls.

## Inference contract

- Input: bounded `TransactionBatch` with applicant category, six-month reference window, transaction IDs, category, direction, amount and verified flag. Rows can be pasted manually; they are **not source-authenticated** just because `verified: true` appears in a submitted JSON row.
- Endpoint: `POST /api/v1/applications/{id}/evidence-intelligence` for analyst, compliance or administrator roles within the application's organization.
- Sample: `GET /api/v1/applications/{id}/evidence-intelligence/demo` loads fixed generated transactions in development only. No provider is called.
- Output: reconciliation findings, stored bank/support source comparison, suspicious monthly receipt patterns, reviewer actions, explicit model provenance, and `assessment_effect: NONE`.
- No database writes, no evidence promotion, no direct edits to accepted underwriting income, and no binding loan approval.

## Algorithm

1. Run `income.reconcile` to exclude repeated references, own-account credits, loan proceeds and other excluded categories, while preserving coverage and reversal findings.
2. For at least three positive months, calculate the median of the six monthly income receipts.
3. Generate 384 artificial nonnegative normalized receipt values with a **fixed seed 20261110**. Fit `sklearn.ensemble.IsolationForest(n_estimators=96, contamination=0.05, random_state=20261110)` on `log1p(normalized_value)`.
4. Apply the detector to six observed monthly receipt totals normalized by the observed positive-month median. Negative `decision_function` outputs indicate unusual observations **relative to this synthetic distribution**.
5. Return ordered months with margins and source-specific deterministic reasons. The model score is not a probability, a calibration metric, or a fraud finding.

## Reproducible synthetic case

The generated case `AS-1004` includes recurring ₹100,000 monthly receipts, one ₹820,000 artificial receipt, a ₹240,000 loan inflow excluded from income, and a duplicate referenced income row. Stored synthetic bank/support evidence is initially ₹100,000 versus ₹55,000 (45% discrepancy). After a judge revises those stored values, the source comparison reflects the new state, rather than forcing a demo result.

```bash
python scripts/hackathon_demo.py
python -m pytest tests/test_evidence_intelligence.py -q
```

## Limitations and review boundaries

- The fixed artificial reference is intentionally **not representative of real borrower income**. An unusually high or low receipt is a review prompt, not a fraud claim, a repayment-risk estimate, or independently verified income.
- No supervised mortgage-default labels or ground truth exist in this feature. Accuracy, recall, false-positive rate, fairness and calibration on actual borrowers have **not been measured**.
- The model prioritizes unusual monthly magnitudes only. It does not authenticate documents or detect document forgeries. The deterministic reconciliation rules remain distinct from machine-learning inference.
- The mechanism is deliberately non-decisional: if the model is absent, unavailable, or reports no outliers, the original policy engine continues unchanged. A bank integration and consent are separately required to use actual financial statements.
- Additional requirements for real-world use: lender-owned data rights, security review, source authentication, approved model monitoring, subgroup-impact analysis, independent validation and human escalation procedures.

## Code

- [`src/aadharshila/evidence_intelligence.py`](../../src/aadharshila/evidence_intelligence.py) — ML model and source comparison.
- [`src/aadharshila/income.py`](../../src/aadharshila/income.py) — deterministic receipts/obligations and exclusion logic.
- [`web/app.js`](../../web/app.js) — visible review surface.
- [`tests/test_evidence_intelligence.py`](../../tests/test_evidence_intelligence.py) — role boundary, no-mutation, fixed seed, missing ML dependency and outlier regressions.
