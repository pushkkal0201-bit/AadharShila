"""Non-binding conditional-loan preview and regulated-disbursement block."""
from __future__ import annotations
from datetime import datetime, timezone


def preview(assessment, application, *, borrower_view: bool = False):
    """Borrower-facing preview is not a sanction letter or KFS."""
    decision=assessment.result
    accepted=decision.get('financials') or {}
    # A sanction preview is borrower-readable. Fraud and AML escalation codes
    # belong only in staff reports: disclosing them can compromise a review.
    internal_codes={'SCREENING_POTENTIAL_MATCH','SCREENING_UNRESOLVED',
                    'DOCUMENT_REUSE_REVIEW','PROVIDER_UNAVAILABLE','TECHNICAL_FAILURE'}
    reasons=decision.get('reasons',[])
    visible=[item for item in reasons if not (borrower_view and
             (item.get('code','').startswith('SCREENING_') or item.get('code') in internal_codes))]
    blockers=[{'code':item['code'],'status':item['status']} for item in visible]
    if borrower_view and len(visible)<len(reasons) and assessment.outcome=='REFER':
        blockers.append({'code':'ADDITIONAL_REVIEW_REQUIRED','status':'UNRESOLVED'})
    return {'type':'NON_BINDING_ASSESSMENT_PREVIEW',
            'application_id':application.id,'assessment_id':assessment.id,
            'decision':assessment.outcome,
            'principal_requested_inr':float(application.amount),
            'illustrative_emi_inr':accepted.get('emi'),
            'illustrative_total_interest_inr':accepted.get('total_interest'),
            'policy_version':decision.get('policy_version'),
            'blockers':blockers,
            'prerequisites':{'borrower_acceptance':'NOT_COLLECTED',
                             'lender_sanction_authority':'NOT_ATTESTED',
                             'legal_title':'REQUIRES_INSTITUTIONAL_REVIEW',
                             'regulated_disclosures':'NOT_ISSUED',
                             'disbursement':'BLOCKED'},
            'issued_at':datetime.now(timezone.utc).isoformat(),
            'binding':False,
            'disclaimer':'This is not a sanction, Key Facts Statement, loan agreement, or authorization to disburse funds.'}
