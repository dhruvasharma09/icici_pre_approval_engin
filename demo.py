"""
ICICI Pre-Approval Engine — Interactive Demo
============================================
Run:  python demo.py
      python demo.py --batch   (runs all three sample cases)
"""

import argparse
import json
from engine import (
    ApplicationInput, EmploymentType,
    Decision, evaluate, _estimate_emi
)

# ─────────────────────────────────────────────
#  SAMPLE CASES
# ─────────────────────────────────────────────

SAMPLE_CASES = [
    {
        "label": "Case A — Strong HNI Profile (Auto Approval Expected)",
        "input": ApplicationInput(
            applicant_name      = "Arjun Mehta",
            cibil_score         = 790,
            monthly_income      = 350_000,        # ₹3.5L/mo
            monthly_obligations = 25_000,          # ₹25K existing EMI
            requested_loan_amt  = 12_000_000,      # ₹1.2 Cr loan
            property_value      = 18_000_000,      # ₹1.8 Cr property
            employment_type     = EmploymentType.SALARIED_MNC,
            years_employed      = 7.5,
            relationship_years  = 6.0,
            existing_products   = 3,
        ),
    },
    {
        "label": "Case B — Mid-Tier Salaried (Priority Review Expected)",
        "input": ApplicationInput(
            applicant_name      = "Priya Sharma",
            cibil_score         = 710,
            monthly_income      = 180_000,         # ₹1.8L/mo
            monthly_obligations = 15_000,           # ₹15K existing EMI
            requested_loan_amt  = 5_000_000,        # ₹50L loan
            property_value      = 8_000_000,        # ₹80L property
            employment_type     = EmploymentType.SALARIED_PRIVATE,
            years_employed      = 2.5,
            relationship_years  = 1.5,
            existing_products   = 1,
        ),
    },
    {
        "label": "Case C — High-Risk Profile (Auto Rejection Expected)",
        "input": ApplicationInput(
            applicant_name      = "Rohan Gupta",
            cibil_score         = 610,             # below floor
            monthly_income      = 80_000,
            monthly_obligations = 45_000,           # very high existing debt
            requested_loan_amt  = 5_000_000,
            property_value      = 5_500_000,        # LTV ~91% — too high
            employment_type     = EmploymentType.CONTRACT,
            years_employed      = 0.5,
            relationship_years  = 0.0,
            existing_products   = 0,
        ),
    },
]


# ─────────────────────────────────────────────
#  FORMATTERS
# ─────────────────────────────────────────────

DECISION_LABELS = {
    Decision.AUTO_APPROVAL:   "✅  AUTO APPROVAL",
    Decision.PRIORITY_REVIEW: "🔶  PRIORITY REVIEW",
    Decision.AUTO_REJECTION:  "❌  AUTO REJECTION",
}

SIGNAL_DISPLAY = {
    "cibil":              ("CIBIL Score",       "cibil_score",       lambda v: f"{int(v)}"),
    "dti":                ("Debt-to-Income",    "raw_value",         lambda v: f"{v*100:.1f}%"),
    "ltv":                ("Loan-to-Value",     "raw_value",         lambda v: f"{v*100:.1f}%"),
    "income_stability":   ("Income Stability",  "years_employed",    lambda v: f"{v:.1f} yrs"),
    "relationship_score": ("Relationship",      "existing_products", lambda v: f"{int(v)} product(s)"),
}


