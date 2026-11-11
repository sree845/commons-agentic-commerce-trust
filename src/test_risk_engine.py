import unittest
from risk_engine import RiskEngine


class TestRiskEngine(unittest.TestCase):

    def setUp(self):
        self.engine = RiskEngine()

        self.test_orders = {
            "Low-risk test": {
                "amount": 10.0,
                "mandate_cap": 500.0,
                "category_allowed": 1,
                "mandate_age_days": 179,
                "orders_per_hour": 1,
                "address_changed": 0,
                "payment_retries": 0,
                "amount_vs_merchant_norm": 10.0 / 75.0,
                "shared_agent_flag_count": 0
            },
            "Medium-risk test": {
                "amount": 45.0,
                "mandate_cap": 100.0,
                "category_allowed": 1,
                "mandate_age_days": 60,
                "orders_per_hour": 2,
                "address_changed": 0,
                "payment_retries": 0,
                "amount_vs_merchant_norm": 45.0 / 75.0,
                "shared_agent_flag_count": 0
            },
            "High-risk test": {
                "amount": 250.0,
                "mandate_cap": 100.0,
                "category_allowed": 0,
                "mandate_age_days": 5,
                "orders_per_hour": 20,
                "address_changed": 1,
                "payment_retries": 8,
                "amount_vs_merchant_norm": 250.0 / 75.0,
                "shared_agent_flag_count": 1
            }
        }

    def test_low_risk_order(self):
        result = self.engine.score_order(
            self.test_orders["Low-risk test"]
        )
        self.assertEqual(result["decision"], "HOLD")
        self.assertGreaterEqual(result["risk_percentage"], 0)
        self.assertLessEqual(result["risk_percentage"], 100)

    def test_medium_risk_order(self):
        result = self.engine.score_order(
            self.test_orders["Medium-risk test"]
        )
        self.assertEqual(result["decision"], "HOLD")
        self.assertGreaterEqual(result["risk_percentage"], 0)
        self.assertLessEqual(result["risk_percentage"], 100)

    def test_high_risk_order(self):
        result = self.engine.score_order(
            self.test_orders["High-risk test"]
        )
        self.assertEqual(result["decision"], "VOID")
        self.assertGreaterEqual(result["risk_percentage"], 0)
        self.assertLessEqual(result["risk_percentage"], 100)

    def test_risk_scores_increase_with_risk(self):
        low = self.engine.score_order(
            self.test_orders["Low-risk test"]
        )["risk_percentage"]

        medium = self.engine.score_order(
            self.test_orders["Medium-risk test"]
        )["risk_percentage"]

        high = self.engine.score_order(
            self.test_orders["High-risk test"]
        )["risk_percentage"]

        self.assertLess(low, medium)
        self.assertLess(medium, high)


if __name__ == "__main__":
    unittest.main()
