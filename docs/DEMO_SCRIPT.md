# Judge demonstration — approximately 6 minutes

**Opening (30 seconds).** Explain the core problem: an EMI calculator cannot decide a mortgage if it does not know which statements are reliable, which records disagree or whether the property and KYC checks are complete. Introduce Aadharshila as an evidence-to-decision system. State upfront that all cases use local synthetic evidence and illustrative policies.

**1. Contradiction: a self-employed LAP (1 minute).** Log in as `analyst` / `Demo@12345`, open `AS-1004`. Show the request amount, accepted bank income and `income_support`. The supporting value is materially lower. Open **Evidence explorer** and point to the synthetic provider tag and separate verification state. Open **Decision explanation** and show `INCOME_CONTRADICTION` with outcome `REFER`. This is a routing result, not an approval.

**2. Resolution and assessment (1 minute).** In Evidence explorer choose `income_support`, value `99000`, verification `VERIFIED`, mode `SIMULATED`; save. The app records a new evidence revision and runs the same deterministic policy engine. Re-open Decision explanation. Show how the contradiction disappears if the value is now consistent; if any other gate remains open, it still refers. No outcome is forced by a hidden applicant ID.

**3. Alternatives and sensitivity (1 minute).** Visit **Offers & stress tests**. Show the maximum affordable illustrative principal from EMI, FOIR and LTV. Compare total interest and the simulated income/rate stress matrix. State that these are hypothetical scenarios and cannot bypass pending identity or property checks.

**4. Revisions and replay (1 minute).** In **Historical replay**, show the initial and revised assessments. Replay the initial one. The report should reproduce its original `REFER` with the original policy and feature snapshot, even though current evidence has changed. Open the **Audit timeline** to show the recorded evidence mutation and assessment event.

**5. Clean and adverse cases (1 minute).** Open `AS-1001` to show all gates passed in the simulated Home Loan case. Open `AS-1003` to show known affordability failure leading to `REJECT`. Open `AS-1007` to show the typed upstream failure, which does **not** turn into verification success. Open `AS-1006` for a potential screening match that creates review rather than an automatic allegation.

**6. Governance (30 seconds).** Open **Policy studio** and show separate Home Loan and LAP limits, version states and authority separation. In **Policy simulation**, show an impact comparison on historical synthetic snapshots, without overwriting old decisions. Show the **Integrations** page with every provider explicitly labeled `SIMULATED`.

**Closing.** The defensible innovation is not a claim of autonomous regulatory certification. It is a reproducible evidence trace from source → normalized calculation → explicit policy → decision → reason → historical replay. Live borrower identity, property-title validation, credit bureau, lender policy signoff and real default-model validation are necessary before deployment.
