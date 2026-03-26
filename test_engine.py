"""
ICICI Pre-Approval Engine — Test Suite
=======================================
Run:  python test_engine.py -v
"""

import unittest
from engine import (
    ApplicationInput, EmploymentType, Decision,
    evaluate, _score_cibil, _score_dti, _score_ltv,
    _score_income_stability, _score_relationship,
    _estimate_emi, _recommend_loan_amount,
)


class TestCIBILScoring(unittest.TestCase):

    def test_excellent(self):
        score, _ = _score_cibil(820)
        self.assertEqual(score, 100.0)

    def test_very_good(self):
        score, _ = _score_cibil(760)
        self.assertEqual(score, 85.0)

    def test_good(self):
        score, _ = _score_cibil(720)
        self.assertEqual(score, 70.0)

    def test_acceptable(self):
        score, _ = _score_cibil(660)
        self.assertEqual(score, 50.0)

    def test_hard_stop(self):
        score, _ = _score_cibil(640)
        self.assertEqual(score, 0.0)

    def test_floor_boundary(self):
        score, _ = _score_cibil(650)
        self.assertEqual(score, 50.0)


class TestDTIScoring(unittest.TestCase):

    def test_healthy_dti(self):
        # EMI ~₹8,700 on a ₹10L loan; income ₹1L → DTI ≈ 8.7%
        emi = _estimate_emi(1_000_000)
        dti, score, _ = _score_dti(100_000, 0, emi)
        self.assertLessEqual(dti, 0.30)
        self.assertEqual(score, 100.0)

    def test_hard_stop_dti(self):
        emi = _estimate_emi(10_000_000)
        dti, score, _ = _score_dti(100_000, 50_000, emi)
        self.assertGreater(dti, 0.65)
        self.assertEqual(score, 0.0)

    def test_zero_income_guard(self):
        _, score, _ = _score_dti(0, 0, 10_000)
        self.assertEqual(score, 0.0)


class TestLTVScoring(unittest.TestCase):

    def test_low_ltv(self):
        ltv, score, _ = _score_ltv(5_000_000, 10_000_000)   # 50%
        self.assertAlmostEqual(ltv, 0.50)
        self.assertEqual(score, 100.0)

    def test_acceptable_ltv(self):
        ltv, score, _ = _score_ltv(7_200_000, 10_000_000)   # 72%
        self.assertAlmostEqual(ltv, 0.72)
        self.assertEqual(score, 65.0)

    def test_hard_stop_ltv(self):
        ltv, score, _ = _score_ltv(9_500_000, 10_000_000)   # 95%
        self.assertGreater(ltv, 0.90)
        self.assertEqual(score, 0.0)

    def test_zero_property_guard(self):
        _, score, _ = _score_ltv(5_000_000, 0)
        self.assertEqual(score, 0.0)


class TestIncomeStabilityScoring(unittest.TestCase):

    def test_psu_long_tenure(self):
        score, _ = _score_income_stability(EmploymentType.SALARIED_PSU, 6.0, 100_000)
        self.assertEqual(score, 100.0)   # 90 base + 10 tenure mod

    def test_contract_short_tenure(self):
        score, _ = _score_income_stability(EmploymentType.CONTRACT, 0.5, 80_000)
        self.assertEqual(score, 20.0)   # 35 base - 15 tenure mod

    def test_cap_at_100(self):
        score, _ = _score_income_stability(EmploymentType.SALARIED_PSU, 10.0, 500_000)
        self.assertLessEqual(score, 100.0)


class TestRelationshipScoring(unittest.TestCase):

    def test_new_customer(self):
        score, _ = _score_relationship(0, 0)
        self.assertEqual(score, 0.0)

    def test_loyal_customer(self):
        score, _ = _score_relationship(10, 4)
        self.assertEqual(score, 100.0)

    def test_partial(self):
        score, _ = _score_relationship(2, 1)
        self.assertEqual(score, 40.0)   # 30 + 10


class TestFullEvaluation(unittest.TestCase):

    def _strong_app(self) -> ApplicationInput:
        return ApplicationInput(
            applicant_name="Test Approval",
            cibil_score=790,
            monthly_income=350_000,
            monthly_obligations=25_000,
            requested_loan_amt=12_000_000,
            property_value=18_000_000,
            employment_type=EmploymentType.SALARIED_MNC,
            years_employed=7.5,
            relationship_years=6.0,
            existing_products=3,
        )

    def _weak_app(self) -> ApplicationInput:
        return ApplicationInput(
            applicant_name="Test Rejection",
            cibil_score=610,
            monthly_income=80_000,
            monthly_obligations=45_000,
            requested_loan_amt=5_000_000,
            property_value=5_500_000,
            employment_type=EmploymentType.CONTRACT,
            years_employed=0.5,
            relationship_years=0.0,
            existing_products=0,
        )

    def test_auto_approval(self):
        result = evaluate(self._strong_app())
        self.assertEqual(result.decision, Decision.AUTO_APPROVAL)
        self.assertGreaterEqual(result.composite_score, 80.0)

    def test_auto_rejection_hard_stop(self):
        result = evaluate(self._weak_app())
        self.assertEqual(result.decision, Decision.AUTO_REJECTION)
        self.assertGreater(len(result.hard_stop_reasons), 0)

    def test_priority_review_band(self):
        # Borderline application — should land 60–79
        app = ApplicationInput(
            applicant_name="Test Review",
            cibil_score=710,
            monthly_income=180_000,
            monthly_obligations=15_000,
            requested_loan_amt=5_000_000,
            property_value=8_000_000,
            employment_type=EmploymentType.SALARIED_PRIVATE,
            years_employed=2.5,
            relationship_years=1.5,
            existing_products=1,
        )
        result = evaluate(app)
        self.assertEqual(result.decision, Decision.PRIORITY_REVIEW)
        self.assertGreaterEqual(result.composite_score, 60.0)
        self.assertLess(result.composite_score, 80.0)

    def test_composite_score_bounded(self):
        result = evaluate(self._strong_app())
        self.assertGreaterEqual(result.composite_score, 0.0)
        self.assertLessEqual(result.composite_score, 100.0)

    def test_all_signals_present(self):
        result = evaluate(self._strong_app())
        expected = {"cibil", "dti", "ltv", "income_stability", "relationship_score"}
        self.assertEqual(set(result.signals.keys()), expected)

    def test_weights_sum_to_one(self):
        from engine import WEIGHTS
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=10)

    def test_recommended_amount_on_rejection(self):
        result = evaluate(self._weak_app())
        # Even if rejected, may provide a recommended lower amount
        # (could be None if even a minimal loan isn't viable)
        if result.recommended_amt is not None:
            self.assertGreater(result.recommended_amt, 0)

    def test_to_dict_serialisable(self):
        import json
        result = evaluate(self._strong_app())
        d = result.to_dict()
        json_str = json.dumps(d)   # must not raise
        self.assertIn("composite_score", json_str)

    def test_emi_positive(self):
        emi = _estimate_emi(5_000_000)
        self.assertGreater(emi, 0)

    def test_recommend_lower_than_requested(self):
        result = evaluate(self._weak_app())
        if result.recommended_amt:
            self.assertLess(result.recommended_amt, 5_000_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
