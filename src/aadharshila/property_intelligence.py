"""Bounded comparable valuation and legal-evidence routing for manual reviewers.

This is not an automated title search, legal opinion or issuer verification.
Comparable evidence must be supported by an authorized valuer before acceptance.
"""
from __future__ import annotations
from decimal import Decimal
from statistics import median
from pydantic import BaseModel, Field
from .finance import D, cash

class Comparable(BaseModel):
    sale_reference: str = Field(min_length=3,max_length=90)
    area_sqm: Decimal = Field(gt=10,le=20000)
    sale_price_inr: Decimal = Field(gt=0,le=100000000000)
    distance_km: Decimal = Field(ge=0,le=100)
    months_ago: int = Field(ge=0,le=60)
    issuer_verified: bool = False

class PropertyReview(BaseModel):
    area_sqm: Decimal = Field(gt=10,le=20000)
    declared_value_inr: Decimal = Field(gt=0,le=100000000000)
    registry_checked: bool = False
    title_opinion_approved: bool = False
    cersai_checked: bool = False
    rera_applicable: bool|None = None
    rera_checked: bool = False
    valuation_report_approved: bool = False
    comparables: list[Comparable] = Field(default_factory=list,max_length=100)


def evaluate_property(data: PropertyReview) -> dict:
    legal_checks={'registry':data.registry_checked,
                  'title_opinion':data.title_opinion_approved,
                  'cersai':data.cersai_checked,
                  'rera':data.rera_checked if data.rera_applicable else data.rera_applicable is False,
                  'valuation_report':data.valuation_report_approved}
    eligible=[x for x in data.comparables
              if x.issuer_verified and x.distance_km<=D(10) and x.months_ago<=18]
    estimates=[D(x.sale_price_inr)/D(x.area_sqm) for x in eligible]
    estimate=cash(D(median(estimates))*D(data.area_sqm)) if len(eligible)>=3 else None
    missing=[k for k,v in legal_checks.items() if not v]
    if estimate is None:missing.append('comparable_coverage')
    return {'status':'REVIEW_REQUIRED' if missing else 'READY_FOR_INDEPENDENT_VALUER_REVIEW',
            'comparable_count':len(eligible),
            'indicative_median_valuation_inr':float(estimate) if estimate is not None else None,
            'declared_value_inr':float(cash(data.declared_value_inr)),
            'legal_checks':{k:'RECORDED_ASSERTION_NOT_VERIFIED' if v else 'UNRESOLVED' for k,v in legal_checks.items()},
            'missing_controls':missing,'automated_title_verified':False,
            'accepted_collateral_value_inr':None,
            'disclaimer':'Not an appraised value or ownership verification; registry and legal-report assertions need independent provider authentication.'}
