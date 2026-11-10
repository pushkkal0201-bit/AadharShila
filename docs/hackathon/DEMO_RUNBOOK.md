# Aadharshila — judge demonstration runbook

**Competition:** Housing Fintech Challenge — Problem Statement 2, Digitally Automated Mortgage Underwriting Engine.

**Disclosure before the demo:** All applicant identities, statements, provider assertions, and credit policies are synthetic. The ML model ranks unusual patterns in an artificial reference distribution. The platform cannot issue binding sanctions or move funds.

## Six-minute live walkthrough

| Time | Screen | Operator action | Point proved |
| --- | --- | --- | --- |
| 0:00–0:40 | Overview | Select **AS-1004**. Show request, FOIR, LTV, `REFER`. | Income consistency matters even when affordability ratios appear acceptable. |
| 0:40–1:45 | Evidence intelligence · ML | Click **Load synthetic sample** → **Run evidence analysis**. Review duplicate receipt, abnormal monthly inflow, and bank/support difference. | A real Isolation Forest inference runs against an explicitly synthetic training reference. Flags prioritize review; they cannot decide credit. |
| 1:45–2:25 | Decision explanation | Inspect `INCOME_CONTRADICTION`. | The existing policy engine returns an explainable `REFER`, independently of the ML output. |
| 2:25–3:25 | Evidence explorer | In development demonstration mode, revise `income_support` from ₹55,000 to ₹99,000 and reassess. | New evidence revision yields a new assessment. The demo still respects unresolved gates. |
| 3:25–4:20 | Historical replay / Decision changes | Replay the original assessment and compare with the new one. | Original reasons and policy context remain reproducible. |
| 4:20–5:10 | Policy simulation | Demonstrate impact without overwriting saved decisions. | Policy governance and separation of roles. |
| 5:10–6:00 | Integrations / Monitoring | Show `SIMULATED` source labels and test evidence. | Verification boundaries and operational discipline are visible. |

**Demo safeguards:** Run on local synthetic data only. Do not use real bank statements, Aadhaar documents, live bureau access, or government datasets without explicit rights and consent.

## Fresh Windows checkout

Open Command Prompt in the repository:

```bat
cd /d D:\Projects\AadharShila
py -3.11 -m venv .venv
setup.bat
run.bat
```

Already installed? Run `git pull --ff-only origin main`, `setup.bat`, then `run.bat`. Visit `http://127.0.0.1:8000`, select **Credit analyst**, and enter the synthetic demo password `Demo@12345`.

On a second terminal run `worker.bat` if queued reassessments are part of the demo.

## CLI fallback (does not need a browser)

```bat
cd /d D:\Projects\AadharShila
.venv\Scripts\python.exe scripts\hackathon_demo.py
```

The script creates an artificial six-month transaction batch, compares `₹100,000` bank-income to `₹55,000` supporting income, runs a seeded Isolation Forest against a fixed artificial reference, and prints an advisory JSON result. It does not load user data, call a provider, change a database, or produce an approval.

## Recording and delivery

Record an actual screen capture locally using the installed application, not a generated mockup. Include the menu labels, `SYNTHETIC DATA` banner, ML model-reference disclaimer, and historical replay. Create a short backup recording of the live walk-through. **No video is bundled or claimed to be recorded by this repository.**

Suggested hand-in package: GitHub repo URL, concise pitch deck, runbook, an actual 3–6 minute screen recording, and the project's test / CI evidence. Submission portal fields and exact maximum lengths must be checked in the participant account; the public listing alone does not confirm them.

## Before recording

```bat
test.bat
```

Check all three of these paths: AS-1004 contradiction; AS-1003 affordability rejection; AS-1007 upstream provider failure. The UI must never interpret a provider failure as verified. Use a fresh disposable database if earlier demo edits have modified AS-1004; do not delete a database that contains work you want to retain.
