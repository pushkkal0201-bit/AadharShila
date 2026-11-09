# Decision computation and policy semantics

## Calculation basis

All money arithmetic in `finance.py` uses Python `Decimal` and round-half-up to two rupee decimal places. For principal `P`, monthly rate `r = annual_rate_percent / 1200`, and tenure `n` months:

- EMI = `P × r × (1+r)^n / ((1+r)^n − 1)`; for zero rate, `P / n`.
- FOIR = `(existing monthly debt obligations + computed proposed EMI) / accepted monthly income`.
- LTV = `requested principal / accepted property valuation`.
- Monthly surplus = `accepted income − existing debt obligations − proposed EMI`.
- Total repayment = `rounded EMI × number of months`; total interest = total repayment minus principal.

An unverified income figure is **not** substituted for accepted income. No income / no valuation results in an unresolved denominator, not a zero-risk or positive pass.

## Illustrative policies

| Parameter | Home Loan | LAP |
| --- | ---: | ---: |
| Annual interest | 8.5% | 10.5% |
| Maximum FOIR | 50% | 45% |
| Maximum LTV | 80% | 65% |
| Minimum verified income / month | ₹20,000 | ₹30,000 |
| Maximum tenure | 360 months | 240 months |
| Income source tolerance | 15% | 15% |
| Property value tolerance | 20% | 20% |

**These are synthetic demonstration assumptions only.** They are not lender-published terms, not RBI-mandated universal thresholds and not customer offers.

## Required gates

The assessment requires current identity, bank income, independent income support, bureau, ownership, legal, valuation and screening evidence, plus active `financial_underwriting` consent. Each has an actual `PASS` or `UNRESOLVED` rule execution. Provider failure additionally creates a `TECHNICAL_FAILURE` / `PROVIDER_UNAVAILABLE` blocker. A fuzzy screening match creates a review dependency and does not itself assert a confirmed sanctions match. The engine also checks known income/valuation contradictions and shared document hashes.

1. A **known hard policy failure** such as FOIR over the threshold, LTV over threshold, verified income below the minimum or tenure exceeding the limit produces `REJECT` even if unrelated evidence is still missing.
2. Without a known hard failure, any **unresolved mandatory gate** (missing, stale, contradictory or failed provider) produces `REFER`.
3. Only when every mandatory check passes does the illustrative engine produce `APPROVE`.

A `REFER` is a completed **routing result**, not a completed underwriting approval. An `APPROVE` in this prototype is a **simulation** and cannot produce loan disbursement or a legally effective sanction.

## Alternative terms

The eligibility solver computes the maximum permitted EMI as `max(0, verified income × max_FOIR − obligations)`, converts it to an eligible principal by reversing the EMI formula and takes the minimum of that value, the requested principal and `verified collateral × max_LTV`. No result is called an approved offer; unresolved KYC or property checks remain blockers.

## Stress matrix

Baseline, income -20%, rate +2 percentage points, combined income/rate, and collateral -15%. Recalculate EMI, FOIR, monthly surplus and LTV. All figures are hypothetical comparisons, **not forecasts**.

## Historical replay

`service.replay` reads the stored input/policy snapshot and re-evaluates the pure engine. It compares the saved and replayed decision, reasons, executed rules and financial outputs. No external providers are contacted. The stored rule-band indicator is not a probability of default.