def print_result(label: str, result) -> None:
    width = 68
    sep   = "─" * width

    print(f"\n{'═' * width}")
    print(f"  {label}")
    print(f"{'═' * width}")
    print(f"  Applicant   : {result.applicant_name}")
    print(f"  Score       : {result.composite_score:.1f} / 100")
    print(f"  Decision    : {DECISION_LABELS[result.decision]}")
    print(f"  Confidence  : {result.confidence}")

    print(f"\n  {sep}")
    print(f"  {'SIGNAL':<22} {'RAW VALUE':<15} {'SIGNAL SCORE':<15} {'WEIGHTED':<10} {'NOTE'}")
    print(f"  {sep}")

    for key, sb in result.signals.items():
        sig_name = {
            "cibil":              "CIBIL Score",
            "dti":                "Debt-to-Income",
            "ltv":                "Loan-to-Value",
            "income_stability":   "Income Stability",
            "relationship_score": "Relationship",
        }[key]

        raw_str = {
            "cibil":              f"{int(sb.raw_value)}",
            "dti":                f"{sb.raw_value*100:.1f}%",
            "ltv":                f"{sb.raw_value*100:.1f}%",
            "income_stability":   f"{sb.raw_value:.1f} yrs",
            "relationship_score": f"{int(sb.raw_value)} product(s)",
        }[key]

        print(f"  {sig_name:<22} {raw_str:<15} {sb.signal_score:<15.1f} {sb.weighted:<10.1f} {sb.note}")

    print(f"  {sep}")
    print(f"  {'COMPOSITE SCORE':<55} {result.composite_score:.1f}")
    print(f"  {sep}")

    if result.hard_stop_reasons:
        print(f"\n  ⛔  HARD STOPS")
        for r in result.hard_stop_reasons:
            print(f"     • {r}")

    if result.soft_flags:
        print(f"\n  ⚠️   SOFT FLAGS")
        for f in result.soft_flags:
            print(f"     • {f}")

    print(f"\n  📋  OUTCOME")
    for r in result.reasons:
        # word-wrap at ~62 chars
        words   = r.split()
        line    = ""
        for word in words:
            if len(line) + len(word) + 1 > 62:
                print(f"     {line}")
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            print(f"     {line}")

    if result.recommended_amt:
        print(f"\n  💡  Max eligible amount: ₹{result.recommended_amt:,.0f}")

    print(f"\n{'═' * width}\n")


# ─────────────────────────────────────────────
#  INTERACTIVE MODE
# ─────────────────────────────────────────────

EMPLOYMENT_MAP = {
    "1": EmploymentType.SALARIED_PSU,
    "2": EmploymentType.SALARIED_MNC,
    "3": EmploymentType.SALARIED_PRIVATE,
    "4": EmploymentType.SELF_EMPLOYED_CA,
    "5": EmploymentType.SELF_EMPLOYED_BIZ,
    "6": EmploymentType.CONTRACT,
}


def _get_float(prompt: str) -> float:
    while True:
        try:
            return float(input(prompt).replace(",", "").replace("₹", "").strip())
        except ValueError:
            print("  Please enter a valid number.")


def _get_int(prompt: str) -> int:
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("  Please enter a valid integer.")


def interactive_mode() -> None:
    print("\n" + "═" * 68)
    print("  ICICI iHomeLoans — Pre-Approval Engine  (Interactive Mode)")
    print("═" * 68)

    name = input("\n  Applicant name          : ").strip() or "Applicant"
    cibil = _get_int("  CIBIL score (300–900)   : ")
    income = _get_float("  Gross monthly income (₹): ")
    obligations = _get_float("  Existing EMIs/month  (₹): ")
    loan_amt = _get_float("  Loan amount requested (₹): ")
    prop_val = _get_float("  Property value        (₹): ")

    print("\n  Employment type:")
    print("    1 — Salaried (Government / PSU)")
    print("    2 — Salaried (MNC / listed company)")
    print("    3 — Salaried (Private / unlisted)")
    print("    4 — Self-employed professional (CA, doctor)")
    print("    5 — Self-employed business owner (≥3 yrs ITR)")
    print("    6 — Contract / freelance")
    emp_choice = input("  Enter choice (1–6)      : ").strip()
    emp_type = EMPLOYMENT_MAP.get(emp_choice, EmploymentType.SALARIED_PRIVATE)

    years_emp = _get_float("  Years at current job    : ")
    rel_years = _get_float("  Years as ICICI customer : ")
    products  = _get_int  ("  ICICI products held     : ")

    app = ApplicationInput(
        applicant_name      = name,
        cibil_score         = cibil,
        monthly_income      = income,
        monthly_obligations = obligations,
        requested_loan_amt  = loan_amt,
        property_value      = prop_val,
        employment_type     = emp_type,
        years_employed      = years_emp,
        relationship_years  = rel_years,
        existing_products   = products,
    )

    result = evaluate(app)
    print_result("Your Application Result", result)

    export = input("  Export result to JSON? (y/n): ").strip().lower()
    if export == "y":
        fname = f"{name.replace(' ', '_').lower()}_scorecard.json"
        with open(fname, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"  Saved → {fname}\n")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ICICI Pre-Approval Engine")
    parser.add_argument("--batch",  action="store_true", help="Run all sample test cases")
    parser.add_argument("--json",   action="store_true", help="Output JSON (use with --batch)")
    args = parser.parse_args()

    if args.batch:
        for case in SAMPLE_CASES:
            result = evaluate(case["input"])
            if args.json:
                print(json.dumps(result.to_dict(), indent=2))
            else:
                print_result(case["label"], result)
    else:
        interactive_mode()
