import unittest

from starlette.testclient import TestClient

from backend.main import app

OVERVIEW_SCENARIOS = [
    {
        "name": "A_w2_plus_long_term_gain",
        "payload": {"filing_status": "single", "w2_wages": 200000, "long_term_capital_gain": 50000},
        "expected": {
            "total_tax": 60465.20,
            "federal_income_tax": 37247.00,
            "long_term_capital_gains_tax": 7500.00,
            "net_investment_income_tax": 1900.00,
            "total_payroll_tax": 13818.20,
        },
    },
    {
        "name": "B_feie_rate_stacking",
        "payload": {"filing_status": "single", "foreign_earned_income": 200000, "days_abroad": 330},
        "expected": {
            "total_tax": 13200.00,
            "feie_excluded_income": 130000.00,
            "federal_income_tax": 13200.00,
        },
    },
    {
        "name": "C_self_employment_capital_gain_feie",
        "payload": {
            "filing_status": "single",
            "net_self_employment_profit": 60000,
            "long_term_capital_gain": 40000,
            "foreign_earned_income": 100000,
            "days_abroad": 330,
        },
        "expected": {
            "total_tax": 22236.87,
            "qbi_deduction": 8152.23,
            "feie_excluded_income": 100000.00,
            "total_payroll_tax": 8477.73,
        },
    },
    {
        "name": "D_self_employment_with_ca_state",
        "payload": {"filing_status": "single", "net_self_employment_profit": 100000, "state_code": "CA"},
        "expected": {
            "total_tax": 27311.11,
            "federal_income_tax": 8630.60,
            "total_payroll_tax": 14129.55,
            "state_income_tax": 4550.96,
        },
    },
]


class IncomeSummaryOverviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_frontend_overview_payloads_match_golden_totals(self):
        for scenario in OVERVIEW_SCENARIOS:
            with self.subTest(scenario=scenario["name"]):
                # Mirror the frontend, which hard-codes tax_year: 2025; this keeps the
                # 2025 contract locked even if the backend default tax_year changes later.
                response = self.client.post(
                    "/calc/income-summary",
                    json={"tax_year": 2025, **scenario["payload"]},
                )

                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["status"], "ok")
                result = body["result"]
                for field, expected in scenario["expected"].items():
                    if field == "state_income_tax":
                        self.assertEqual(result["state_income_tax"]["tax"], expected)
                    else:
                        self.assertEqual(result[field], expected)

                breakdown = {row["label"]: row["amount"] for row in body["breakdown"]}
                self.assertEqual(breakdown["total_tax"], scenario["expected"]["total_tax"])
                self.assertIn("federal_income_tax", breakdown)
                self.assertIn("total_payroll_tax", breakdown)


if __name__ == "__main__":
    unittest.main()
