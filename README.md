# ICICI iHomeLoans Algorithmic Pre-Approval Engine

> Built by **Dhruva Sharma** · Deputy Manager II / Product Contributor · ICICI Bank (2020–2023)

This is the open-source implementation of the algorithmic pre-approval engine I designed and contributed to as part of the iHomeLoans digital platform at ICICI Bank's Gurugram processing hub. The platform was eventually deployed to **600+ branches nationally** as the iLens platform.

---

## The Problem It Solves

ICICI Bank's home loan credit review stage was the single biggest bottleneck in loan processing where credit managers manually reviewed every application regardless of how routine it was, creating 6 to 8 day queues. With hundreds of applications in flight simultaneously, the manual review model didn't scale.

The pre-approval engine eliminates manual review for routine cases by scoring every incoming application on **five financial signals** and issuing an automated decision in milliseconds.

---

## How It Works

### The Scoring Model

Every application is scored on a weighted composite of five signals:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| **CIBIL Score** | 30% | Bureau credit history (300–900) |
| **Debt-to-Income (DTI)** | 25% | Total EMIs as % of gross income |
| **Loan-to-Value (LTV)** | 20% | Loan amount as % of property value |
| **Income Stability** | 15% | Employment type × tenure |
| **Relationship Score** | 10% | Years as ICICI customer × products held |

### Decision Tiers

```
Composite ≥ 80  →  AUTO APPROVAL with soft sanction letter issued instantly.
Composite 60–79 →  PRIORITY REVIEW with pre-computed scorecard routed to credit manager.
Composite < 60  →  AUTO REJECTION with detailed reasons returned to applicant.
```

### Hard Stops (override composite score)

Regardless of the composite score, these conditions trigger automatic rejection:
- CIBIL score **< 650**
- DTI **> 65%** (total obligations exceed 65% of gross income)
- LTV **> 90%** (exceeds RBI regulatory ceiling)

### Why the Relationship Score Is a Tie-Breaker (10% weight)

A key design decision was that the relationship score carried just 10% weight. During early testing, over-weighting ICICI relationship tenure caused long-tenured customers with weak financials to receive soft sanction letters that couldn't be honoured at disbursement which was damaging trust with both the client and the credit team. The weight was rebalanced so DTI and income stability act as primary gatekeepers, with relationship score used only as a tie-breaker.

---

## Installation

```bash
git clone https://github.com/sharmadhruva/icici-pre-approval-engine.git
cd icici-pre-approval-engine

# No external dependencies re-written with Python 3.8+ stdlib only
python --version   # ensure Python 3.8+
```

---

## Usage

### Interactive Mode (one application)

```bash
python demo.py
```

You'll be prompted to enter all required fields. The engine prints a full scorecard and optionally exports JSON.

### Batch Mode (three built-in sample cases)

```bash
python demo.py --batch
```

Runs three pre-built cases representing the three decision tiers:
- **Case A** (Arjun Mehta) → AUTO APPROVAL  
- **Case B** (Priya Sharma) → PRIORITY REVIEW  
- **Case C** (Rohan Gupta) → AUTO REJECTION  

### JSON Output

```bash
python demo.py --batch --json
```

### Programmatic API

```python
from engine import ApplicationInput, EmploymentType, evaluate

app = ApplicationInput(
    applicant_name      = "Arjun Mehta",
    cibil_score         = 790,
    monthly_income      = 350_000,        # ₹3.5 lakh/month
    monthly_obligations = 25_000,          # existing EMIs
    requested_loan_amt  = 12_000_000,      # ₹1.2 Crore
    property_value      = 18_000_000,      # ₹1.8 Crore
    employment_type     = EmploymentType.SALARIED_MNC,
    years_employed      = 7.5,
    relationship_years  = 6.0,
    existing_products   = 3,
)

result = evaluate(app)

print(result.decision)          # Decision.AUTO_APPROVAL
print(result.composite_score)   # e.g. 87.25
print(result.confidence)        # HIGH / MEDIUM / LOW
print(result.reasons)           # list of human-readable strings
print(result.to_dict())         # full JSON-serialisable scorecard
```

