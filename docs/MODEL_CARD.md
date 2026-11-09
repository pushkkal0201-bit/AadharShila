# Risk indicator card — rule-band demonstration

- **Name:** Aadharshila explanatory risk bands
- **Implementation:** `src/aadharshila/engine.py`, `score` output in `evaluate`
- **Version:** `rule-band-1`
- **Method:** Deterministic thresholds on computed FOIR and LTV
- **Inputs:** Eligible income, current obligations, computed EMI, requested principal, accepted collateral value
- **Output:** `LOW`, `MODERATE` or `HIGH`, where sufficient data exists
- **Trained model:** **None**
- **Probability of default:** **Not estimated**
- **Dataset:** Deterministic synthetic applicants for functional testing only
- **Performance evaluation:** No discrimination, calibration, AUC, default prediction, fairness or drift validation is claimed
- **Use:** Explaining affordability/collateral conditions inside a demo
- **Prohibited use:** Predicting real mortgage default, deciding actual creditworthiness or bypassing lender policy / KYC requirements

The indicator never has override authority. The final decision is deterministic, not an output of a generative model.

A genuine lender-grade model would require licensed and appropriately representative performance data, a target label and horizon, temporal validation, calibration, subgroup analysis as appropriate, explainability review, model risk management, ongoing monitoring and sign-off. None of those validations has occurred in this deliverable.
