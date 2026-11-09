# Integration matrix and data contracts

## Current modes

All external evidence categories listed here use **SIMULATED** local fixtures. They do not perform network authentication or query a live provider.

| Category | Current mode | Evidence key / role | Production dependency |
| --- | --- | --- | --- |
| Identity verification | SIMULATED | `identity` | Authorized identity provider / KYC process |
| CKYCR-related evidence | SIMULATED | Additional identity evidence | Authorized entity access and process review |
| DigiLocker / document issuer | SIMULATED | Issued document evidence | Authorized consent, API partner approval |
| Account Aggregator | SIMULATED | `bank_income` | Proper AA flow, data-use purpose, FIU/FIP integration |
| Licensed credit bureau | SIMULATED | `bureau` | Contract, permissible purpose, bureau account |
| Tax and GST | SIMULATED | `income_support` | Authorized source and data permissions |
| Property records | SIMULATED | `ownership` / `legal` | Jurisdiction-specific official availability, qualified legal review |
| CERSAI | SIMULATED | Registered-interest evidence | Authorized access, correct interpretation |
| RERA | SIMULATED | Approval/evidence if applicable | Appropriate state regulator data and case applicability |
| Property valuation | SIMULATED | `valuation` | Independent appraiser or validated, bounded provider |
| Sanctions / PEP | SIMULATED | `screening` | Licensed screening feeds, analyst resolution, AML process |

No real provider is reported as available, sandbox-approved or live. An `UNRESOLVED` or `FAILED` provider dependency cannot satisfy a mandatory underwriting gate. The local fixture data is deterministic and seeded by `seed.py` with `mode=SIMULATED`.

## Implemented fixture adapter contract (live adapter outstanding)

A real connector must specify operation, input/output contract, authorized-purpose proof, timeout, bounded retries, stable request ID, idempotency key, freshness rule, error taxonomy and data retention controls. `src/aadharshila/connectors.py` implements a typed fixture adapter, consent check, explicit `UNAVAILABLE` outcome and persisted request metadata in `ProviderInvocation`. The API exposes `POST /api/v1/applications/{id}/providers/{key}/run` and `GET /api/v1/applications/{id}/provider-calls`. A **real** provider adapter, authenticated network transport, signed provenance, robust retry policy and provider approvals remain unimplemented.

```json
{
  "evidence_key": "bank_income",
  "provider": "synthetic-fixture-v1",
  "mode": "SIMULATED",
  "verification": "VERIFIED",
  "value": { "amount": 125000 },
  "revision": 1
}
```

Here `VERIFIED` means the synthetic fixture carries a positive assertion for **local decision testing**. This is not live verification. Borrowers cannot set that state themselves, and analysts can add it only in the explicitly labeled synthetic review-fixture mode. The `EXPIRED`, `FAILED`, `UNRESOLVED` and potential-match pathways are exercised in the test suite.
