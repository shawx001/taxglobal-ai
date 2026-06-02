import unittest

from engine import (
    bracket_tax,
    crypto_gain_estimate,
    federal_income_tax,
    feie_estimate,
    fica_tax,
    nexus_estimate,
    self_employment_tax,
    state_income_tax,
)
from engine.rules_loader import load_state_rules

EXPECTED_RESPONSE_KEYS = {
    "status",
    "input",
    "result",
    "breakdown",
    "rule_version",
    "citations",
    "assumptions",
    "reason",
}

class EngineTests(unittest.TestCase):
    def test_bracket_tax_uses_marginal_rates(self):
        brackets = [
            {"up_to": 10_000, "rate": 0.10},
            {"up_to": 20_000, "rate": 0.20},
            {"up_to": None, "rate": 0.30},
        ]

        self.assertEqual(bracket_tax(25_000, brackets), 4_500.00)

    def test_federal_income_tax_single_uses_2025_rules(self):
        result = federal_income_tax(120_000, "single")

        self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["reason"])
        self.assertEqual(result["result"]["taxable_income"], 105_000.00)
        self.assertEqual(result["result"]["tax"], 18_047.00)
        self.assertEqual(result["rule_version"], "us-2025-federal-v0.1")
        self.assertEqual(result["citations"][0]["source_id"], "irs_rp_2024_40")

    def test_federal_income_tax_accepts_prototype_filing_alias_without_using_prototype_rules(self):
        result = federal_income_tax(120_000, "mfj")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["input"]["filing_status"], "married_filing_jointly")
        self.assertEqual(result["result"]["taxable_income"], 90_000.00)
        self.assertEqual(result["result"]["tax"], 10_323.00)

    def test_fica_caps_social_security_and_applies_additional_medicare(self):
        result = fica_tax(250_000, "single")

        self.assertEqual(result["status"], "ok")
        self.assertIn("annual taxpayer filing-status thresholds", result["assumptions"][1])
        self.assertEqual(result["result"]["social_security_tax"], 10_918.20)
        self.assertEqual(result["result"]["medicare_tax"], 3_625.00)
        self.assertEqual(result["result"]["additional_medicare_tax"], 450.00)
        self.assertEqual(result["result"]["total"], 14_993.20)

    def test_fica_uses_mfj_additional_medicare_threshold(self):
        result = fica_tax(250_000, "married_filing_jointly")

        self.assertEqual(result["result"]["additional_medicare_tax"], 0.00)

    def test_feie_estimate_physical_presence_passes_at_330_days(self):
        result = feie_estimate(140_000, 330)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["qualifies_physical_presence_test"])
        self.assertEqual(result["result"]["excluded_income"], 130_000.00)
        self.assertEqual(result["result"]["remaining_income"], 10_000.00)

    def test_feie_estimate_physical_presence_fails_below_330_days(self):
        result = feie_estimate(140_000, 329)

        self.assertFalse(result["result"]["qualifies_physical_presence_test"])
        self.assertEqual(result["result"]["excluded_income"], 0.00)
        self.assertEqual(result["result"]["remaining_income"], 140_000.00)

    def test_state_income_tax_effective_zero_tax_state(self):
        result = state_income_tax("FL", 100_000)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["tax"], 0.00)
        self.assertEqual(result["citations"][0]["source_id"], "fl_personal_income_tax_faq")

    def test_state_income_tax_effective_flat_tax_state(self):
        result = state_income_tax("IL", 100_000)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["tax"], 4_950.00)
        self.assertEqual(result["result"]["rate"], 0.0495)

    def test_state_income_tax_blocks_pending_extraction_states(self):
        result = state_income_tax("CA", 100_000)

        self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(result["status"], "not_covered")
        self.assertIn("pending_extraction", result["reason"])
        self.assertIsNone(result["result"])
        self.assertEqual(result["rule_version"], "us-2025-states-v0.1")
        self.assertEqual(result["citations"][0]["source_id"], "ca_2025_540_tax_rate_schedules")

    def test_state_income_tax_blocks_source_pending_states(self):
        result = state_income_tax("TX", 100_000)

        self.assertEqual(result["status"], "not_covered")
        self.assertIn("source_pending", result["reason"])
        self.assertIsNone(result["result"])

    def test_state_income_tax_blocks_unknown_states(self):
        result = state_income_tax("ZZ", 100_000)

        self.assertEqual(result["status"], "not_covered")
        self.assertIn("not present", result["reason"])

    def test_rule_loader_returns_isolated_copies(self):
        rules = load_state_rules()
        rules["states"]["FL"]["flat_rate"] = 0.99

        result = state_income_tax("FL", 100_000)

        self.assertEqual(result["result"]["tax"], 0.00)
        self.assertEqual(result["result"]["rate"], 0.0)

    def test_self_employment_tax_negative_profit_clamps_to_zero(self):
        result = self_employment_tax(-5_000, "single")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["net_earnings_from_self_employment"], 0.00)
        self.assertEqual(result["result"]["total_se_related_tax"], 0.00)

    def test_self_employment_tax_uses_mfj_additional_medicare_threshold(self):
        result = self_employment_tax(250_000, "mfj")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["additional_medicare_tax"], 0.00)
        self.assertEqual(result["result"]["total_se_related_tax"], 28_531.78)

    def test_nexus_ca_equal_threshold_uses_strict_greater_than(self):
        result = nexus_estimate("CA", 500_000)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["exceeded"])
        self.assertTrue(result["result"]["approaching"])
        self.assertEqual(result["result"]["status_label"], "approaching")

    def test_nexus_tx_equal_threshold_uses_greater_than_or_equal(self):
        result = nexus_estimate("TX", 500_000)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["exceeded"])
        self.assertFalse(result["result"]["approaching"])
        self.assertEqual(result["result"]["status_label"], "triggered")

    def test_nexus_ny_equal_transaction_threshold_uses_strict_greater_than(self):
        result = nexus_estimate("NY", 600_000, 100)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["exceeded"])
        self.assertTrue(result["result"]["approaching"])
        self.assertEqual(result["result"]["status_label"], "approaching")

    def test_nexus_ny_missing_transaction_count_does_not_trigger(self):
        result = nexus_estimate("NY", 600_000)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["exceeded"])
        self.assertTrue(result["result"]["approaching"])
        self.assertIn("transaction_count input was not provided", result["assumptions"][1])

    def test_crypto_partial_lot_is_consumed_across_multiple_disposals(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "ETH", "date": "2023-01-01", "quantity": 2, "cost_basis": 2000}],
            disposals=[
                {"asset": "ETH", "date": "2025-01-02", "quantity": 0.5, "proceeds": 1000},
                {"asset": "ETH", "date": "2025-01-03", "quantity": 0.75, "proceeds": 1500},
            ],
            method="FIFO",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["result"]["lots_matched"]), 2)
        self.assertEqual(result["result"]["realized"]["long_term_gain"], 1250.00)
        self.assertEqual(result["result"]["realized"]["short_term_gain"], 0.00)

    def test_crypto_holding_period_one_year_plus_one_day_is_long_term(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2024-02-29", "quantity": 1, "cost_basis": 10000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 12000}],
            method="FIFO",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["lots_matched"][0]["term"], "long")

    def test_crypto_zero_quantity_is_invalid_input(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2024-01-01", "quantity": 0, "cost_basis": 10000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 12000}],
            method="FIFO",
        )

        self.assertEqual(result["status"], "invalid_input")
        self.assertIn("quantity", result["reason"])


if __name__ == "__main__":
    unittest.main()
