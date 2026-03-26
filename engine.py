"""
ICICI iHomeLoans — Algorithmic Pre-Approval Engine
===================================================
Composite 5-signal scoring model used to eliminate manual review
for routine home loan applications at ICICI Bank.

Signals & Weights
-----------------
  CIBIL Score          30%
  Debt-to-Income (DTI) 25%
  Loan-to-Value (LTV)  20%
  Income Stability     15%
  Relationship Score   10%

Decision Tiers
--------------
  Score ≥ 80  →  AUTO APPROVAL   — soft sanction letter issued instantly
  Score 60–79 →  PRIORITY REVIEW — pre-computed scorecard sent to credit manager
  Score < 60  →  AUTO REJECTION  — detailed reasons returned to applicant

Author : Dhruva Sharma  (ICICI Deputy Manager II / Product Contributor)
GitHub : github.com/sharmadhruva/icici-pre-approval-engine
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import math


# ─────────────────────────────────────────────
#  ENUMS
# ─────────────────────────────────────────────

class Decision(str, Enum):
    AUTO_APPROVAL   = "AUTO_APPROVAL"
    PRIORITY_REVIEW = "PRIORITY_REVIEW"
    AUTO_REJECTION  = "AUTO_REJECTION"


class EmploymentType(str, Enum):
    SALARIED_PSU      = "SALARIED_PSU"       # Government / PSU — most stable
    SALARIED_MNC      = "SALARIED_MNC"       # MNC / listed company
    SALARIED_PRIVATE  = "SALARIED_PRIVATE"   # Private company (unlisted)
    SELF_EMPLOYED_CA  = "SELF_EMPLOYED_CA"   # Professional (CA, doctor, etc.)
    SELF_EMPLOYED_BIZ = "SELF_EMPLOYED_BIZ"  # Business owner (≥3 yrs ITR)
    CONTRACT          = "CONTRACT"           # Contract / gig / freelance


# ─────────────────────────────────────────────
#  INPUT MODEL
# ─────────────────────────────────────────────

@dataclass
class ApplicationInput:
    """
    All fields required to score a home loan application.

    Parameters
    ----------
    applicant_name      : str
    cibil_score         : int    — 300–900 (CIBIL bureau score)
    monthly_income      : float  — Gross monthly income in INR
    monthly_obligations : float  — Total existing EMIs in INR
    requested_loan_amt  : float  — Loan amount requested in INR
    property_value      : float  — Market value of the property in INR
    employment_type     : EmploymentType
    years_employed      : float  — Years at current employer / in business
    relationship_years  : float  — Years as existing ICICI customer (0 if new)
    existing_products   : int    — Number of active ICICI products held
    """
    applicant_name      : str
    cibil_score         : int
    monthly_income      : float
    monthly_obligations : float
    requested_loan_amt  : float
    property_value      : float
    employment_type     : EmploymentType
    years_employed      : float
    relationship_years  : float  = 0.0
    existing_products   : int    = 0


# ─────────────────────────────────────────────
#  OUTPUT MODEL
# ─────────────────────────────────────────────

@dataclass
class SignalBreakdown:
    raw_value    : float
    signal_score : float   # 0–100 normalised score for this signal
    weighted     : float   # after applying signal weight
    weight       : float
    note         : str

@dataclass
class ScorecardResult:
    applicant_name    : str
    composite_score   : float
    decision          : Decision
    signals           : dict[str, SignalBreakdown]
    hard_stop_reasons : list[str]
    soft_flags        : list[str]
    reasons           : list[str]       # human-readable explanation
    recommended_amt   : Optional[float] # adjusted loan amount (if applicable)
    confidence        : str             # HIGH / MEDIUM / LOW

    def to_dict(self) -> dict:
        return {
            "applicant_name":    self.applicant_name,
            "composite_score":   round(self.composite_score, 2),
            "decision":          self.decision.value,
            "confidence":        self.confidence,
            "recommended_amt":   self.recommended_amt,
            "hard_stop_reasons": self.hard_stop_reasons,
            "soft_flags":        self.soft_flags,
            "reasons":           self.reasons,
            "signal_breakdown": {
                k: {
                    "raw_value":    round(v.raw_value, 4),
                    "signal_score": round(v.signal_score, 2),
                    "weighted":     round(v.weighted, 2),
                    "weight_pct":   f"{int(v.weight * 100)}%",
                    "note":         v.note,
                }
                for k, v in self.signals.items()
            },
        }


# ─────────────────────────────────────────────
#  SCORING FUNCTIONS  (one per signal)
# ─────────────────────────────────────────────

def _score_cibil(cibil: int) -> tuple[float, str]:
    """
    CIBIL bureau score → 0-100 signal score.
    Weight: 30%.

    Hard stop: CIBIL < 650 (non-negotiable floor).
    """
    if cibil >= 800:
        return 100.0, "Excellent credit history — top tier"
    elif cibil >= 750:
        return 85.0,  "Very good credit history"
    elif cibil >= 700:
        return 70.0,  "Good credit history — minor blemishes possible"
    elif cibil >= 650:
        return 50.0,  "Acceptable — heightened monitoring recommended"
    else:
        return 0.0,   "Below minimum floor (650) — hard stop triggered"


def _score_dti(monthly_income: float,
               monthly_obligations: float,
               requested_emi: float) -> tuple[float, float, str]:
    """
    Debt-to-Income ratio (DTI) → 0-100 signal score.
    Weight: 25%.

    DTI = (existing EMIs + new loan EMI) / gross monthly income.
    Hard stop: DTI > 65%.
    """
    if monthly_income <= 0:
        return 0.0, 0.0, "Income not provided"

    total_obligations = monthly_obligations + requested_emi
    dti = total_obligations / monthly_income

    if dti <= 0.30:
        score = 100.0
        note  = f"DTI {dti*100:.1f}% — very healthy"
    elif dti <= 0.40:
        score = 85.0
        note  = f"DTI {dti*100:.1f}% — good"
    elif dti <= 0.50:
        score = 65.0
        note  = f"DTI {dti*100:.1f}% — acceptable"
    elif dti <= 0.65:
        score = 35.0
        note  = f"DTI {dti*100:.1f}% — stretched; flag for review"
    else:
        score = 0.0
        note  = f"DTI {dti*100:.1f}% — exceeds 65% ceiling; hard stop triggered"

    return dti, score, note


def _score_ltv(loan_amount: float, property_value: float) -> tuple[float, float, str]:
    """
    Loan-to-Value ratio (LTV) → 0-100 signal score.
    Weight: 20%.

    Per RBI guidelines max LTV = 90% for loans < 30L, 80% otherwise.
    Hard stop: LTV > 90%.
    """
    if property_value <= 0:
        return 0.0, 0.0, "Property value not provided"

    ltv = loan_amount / property_value

    if ltv <= 0.60:
        score = 100.0
        note  = f"LTV {ltv*100:.1f}% — low risk, strong collateral cushion"
    elif ltv <= 0.70:
        score = 85.0
        note  = f"LTV {ltv*100:.1f}% — good"
    elif ltv <= 0.80:
        score = 65.0
        note  = f"LTV {ltv*100:.1f}% — acceptable per RBI norms"
    elif ltv <= 0.90:
        score = 35.0
        note  = f"LTV {ltv*100:.1f}% — at RBI ceiling; flag for review"
    else:
        score = 0.0
        note  = f"LTV {ltv*100:.1f}% — exceeds 90% RBI ceiling; hard stop triggered"

    return ltv, score, note


def _score_income_stability(employment_type: EmploymentType,
                            years_employed: float,
                            monthly_income: float) -> tuple[float, str]:
    """
    Income stability → 0-100 signal score.
    Weight: 15%.

    Combines employment type durability with tenure.
    """
    # Base score by employment type
    base_by_type = {
        EmploymentType.SALARIED_PSU:      90,
        EmploymentType.SALARIED_MNC:      80,
        EmploymentType.SALARIED_PRIVATE:  65,
        EmploymentType.SELF_EMPLOYED_CA:  70,
        EmploymentType.SELF_EMPLOYED_BIZ: 60,
        EmploymentType.CONTRACT:          35,
    }
    base = base_by_type[employment_type]

    # Tenure modifier
    if years_employed >= 5:
        modifier = +10
        tenure_note = f"{years_employed:.1f} yrs tenure — strong"
    elif years_employed >= 3:
        modifier = +5
        tenure_note = f"{years_employed:.1f} yrs tenure — adequate"
    elif years_employed >= 1:
        modifier = 0
        tenure_note = f"{years_employed:.1f} yr tenure — minimal"
    else:
        modifier = -15
        tenure_note = f"{years_employed:.1f} yr tenure — insufficient (< 1 yr)"

    score = min(100.0, max(0.0, base + modifier))
    note  = f"{employment_type.value} | {tenure_note}"
    return score, note


def _score_relationship(relationship_years: float,
                        existing_products: int) -> tuple[float, str]:
    """
    ICICI relationship score → 0-100 signal score.
    Weight: 10%.

    Tie-breaker only — never gates approval alone.
    """
    # Years component (max 60 pts)
    if relationship_years >= 10:
        year_pts = 60
    elif relationship_years >= 5:
        year_pts = 45
    elif relationship_years >= 2:
        year_pts = 30
    elif relationship_years >= 1:
        year_pts = 15
    else:
        year_pts = 0  # new-to-bank customer

    # Products component (max 40 pts)
    product_pts = min(40, existing_products * 10)

    score = float(year_pts + product_pts)
    note  = (f"{relationship_years:.1f} yrs as ICICI customer | "
             f"{existing_products} active product(s)")
    return score, note


# ─────────────────────────────────────────────
#  UTILITY: estimate new loan EMI
# ─────────────────────────────────────────────

def _estimate_emi(loan_amount: float,
                  annual_rate: float = 0.085,
                  tenure_months: int = 240) -> float:
    """
    Standard reducing-balance EMI formula.
    Default: 8.5% p.a., 20-year tenure.
    """
    r = annual_rate / 12
    emi = loan_amount * r * math.pow(1 + r, tenure_months) / (math.pow(1 + r, tenure_months) - 1)
    return emi


def _recommend_loan_amount(monthly_income: float,
                           monthly_obligations: float,
                           property_value: float,
                           annual_rate: float = 0.085,
                           tenure_months: int = 240,
                           max_dti: float = 0.50) -> float:
    """
    Maximum loan the applicant qualifies for at DTI ≤ max_dti
    and LTV ≤ 80%, whichever is lower.
    """
    affordable_emi  = (monthly_income * max_dti) - monthly_obligations
    if affordable_emi <= 0:
        return 0.0
    r = annual_rate / 12
    max_by_dti = affordable_emi * (math.pow(1 + r, tenure_months) - 1) / (r * math.pow(1 + r, tenure_months))
    max_by_ltv = property_value * 0.80
    return min(max_by_dti, max_by_ltv)


# ─────────────────────────────────────────────
#  MAIN ENGINE
# ─────────────────────────────────────────────

WEIGHTS = {
    "cibil":              0.30,
    "dti":                0.25,
    "ltv":                0.20,
    "income_stability":   0.15,
    "relationship_score": 0.10,
}

# Minimum CIBIL floor — hard stop regardless of composite score
CIBIL_HARD_FLOOR = 650
# Maximum DTI ceiling — hard stop regardless of composite score
DTI_HARD_CEILING = 0.65
# Maximum LTV ceiling — hard stop per RBI guidelines
LTV_HARD_CEILING = 0.90


def evaluate(app: ApplicationInput,
             annual_rate: float = 0.085,
             tenure_months: int = 240) -> ScorecardResult:
    """
    Score a home loan application and return a full ScorecardResult.

    Parameters
    ----------
    app            : ApplicationInput
    annual_rate    : float  — Home loan interest rate (default 8.5% p.a.)
    tenure_months  : int    — Loan tenure in months (default 240 = 20 yrs)

    Returns
    -------
    ScorecardResult
    """
    hard_stops : list[str] = []
    soft_flags : list[str] = []

    # ── Estimate new EMI ────────────────────────────────────
    requested_emi = _estimate_emi(app.requested_loan_amt, annual_rate, tenure_months)

    # ── Score each signal ───────────────────────────────────

    cibil_score, cibil_note = _score_cibil(app.cibil_score)
    dti_raw, dti_score, dti_note = _score_dti(
        app.monthly_income, app.monthly_obligations, requested_emi
    )
    ltv_raw, ltv_score, ltv_note = _score_ltv(
        app.requested_loan_amt, app.property_value
    )
    stab_score, stab_note = _score_income_stability(
        app.employment_type, app.years_employed, app.monthly_income
    )
    rel_score, rel_note = _score_relationship(
        app.relationship_years, app.existing_products
    )

    signals: dict[str, SignalBreakdown] = {
        "cibil": SignalBreakdown(
            raw_value=float(app.cibil_score),
            signal_score=cibil_score,
            weighted=cibil_score * WEIGHTS["cibil"],
            weight=WEIGHTS["cibil"],
            note=cibil_note,
        ),
        "dti": SignalBreakdown(
            raw_value=dti_raw,
            signal_score=dti_score,
            weighted=dti_score * WEIGHTS["dti"],
            weight=WEIGHTS["dti"],
            note=dti_note,
        ),
        "ltv": SignalBreakdown(
            raw_value=ltv_raw,
            signal_score=ltv_score,
            weighted=ltv_score * WEIGHTS["ltv"],
            weight=WEIGHTS["ltv"],
            note=ltv_note,
        ),
        "income_stability": SignalBreakdown(
            raw_value=app.years_employed,
            signal_score=stab_score,
            weighted=stab_score * WEIGHTS["income_stability"],
            weight=WEIGHTS["income_stability"],
            note=stab_note,
        ),
        "relationship_score": SignalBreakdown(
            raw_value=float(app.existing_products),
            signal_score=rel_score,
            weighted=rel_score * WEIGHTS["relationship_score"],
            weight=WEIGHTS["relationship_score"],
            note=rel_note,
        ),
    }

    # ── Composite score ─────────────────────────────────────
    composite = sum(s.weighted for s in signals.values())

    # ── Hard stop checks ────────────────────────────────────
    if app.cibil_score < CIBIL_HARD_FLOOR:
        hard_stops.append(
            f"CIBIL score {app.cibil_score} is below the minimum floor of {CIBIL_HARD_FLOOR}."
        )
    if dti_raw > DTI_HARD_CEILING:
        hard_stops.append(
            f"DTI of {dti_raw*100:.1f}% exceeds the 65% ceiling. "
            f"Existing + new EMI obligations: ₹{app.monthly_obligations + requested_emi:,.0f}/mo "
            f"against income of ₹{app.monthly_income:,.0f}/mo."
        )
    if ltv_raw > LTV_HARD_CEILING:
        hard_stops.append(
            f"LTV of {ltv_raw*100:.1f}% exceeds the RBI ceiling of 90%."
        )

    # ── Soft flags ──────────────────────────────────────────
    if app.years_employed < 1:
        soft_flags.append("Tenure at current employer < 1 year — income continuity risk.")
    if app.employment_type == EmploymentType.CONTRACT:
        soft_flags.append("Contract employment — income volatility; verify 2-year income history.")
    if app.relationship_years == 0 and app.existing_products == 0:
        soft_flags.append("New-to-bank customer — no relationship history to validate.")
    if dti_raw > 0.50:
        soft_flags.append(f"DTI above 50% ({dti_raw*100:.1f}%) — budget is stretched.")
    if ltv_raw > 0.80:
        soft_flags.append(f"LTV above 80% ({ltv_raw*100:.1f}%) — limited equity buffer.")

    # ── Decision logic ──────────────────────────────────────
    if hard_stops:
        decision = Decision.AUTO_REJECTION
    elif composite >= 80:
        decision = Decision.AUTO_APPROVAL
    elif composite >= 60:
        decision = Decision.PRIORITY_REVIEW
    else:
        decision = Decision.AUTO_REJECTION

    # ── Confidence ──────────────────────────────────────────
    if decision == Decision.AUTO_APPROVAL and not soft_flags:
        confidence = "HIGH"
    elif decision == Decision.AUTO_APPROVAL and soft_flags:
        confidence = "MEDIUM"
    elif decision == Decision.PRIORITY_REVIEW:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # ── Recommended loan amount (if rejected or reviewed) ───
    recommended_amt: Optional[float] = None
    if decision in (Decision.AUTO_REJECTION, Decision.PRIORITY_REVIEW):
        rec = _recommend_loan_amount(
            app.monthly_income, app.monthly_obligations, app.property_value
        )
        if rec > 0 and rec < app.requested_loan_amt:
            recommended_amt = rec

    # ── Human-readable reasons ──────────────────────────────
    reasons: list[str] = []

    if decision == Decision.AUTO_APPROVAL:
        reasons.append(
            f"Composite score of {composite:.1f}/100 meets the auto-approval threshold (≥80)."
        )
        reasons.append(
            "A soft sanction letter is being issued. Final sanction subject to property legal and technical verification."
        )
        if soft_flags:
            reasons.append(
                "Note: the following items should be reviewed at disbursement: " + "; ".join(soft_flags)
            )

    elif decision == Decision.PRIORITY_REVIEW:
        reasons.append(
            f"Composite score of {composite:.1f}/100 falls in the priority review band (60–79). "
            "Application has been routed to a credit manager with a pre-computed scorecard."
        )
        if soft_flags:
            reasons.append("Key flags for the credit manager: " + "; ".join(soft_flags))
        if recommended_amt:
            reasons.append(
                f"Suggested maximum loan amount at 50% DTI ceiling: ₹{recommended_amt:,.0f}."
            )

    else:  # AUTO_REJECTION
        reasons.append(
            f"Composite score of {composite:.1f}/100 does not meet the minimum threshold."
        )
        if hard_stops:
            reasons.extend(hard_stops)
        if recommended_amt:
            reasons.append(
                f"You may qualify for a lower loan amount of approximately ₹{recommended_amt:,.0f}. "
                "Please speak with your Relationship Manager to restructure the application."
            )
        else:
            reasons.append(
                "Based on current profile, a home loan cannot be sanctioned at this time. "
                "We recommend improving your CIBIL score and/or reducing existing obligations "
                "before reapplying."
            )

    return ScorecardResult(
        applicant_name=app.applicant_name,
        composite_score=composite,
        decision=decision,
        signals=signals,
        hard_stop_reasons=hard_stops,
        soft_flags=soft_flags,
        reasons=reasons,
        recommended_amt=recommended_amt,
        confidence=confidence,
    )
