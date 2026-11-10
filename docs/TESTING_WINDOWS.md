# Local verification on Windows

This guide uses the synthetic development environment. It is meant to produce a repeatable demonstration, not a live credit decision.

## 1. Update, install, test

Use **Command Prompt** in a local checkout. An existing virtual environment is retained:

```bat
cd /d D:\Projects\AadharShila
git pull --ff-only origin main
if not exist .venv\Scripts\python.exe py -3.11 -m venv .venv
setup.bat
.venv\Scripts\python.exe -c "import pandas, numpy, sklearn; print('ML dependencies OK')"
test.bat
```

The Windows setup script installs `requirements-ml.txt` so the full suite can import pandas, NumPy and scikit-learn. `test.bat` checks those imports before launching pytest. A previous environment created with only `requirements.txt` might not have pandas; rerun `setup.bat` instead of deleting the environment or database.

**Pass condition:** pytest completes without failures or errors. A few deliberate skips and deprecation warnings do not necessarily indicate a failure. Do not quote a historical test count as the result of a new run.

### Focused financial, ML and deployment tests

For the new precision, data-quality and deployment-mode regressions:

```bat
.venv\Scripts\python.exe -m pytest -q tests\test_engine.py tests\test_finance.py tests\test_environment_boundary.py tests\test_full_ml_pipeline.py tests\test_risk_external_validation.py
```

The boundary tests verify that a displayed FOIR/LTV exactly on a limit still fails when the underlying amount exceeds it, an untrusted obligation assertion cannot satisfy a restricted-environment assessment, malformed training rows are rejected, and non-development `APP_ENV` values cannot enable demo login or synthetic risk preview.

## 2. Standard underwriting walkthrough

```bat
run.bat
```

Open `http://127.0.0.1:8000` and use the development **Credit analyst** account (`analyst` / `Demo@12345`). Do not reuse these credentials for a deployed service.

| Reference | Check | Expected demonstration behavior |
| --- | --- | --- |
| `AS-1001` | Complete Home Loan case | Simulated `APPROVE` when all gates pass |
| `AS-1003` | Known affordability failure | `REJECT` with a financial reason |
| `AS-1004` | Bank income ₹100,000 vs income support ₹55,000 | `REFER`; `INCOME_CONTRADICTION` |
| `AS-1006` | Possible screening match | Review dependency rather than a confirmed match |
| `AS-1007` | Provider outage | Unresolved evidence; never automatically verified |

With `AS-1004`, inspect **Decision explanation**, revise the **synthetic** `income_support` assertion to `99000` in **Evidence explorer**, and compare the new assessment to the historical one. The old assessment should replay from its stored policy and evidence snapshot. A separate unresolved gate can still cause `REFER`.

Do not overwrite real documents or reset a database to restore a demo case. Use a separate disposable database for an untouched recording.

## 3. Advisory transaction anomaly model

With the normal server running, open **Evidence intelligence · ML**, select `AS-1004`, load the synthetic transaction sample and run the analysis.

Expected findings include the duplicate referenced receipt, excluded loan proceeds, an unusual ₹820,000 synthetic monthly receipt, and the source-income contradiction. The ML output must not update accepted income or change the saved loan decision.

CLI reproduction:

```bat
.venv\Scripts\python.exe scripts\hackathon_demo.py
```

Check `credit_decision_modified: false` and `read_only: true`. The Isolation Forest is trained against generated reference data; its score does not establish fraud probability.

## 4. Calibrated synthetic mortgage-risk research

Stop `run.bat` with Ctrl+C before starting this launcher, which also uses port 8000:

```bat
ml_demo.bat
```

Open **Risk model laboratory**, select a synthetic example, acknowledge the research-data warning and run the preview. Confirm that it displays the calibrated synthetic-label score, uncalibrated score, log-odds contributions, artifact SHA-256 and any input-range warnings. Switching between lower- and higher-stress examples should change the inputs without modifying any application.

The research model uses six features: `foir`, `ltv`, `monthly_surplus_ratio`, `obligation_to_income_ratio`, `income_volatility` and `credit_utilization`.

## 5. Independent-date research evaluation

In another CMD terminal:

```bat
cd /d D:\Projects\AadharShila
.venv\Scripts\python.exe -m aadharshila.risk_validation_demo --artifact .risk-ci\research_model.json --output-dir .risk-ci\independent --rows 300 --seed 99
notepad .risk-ci\independent\independent_evaluation.json
```

Inspect the event rate, ROC AUC, average precision, Brier, log loss, calibration, baseline comparison, bootstrap intervals, PSI and subgroup summaries (when sample sizes suffice). The `model_activated` and `independent_validation_completed` flags must remain `false`. These records and labels are entirely synthetic.

## 6. Browser, database and CI

Optionally run a real Chromium journey:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe scripts\browser_smoke.py
```

The browser smoke covers authentication, queue, decision explanation, documents, evidence intelligence, research lab access and logout. The repo's CI additionally verifies the Python suite on Windows and Ubuntu and a PostgreSQL/document restore drill:

[GitHub quality workflow](https://github.com/pushkkal0201-bit/AadharShila/actions/workflows/quality.yml).

For production readiness, a successful simulation or CI run **does not** establish validated mortgage-default performance, provider access rights, lender approval, independent security review, legal authority, loan sanction or disbursement. See [institutional go-live](INSTITUTIONAL_GO_LIVE.md) and [independent model validation](hackathon/INDEPENDENT_MODEL_VALIDATION.md).
