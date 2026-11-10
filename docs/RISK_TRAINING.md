# Offline credit-model training protocol

`aadharshila.risk_training` trains an interpretable 12-month binary-outcome logistic regression and evaluates it on a chronological 65%/15%/20% train/validation/holdout split. The split is made by application decision date. Duplicate borrower IDs are refused rather than allowing the same borrower across partitions.

It accepts only numeric decision-time predictors (`foir`, `ltv`, `monthly_surplus_ratio`, `obligation_to_income_ratio`, `income_volatility`, `credit_utilization`) and rejects unknown target horizons, missing labels, non-finite inputs, insufficient class counts and absent dataset provenance. Imputation and scaling are fitted on **training rows only**. The holdout reports ROC AUC, average precision, Brier score, log loss and a probability-bin calibration table. A plain JSON coefficient artifact avoids loading untrusted pickle models. Feature attribution is interpretable through coefficients and can be evaluated offline with `predict_one`.

Install optional research dependencies:

```bash
python -m pip install -r requirements-ml.txt
python -m aadharshila.risk_training --data /secure/loan_history.csv --manifest /secure/manifest.json --output /secure/out/model.json
```

Example manifest for data provided by an **authorized lender** (example only, no dataset is supplied):

```json
{
  "source": "Documented lender-owned account performance extract",
  "license": "Internal restricted; formal contract required",
  "permission": "Explicitly approved purpose and processing authority",
  "label_definition": "Default within 12 months after mortgage origination under lender-approved definition",
  "horizon_months": 12,
  "features": ["foir", "ltv", "income_volatility"],
  "synthetic": false,
  "decision_date_column": "decision_date",
  "borrower_id_column": "borrower_id",
  "observation_end_date": "2026-12-31"
}
```

The CSV must include those fields plus binary `default_12m` outcome. Every outcome must have matured through the entire observation period; no data from after the original decision may be included as a feature. Actual lender labels and data rights have **not** been provided. The only executed holdout is synthetic and establishes pipeline functionality, not validated real-mortgage default accuracy. The artifact is **not loaded in the live assessment engine**. Additional independent validation, lawful subgroup assessment, drift monitoring, fair-lending analysis, calibration and lending-governance approval are required before deployment.

For **non-synthetic** data, `observation_end_date` is mandatory. Training fails if any decision is less than 12 months before the declared observation end, preventing a common future-label maturity error. This check is based on the supplied metadata; the lender must independently verify label construction and that no post-decision signals entered the features.

## Reproducible synthetic integration benchmark

`python -m aadharshila.synthetic_risk_benchmark --output-dir .risk-ci` generates a deterministic 640-row **fabricated** mortgage-like dataset and runs the same chronological offline training pipeline. Its labels follow an explicitly invented statistical formula and do not describe actual loan defaults.

On the November 10 local run with seed 42, the 128-row synthetic holdout returned ROC AUC **0.685803** and Brier score **0.129962**. These measurements verify the research implementation and are *not* real mortgage prediction metrics. The resulting JSON artifact has `deployment_status: NOT_AUTHORIZED`, is not loaded by the underwriting engine and cannot authorize a loan.
