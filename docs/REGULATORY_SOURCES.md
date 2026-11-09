# Regulatory source register (research references, not legal certification)

**Source review date:** 10 November 2026. All entries below are official RBI publications. The prototype records the sources so that regulated implementation can trace requirements to a specific authority; it does **not** claim that all applicable clauses have been encoded, correctly interpreted, signed off or independently audited.

| Area | Primary source | Official link | Version observed | Software coverage | Sign-off |
| --- | --- | --- | --- | --- | --- |
| HFC regulation and Fair Practices Code | Reserve Bank of India (Housing Finance Companies) Directions, 2025 | https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12939 | Updated as on **1 October 2026**; Chapter X: Fair Practices Code | Policy source register only; synthetic thresholds, no RBI rule hardcoding | Outstanding lender/legal review |
| Non-banking-company KYC/AML | RBI (Non-Banking Financial Companies – Know Your Customer) Directions, 2025 | https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12943 | Updated **29 December 2025**; customer acceptance, identification, due diligence, record management | Identity evidence prerequisite and unresolved screening review only | Outstanding KYC/AML review and approved providers |
| Digital lending | RBI (Digital Lending) Directions, 2025 | https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12848 | Issued **8 May 2025**; applicability includes HFCs, provisions on disclosures and borrower data | Consent workflow and disclosure placeholders only | Outstanding legal/control mapping |

## Control interpretation strategy

The application deliberately does **not** hardcode an RBI-mandated universal FOIR/LTV value. The `policies/` ratios are strictly labeled demonstration assumptions. Final HFC policy requires verified current sources, applicability determination, counsel-approved interpretations, policy-approval workflow and signed audit evidence.

Recommended regulated control metadata: `authority`, `source_url`, `document_version`, `exact_clause`, `effective_date`, `applicability`, `interpretation`, `required_evidence`, `algorithm`, `failure_behavior`, `reviewer`, `approval_reference`. The current prototype does not maintain a populated clause-by-clause executable legal registry; that work is explicitly outstanding.

## Key boundaries

- Sanctions/PEP screening fixture outcomes cannot establish true AML compliance.
- Local KYC status is an asserted fixture status, not access to an authorized official identity system.
- Property title and lien clearance require applicable legal and professional verification; the valuation fixture is not title proof.
- A demonstration approval is not a sanction, KFS or loan agreement, and never disburses funds.

The lender must assess the applicability and versions of all RBI and related official sources during actual implementation; these references are research inputs, not a warranty of completeness or legal advice.
