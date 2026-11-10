"""Clause-referenced evidence completeness registry, pending lender/legal validation.

These checks are internal document-presence diagnostics. They do not assert legal
compliance; applicability and clause interpretation require lender counsel.
"""
from __future__ import annotations

SOURCE_DIGITAL='https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12848'
SOURCE_HFC='https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12939'
SOURCE_KYC='https://www.rbi.org.in/scripts/NotificationUser.aspx?Id=12943'

CONTROL_REGISTRY=[
 {'id':'DLD_2025_7_CREDITWORTHINESS','authority':'RBI','source_url':SOURCE_DIGITAL,
  'source_clause':'Digital Lending Directions 2025 §7','area':'Borrower creditworthiness',
  'implementation':'EVIDENCE_PREREQUISITE','legal_validation':'PENDING'},
 {'id':'DLD_2025_8_DISCLOSURES','authority':'RBI','source_url':SOURCE_DIGITAL,
  'source_clause':'Digital Lending Directions 2025 §8','area':'Borrower disclosures / KFS',
  'implementation':'NOT_IMPLEMENTED','legal_validation':'PENDING'},
 {'id':'DLD_2025_12_CONSENT','authority':'RBI','source_url':SOURCE_DIGITAL,
  'source_clause':'Digital Lending Directions 2025 §12','area':'Purpose-specific borrower data processing',
  'implementation':'PARTIAL_CONSENT_GATE','legal_validation':'PENDING'},
 {'id':'HFC_2025_FAIR_PRACTICES','authority':'RBI','source_url':SOURCE_HFC,
  'source_clause':'Housing Finance Companies Directions 2025 Chapter X','area':'Fair Practices Code',
  'implementation':'NOT_IMPLEMENTED','legal_validation':'PENDING'},
 {'id':'NBFC_KYC_2025_CDD','authority':'RBI','source_url':SOURCE_KYC,
  'source_clause':'NBFC Know Your Customer Directions 2025 — CDD','area':'Customer due diligence',
  'implementation':'EVIDENCE_PREREQUISITE','legal_validation':'PENDING'}
]


def check_application(snapshot:dict,decision:dict)->dict:
    ev=snapshot.get('evidence',{})
    consents=snapshot.get('consents',[])
    checks=[]
    for meta in CONTROL_REGISTRY:
        if meta['id']=='DLD_2025_7_CREDITWORTHINESS':
            present=decision.get('financials') is not None and ev.get('bank_income',{}).get('verification')=='VERIFIED'
        elif meta['id']=='DLD_2025_12_CONSENT':
            present='financial_underwriting' in consents
        elif meta['id']=='NBFC_KYC_2025_CDD':
            present=ev.get('identity',{}).get('verification')=='VERIFIED' and not ev.get('identity',{}).get('expired',True)
        else:present=False
        checks.append({**meta,'evidence_presence':'RECORDED' if present else 'MISSING',
                       'compliance_status':'NOT_ASSESSED',
                       'reason':'Regulatory applicability, interpretation and external evidence not signed off'})
    return {'controls':checks,'legal_certified':False,
            'institutional_signoff':'REQUIRED',
            'disbursement_permitted':False,
            'note':'Document-presence diagnostics only. No regulatory certification or binding loan approval.'}