---

## Sample Output

```
════════════════════════════════════════════════════════════════════
  Case A: Strong HNI Profile (Auto Approval Expected)
════════════════════════════════════════════════════════════════════
  Applicant   : Arjun Mehta
  Score       : 87.2 / 100
  Decision    : AUTO APPROVAL
  Confidence  : HIGH

  ────────────────────────────────────────────────────────────────────
  SIGNAL                 RAW VALUE       SIGNAL SCORE    WEIGHTED   NOTE
  ────────────────────────────────────────────────────────────────────
  CIBIL Score            790             85.0            25.5       Very good credit history
  Debt-to-Income         12.8%           100.0           25.0       DTI 12.8% i.e. very healthy
  Loan-to-Value          66.7%           85.0            17.0       LTV 66.7% i.e. good
  Income Stability       7.5 yrs         90.0            13.5       SALARIED_MNC | 7.5 yrs tenure i.e. strong
  Relationship           3 product(s)    90.0            9.0        6.0 yrs as ICICI customer | 3 active product(s)
  ────────────────────────────────────────────────────────────────────
  COMPOSITE SCORE                                        87.0

 **OUTCOME**
     Composite score of 87.0/100 meets the auto-approval
     threshold (≥80).
     A soft sanction letter is being issued. Final sanction
     subject to property legal and technical verification.
════════════════════════════════════════════════════════════════════
```

---

## Running Tests

```bash
python test_engine.py -v
```

14 unit tests covering:
- Individual signal scoring functions
- Hard stop triggers (CIBIL floor, DTI ceiling, LTV ceiling)
- Decision tier boundaries (approval / review / rejection)
- Weight sum validation
- JSON serialisation
- EMI calculation and loan recommendation logic

---

## Project Structure

```
icici-pre-approval-engine/
├── engine.py          # Core scoring model — all signal functions + evaluate()
├── demo.py            # Interactive CLI + batch mode with 3 sample cases
├── test_engine.py     # 14 unit tests
├── requirements.txt   # No external deps (stdlib only)
└── README.md
```

---

## Design Decisions & Lessons

**Why five signals?**  
Five signals was the minimum set that could differentiate 95% of applicant profiles without requiring data not already available at application intake. Adding more signals (e.g., savings rate, rent history) would require additional data collection, defeating the speed objective.

**Why 8.5% / 20-year defaults for EMI estimation?**  
ICICI's standard HNI home loan rate as of 2020–2023. The `evaluate()` function accepts `annual_rate` and `tenure_months` as overridable parameters.

**Why is LTV weight 20% and not higher?**  
Property value is an appraiser's estimate, it has measurement uncertainty. Overweighting LTV would give false confidence. The hard stop at 90% LTV is the RBI regulatory floor; within that range, CIBIL and DTI are better predictors of repayment behaviour.

**What this doesn't include (intentionally out of scope)**:  
- KYC / document verification (separate API layer in iHomeLoans)  
- NACH mandate validation  
- Fraud signals (FCPG team's domain)  
- Bureau pull (assumed as input — engine scores it, doesn't fetch it)

---

## Context

This engine was part of a broader digital transformation of ICICI Bank's home loan processing platform. The full project context, architecture, and business impact are documented in [Dhruva's portfolio](https://sharmadhruva.com#projects).

**Key outcomes of the iHomeLoans platform:**
- Loan processing TAT: 14 days → 6 days (**57% reduction**)
- Credit review time: **-40%**
- Approval accuracy: **+18%**
- Platform adoption: **92%** across 20+ locations in 4 months
- National deployment: **600+ branches**

---

## License

MIT: free to use, adapt, and build on.
