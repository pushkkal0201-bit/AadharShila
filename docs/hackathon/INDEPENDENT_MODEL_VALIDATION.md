# Independent cohort evaluation — research protocol

This document specifies the **offline, out-of-time** evaluation software added to Aadharshila's mortgage-risk model pipeline. It is designed to evaluate a pinned candidate against a separately supplied, labeled cohort while disclosing uncertainty, distribution shift, and dataset limitations. It does **not** certify the model, authenticate a lender's rights, or authorize use in credit decisions.

## What was implemented

1. **Pinned artifact loading:** a required SHA-256 fingerprint, size limit, JSON-only model format, known six-feature schema, finite parameters, and rejection of tampered files. No serialized Python/pickle model executes.
2. **Independent evaluation contract:** a dataset manifest must declare a distinct dataset ID, provenance, permitted use, source, outcome definition, 12-month label horizon, feature order, separate borrower identifier, independent-cohort declaration and, for nonsynthetic data, the observation cutoff date. This declaration **cannot prove** rights or independence.
3. **Leakage and maturity controls:** evaluation dates must start strictly after the original model development holdout; the same raw CSV is refused by digest; IDs must be unique within the evaluation cohort; missing or invalid labels and immature real labels fail validation. **Cross-dataset borrower overlap cannot be proven** from an artifact that intentionally stores no borrower IDs. An institution must independently verify non-overlap.
4. **Evaluation without fitting:** the model's original medians, means, scales, coefficients and Platt calibration are reused without fitting on the new cohort. No external labels alter any model parameter.
5. **Metrics and uncertainty:** AUROC, average precision, Brier score, log loss, expected calibration error, reliability bins, and a constant-training-prevalence baseline. Stratified bootstrap yields 95% descriptive intervals for AUROC, average precision, Brier score and calibration error. Report the absolute cohort event rate alongside these metrics.
6. **Drift and cohort checks:** missingness by predictor, PSI against training-period distribution bins, and segment metrics only where at least 50 records and 5 of each class are present. These are **descriptive diagnostics**, not validated fairness analysis.
7. **Safe report:** generates only aggregate outputs, cohort metadata and file hashes, never raw borrower rows. `decision_use: false`, `model_activated: false` and `independent_validation_completed: false` are fixed. There is no endpoint that turns on this evaluator or changes a mortgage decision.

## Reproduce the synthetic external-date test

Use a Python 3.11+ environment with `requirements-ml.txt` and the package installed. The example intentionally uses generated data and labels, and does **not** claim external validation.

```bash
python -m aadharshila.synthetic_risk_benchmark --output-dir .risk-ci --rows 640 --seed 42
python -m aadharshila.risk_validation_demo --artifact .risk-ci/research_model.json --output-dir .risk-ci/independent --rows 300 --seed 99
python -m pytest -q tests/test_risk_external_validation.py
```

The first command creates a fitted candidate. The second generates a **different** artificial set of 300 records, shifts its decision dates later than the model development holdout, and performs the independent-date software check. The JSON report is at `.risk-ci/independent/independent_evaluation.json`. Both files are ignored by Git.

Example output from the local seed-99 demonstration, **synthetic labels only**:

```json
{
  "status": "SYNTHETIC_INDEPENDENT_DATE_TEST_ONLY",
  "rows": 300,
  "seed": 99,
  "roc_auc": 0.67571,
  "brier_score": 0.164661,
  "model_activated": false,
  "independent_validation_completed": false
}
```

This is not a test of the model on actual mortgage defaults. Do not advertise the numeric values as production discrimination, calibration or lending benefit.

## Offline evaluation of legitimately held performance records

Only perform these steps after the organization has approved the purpose and legal rights to use a lender-owned or licensed dataset. **Never upload borrower rows, unredacted identifiers, keys, or lender files into this public GitHub repository.**

Create a separate cohort CSV with these columns, observed **as of the origination/underwriting decision**:

```text
borrower_id,decision_date,foir,ltv,monthly_surplus_ratio,obligation_to_income_ratio,income_volatility,credit_utilization,default_12m
```

Use pseudonymous borrower identifiers. `default_12m` must reflect a documented 12-month performance definition, based on a fully matured outcome window. No features computed from later repayment behavior may enter the decision-time predictors. Do not manufacture missing predictor values from later records.

Place a restricted manifest alongside the data, adapted from [the manifest example](EXTERNAL_EVALUATION_MANIFEST.example.json). Its declared provenance and permission must be reviewed and documented independently; a string field is not proof of entitlement. The actual dataset must be held outside this repository.

For a **real-data-trained candidate**, run:

```bash
python -m aadharshila.risk_training --data /secure/train.csv --manifest /secure/train_manifest.json --output /secure/research_model.json
sha256sum /secure/research_model.json
python -m aadharshila.risk_external_validation \
  --artifact /secure/research_model.json \
  --sha256 <exact-64-hex-digest-from-the-previous-command> \
  --data /secure/later_cohort.csv \
  --manifest /secure/later_cohort_manifest.json \
  --output /secure/research_evaluation.json
```

PowerShell: use `(Get-FileHash -Algorithm SHA256 /secure/research_model.json).Hash.ToLowerInvariant()` to retrieve the digest; supply actual Windows drive paths in place of `/secure/…`.

**The offline evaluator refuses a synthetic-trained candidate against a cohort declared real**. A real-data-trained artifact is not accepted by the application-serving API and is not eligible for the synthetic-only registry. An independent lender evaluation and governance process must review each result before any production consideration.

## Sources and domain fit

- [Freddie Mac Single-Family Loan-Level Dataset](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset) contains origination and monthly performance records, with registration and usage terms. Commercial redistribution may require an additional agreement.
- [Fannie Mae Single-Family Loan Performance Data](https://capitalmarkets.fanniemae.com/credit-risk-transfer/fannie-mae-single-family-loan-performance-data) also requires registration and acceptance of terms for loan-level files.

**Neither file set was downloaded, processed, or used to train/validate this project.** These U.S. mortgage portfolios differ from Indian Home Loan and LAP applicants, approval populations and underwriting datasets; their field definitions also differ from Aadharshila's six-feature decision-time contract. Do not rename missing features, infer nonexistent income from loan performance, or treat these sources as validated substitutes for an Indian lender's actual repayment outcomes.

## What still requires an institution

- Documented lawful data access, representative originations and matured outcome labels.
- Confirmed independent borrower-level separation across development and later cohorts.
- Evaluation of selection/rejection bias, material population differences, missingness and temporal instability.
- Protected-cohort/fair-lending analysis under institutional legal, privacy, and risk oversight.
- Independent statistical review, calibration suitability, thresholds, governance sign-off and monitored deployment.

These steps cannot be completed from an artificial benchmark, a GitHub build, or a dataset manifest alone. The software deliberately leaves any operational score, approval, rejection, sanction or disbursement action blocked.
