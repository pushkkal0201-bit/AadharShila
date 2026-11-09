# Authorized provider onboarding

## Capability boundaries

Aadharshila currently has a **partner gateway adapter**, not direct live integrations with government systems or credit bureaus. Live data is unavailable without an institution/provider agreement, approved purpose, consent language, credential provisioning, schema contract and security review. The gateway is an integration point for an authorized intermediary; it must not be presented as an existing RBI, UIDAI, CERSAI, AA, CKYCR, DigiLocker or credit-bureau API.

For each required evidence category, obtain the provider's written authorization, permissible purpose, the contracting lender's data-processing agreement, exact request/response schema, endpoint, TLS certificate chain, credentials, quotas, failure codes, retention limits and acceptance criteria. Test in the provider's approved sandbox and capture actual provenance before enabling any live verification.

## Adapter settings

Use only environment variables or a dedicated secrets manager, never checked-in credentials. Example for a **hypothetical authorized gateway**:

```text
AADHARSHILA_PARTNER_ALLOWED_HOSTS=gateway.partner.example
AADHARSHILA_PARTNER_BANK_INCOME_URL=https://gateway.partner.example/evidence
AADHARSHILA_PARTNER_BANK_INCOME_MODE=SANDBOX
AADHARSHILA_PARTNER_BANK_INCOME_NAME=authorized-partner-gateway
AADHARSHILA_PARTNER_BANK_INCOME_TOKEN=<credential provided out of band>
AADHARSHILA_PARTNER_BANK_INCOME_HMAC_KEY=<32+ character shared signing key>
```

Change `BANK_INCOME` to `IDENTITY`, `INCOME_SUPPORT`, `BUREAU`, `OWNERSHIP`, `LEGAL`, `VALUATION` or `SCREENING` only for an approved provider-gateway operation. The adapter refuses non-HTTPS URLs, non-allowlisted hosts, credentials embedded in URLs, IP-literal hosts and redirects. A production gateway cannot be configured in sandbox mode. Missing or invalid configuration results in an unresolved status.

## Request and signed response contract

Aadharshila submits a POST with bearer-token authorization and a unique correlation ID. The JSON request includes only `request_id`, `application_reference`, `evidence_key` and `purpose`; no identity numbers, bank logins or original documents are transmitted by this default contract.

The gateway must respond with HTTP 200 and JSON resembling:

```json
{
  "request_id": "<same correlation UUID>",
  "verification": "VERIFIED",
  "verified_at": "2026-11-10T10:00:00Z",
  "data": {"amount": 90000}
}
```

The gateway must compute an `X-Aadharshila-Signature` header containing lowercase hexadecimal HMAC-SHA256 of the **exact response body bytes** using the configured shared secret. The adapter checks freshness (±5 minutes), request ID, signature, payload shape, bounded size and explicit verification state. Errors, timeouts, unsigned responses and incorrect correlations are persisted as `UNRESOLVED` / `FAILED`, not trusted evidence. Response signing is a sample integration control and must be tailored to the chosen partner's approved security architecture; it is not a published API format for any named provider.

## Missing authorization checklist

- Lender/provider legal agreements and regulated permitted-use approvals
- Provider-specific consent, authentication, mapping and freshness documentation
- Verified credentials supplied securely and rotated in a secrets vault
- Provider sandbox tests with documented request/response exemplars
- Independent security assessment, monitoring, retry and incident procedures
- Lender sign-off for risk model, credit policy and any automated approval scope

Until these are complete, **real live underwriting is not authorized**. Even a signed `LIVE` gateway response cannot bypass the current production governance referral guard.
