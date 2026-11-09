# Institutional go-live and external authorization

**A successful digital signature check is not permission to issue a mortgage.** Institution-run governance is required for legal authority, live bureau access, data processing rights and lending.

| Mandatory attestation | Required external issuer | Supporting evidence |
| --- | --- | --- |
| lender_adopted_policy | Lender credit authority | Approved product rules, limits, rates, exceptions |
| regulated_provider_access | Lender/provider contracting authority | Permitted purpose, agreement, consent terms, sandbox acceptance |
| independent_security_review | Independent security assessor | Scope, vulnerabilities, remediation and retest |
| credit_risk_validation | Independent model-risk validator | Authorized matured outcomes, calibration, performance and subgroup testing |
| legal_regulatory_signoff | Lender legal/compliance officer | Clause-level applicability, KYC/AML, KFS, grievances, privacy and property rights |
| production_disaster_recovery | Operations owner | Actual restore, recovery targets, failover and operational handover |

The lender must control the trust anchors and external signatures:

```text
AADHARSHILA_TRUST_STORE=/secure/approved_signers.json
AADHARSHILA_RELEASE_BUNDLE=/secure/signed_release.json
```

The trust file has `{"issuers":[{"issuer_id":"approved-lender-officer","role":"CREDIT_AUTHORITY","public_key_base64":"base64-raw-Ed25519-key"}, ...]}`. Six distinct issuers and public keys are required. Each release bundle entry has `{"claim":{...},"signature_base64":"..."}`; the claim specifies `requirement`, `issuer_id`, `organization_id`, `product`, `policy_sha256`, `environment:"production"`, `scope:"automated_mortgage_underwriting"`, `valid_from` and `valid_until`. Externally authorized signers must sign UTF-8 canonical JSON from `json.dumps(claim,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)`. Do not put private keys, real borrower data or provider credentials in GitHub.

```bash
python -m aadharshila.production_gate --organization-id INSTITUTION_ID \
  --product HOME_LOAN --policy-json /secure/exact_active_policy.json \
  --bundle /secure/signed_release.json \
  --trust-store /secure/approved_signers.json
```

The verifier checks cryptographic signatures and expiry, **not** whether an issuer is actually licensed, independent, qualified or authorized. That requires separate institutional validation. The exact policy fingerprint can be inspected at `GET /api/v1/operations/readiness` by authorized roles. Production loan evidence must be linked to successful authenticated LIVE provider invocations, not user-entered status strings.

No genuine provider contract, regulator-issued permission, historical mortgage-default data, external penetration test, independent credit-model validation or counsel sign-off is included. The application does **not** issue a real sanction, KFS, contract or disbursement and still needs enterprise identity management, secure operations, property/legal reviews, borrower protection and lender-side deployment.

Regulatory sources for qualified applicability review:
- [RBI HFC Directions 2025 (updated October 1, 2026)](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12939)
- [RBI NBFC KYC Directions 2025](https://www.rbi.org.in/scripts/NotificationUser.aspx?Id=12943)
- [RBI Digital Lending Directions 2025](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12848)
