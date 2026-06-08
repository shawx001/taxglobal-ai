import unittest

from engine import (
    bracket_tax,
    crypto_gain_estimate,
    federal_income_tax,
    feie_estimate,
    fica_tax,
    income_tax_summary,
    nexus_estimate,
    qbi_deduction,
    rsu_tax_estimate,
    self_employment_tax,
    state_income_tax,
)
from engine.rules_loader import load_state_rules
from engine.state import state_capital_gains_excise
from engine.tax_engine import _state_taxable_base

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

    def test_tax_engine_compat_shim_exports_legacy_names(self):
        from engine.tax_engine import (  # noqa: PLC0415
            ROUND_HALF_UP,
            Any,
            Decimal,
            _state_taxable_base,
            date,
            load_capital_gains_rules,
            load_federal_rules,
            load_feie_rules,
            load_fica_rules,
            load_nexus_rules,
            load_qbi_rules,
            load_state_rules,
        )

        self.assertTrue(Any)
        self.assertTrue(Decimal)
        self.assertTrue(ROUND_HALF_UP)
        self.assertTrue(date)
        self.assertTrue(_state_taxable_base)
        self.assertTrue(load_capital_gains_rules)
        self.assertTrue(load_federal_rules)
        self.assertTrue(load_feie_rules)
        self.assertTrue(load_fica_rules)
        self.assertTrue(load_nexus_rules)
        self.assertTrue(load_qbi_rules)
        self.assertTrue(load_state_rules)

    def test_federal_income_tax_single_uses_2025_rules(self):
        result = federal_income_tax(120_000, "single", tax_year=2025)

        self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["reason"])
        self.assertEqual(result["result"]["taxable_income"], 105_000.00)
        self.assertEqual(result["result"]["tax"], 18_047.00)
        self.assertEqual(result["rule_version"], "us-2025-federal-v0.1")
        self.assertEqual(result["citations"][0]["source_id"], "irs_rp_2024_40")

    def test_federal_income_tax_accepts_prototype_filing_alias_without_using_prototype_rules(self):
        result = federal_income_tax(120_000, "mfj", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["input"]["filing_status"], "married_filing_jointly")
        self.assertEqual(result["result"]["taxable_income"], 90_000.00)
        self.assertEqual(result["result"]["tax"], 10_323.00)

    def test_fica_caps_social_security_and_applies_additional_medicare(self):
        result = fica_tax(250_000, "single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertIn("annual taxpayer filing-status thresholds", result["assumptions"][1])
        self.assertEqual(result["result"]["social_security_tax"], 10_918.20)
        self.assertEqual(result["result"]["medicare_tax"], 3_625.00)
        self.assertEqual(result["result"]["additional_medicare_tax"], 450.00)
        self.assertEqual(result["result"]["total"], 14_993.20)

    def test_fica_uses_mfj_additional_medicare_threshold(self):
        result = fica_tax(250_000, "married_filing_jointly", tax_year=2025)

        self.assertEqual(result["result"]["additional_medicare_tax"], 0.00)

    def test_feie_estimate_physical_presence_passes_at_330_days(self):
        result = feie_estimate(140_000, 330, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["qualifies_physical_presence_test"])
        self.assertEqual(result["result"]["excluded_income"], 130_000.00)
        self.assertEqual(result["result"]["remaining_income"], 10_000.00)

    def test_feie_estimate_physical_presence_fails_below_330_days(self):
        result = feie_estimate(140_000, 329, tax_year=2025)

        self.assertFalse(result["result"]["qualifies_physical_presence_test"])
        self.assertEqual(result["result"]["excluded_income"], 0.00)
        self.assertEqual(result["result"]["remaining_income"], 140_000.00)

    def test_state_income_tax_effective_zero_tax_state(self):
        result = state_income_tax("FL", 100_000, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["tax"], 0.00)
        self.assertEqual(result["citations"][0]["source_id"], "fl_personal_income_tax_faq")

    def test_state_income_tax_effective_flat_tax_state(self):
        result = state_income_tax("IL", 100_000, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["tax"], 4_950.00)
        self.assertEqual(result["result"]["rate"], 0.0495)

    def test_state_income_tax_effective_progressive_state(self):
        result = state_income_tax("CA", 200_000, "single", tax_year=2025)

        self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["tax"], 15_038.64)
        self.assertEqual(result["result"]["income_tax_type"], "progressive")
        self.assertEqual(result["rule_version"], "us-2025-states-v0.1")
        self.assertEqual(result["citations"][0]["source_id"], "ca_2025_540_tax_rate_schedules")
        self.assertIn("Mental Health Services Tax", "\n".join(result["assumptions"]))

    def test_state_income_tax_progressive_zero_income(self):
        result = state_income_tax("CA", 0, "single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["tax"], 0.00)

    def test_state_income_tax_progressive_defaults_to_single(self):
        explicit = state_income_tax("CA", 200_000, "single", tax_year=2025)
        default = state_income_tax("CA", 200_000, tax_year=2025)

        self.assertEqual(default["status"], "ok")
        self.assertEqual(default["result"]["tax"], explicit["result"]["tax"])
        self.assertEqual(default["input"]["filing_status"], "single")

    def test_state_income_tax_blocks_source_pending_states(self):
        result = state_income_tax("TX", 100_000, tax_year=2025)

        self.assertEqual(result["status"], "not_covered")
        self.assertIn("source_pending", result["reason"])
        self.assertIsNone(result["result"])

    def test_state_income_tax_blocks_unknown_states(self):
        result = state_income_tax("ZZ", 100_000, tax_year=2025)

        self.assertEqual(result["status"], "not_covered")
        self.assertIn("not present", result["reason"])

    def test_rule_loader_returns_isolated_copies(self):
        rules = load_state_rules(2025)
        rules["states"]["FL"]["flat_rate"] = 0.99

        result = state_income_tax("FL", 100_000, tax_year=2025)

        self.assertEqual(result["result"]["tax"], 0.00)
        self.assertEqual(result["result"]["rate"], 0.0)

    def test_self_employment_tax_negative_profit_clamps_to_zero(self):
        result = self_employment_tax(-5_000, "single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["net_earnings_from_self_employment"], 0.00)
        self.assertEqual(result["result"]["total_se_related_tax"], 0.00)

    def test_self_employment_tax_uses_mfj_additional_medicare_threshold(self):
        result = self_employment_tax(250_000, "mfj", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["additional_medicare_tax"], 0.00)
        self.assertEqual(result["result"]["total_se_related_tax"], 28_531.78)

    def test_qbi_deduction_zero_qbi_returns_zero(self):
        result = qbi_deduction(0, 100_000, tax_year=2025)

        self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["deduction"], 0.00)
        self.assertEqual(result["result"]["qbi_component"], 0.00)

    def test_qbi_deduction_negative_qbi_clamps_to_zero(self):
        result = qbi_deduction(-5_000, 100_000, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["input"]["qbi"], 0.00)
        self.assertEqual(result["result"]["deduction"], 0.00)

    def test_qbi_deduction_threshold_equal_uses_below_threshold(self):
        result = qbi_deduction(100_000, 197_300, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["deduction"], 20_000.00)
        self.assertEqual(result["result"]["applied_limit"], "below_threshold")
        self.assertEqual(result["result"]["threshold_band"], "below_threshold")

    def test_qbi_deduction_default_2026_uses_expanded_phase_in_window(self):
        result = qbi_deduction(100_000, 225_000, w2_wages=20_000)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["input"]["tax_year"], 2026)
        self.assertEqual(result["rule_version"], "us-2026-qbi-v0.1")
        self.assertEqual(result["result"]["deduction"], 16_900.00)
        self.assertEqual(result["result"]["applied_limit"], "phase_in")
        self.assertEqual(result["result"]["threshold_band"], "phase_in")

    def test_income_tax_summary_default_2026_w2_anchor(self):
        result = income_tax_summary(w2_wages=200_000, filing_status="single")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["input"]["tax_year"], 2026)
        self.assertEqual(result["result"]["federal_income_tax"], 36_734.00)
        self.assertEqual(result["result"]["total_payroll_tax"], 14_339.00)
        self.assertEqual(result["result"]["total_tax"], 51_073.00)

    def test_income_tax_summary_low_income_still_owes_se_tax(self):
        result = income_tax_summary(10_000, filing_status="single", state_code="FL", tax_year=2025)

        self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["self_employment_tax"], 1_412.96)
        self.assertEqual(result["result"]["federal_income_tax"], 0.00)
        self.assertEqual(result["result"]["taxable_income"], 0.00)
        self.assertEqual(result["result"]["total_tax"], 1_412.96)

    def test_income_tax_summary_unknown_state_is_not_covered_inside_summary(self):
        result = income_tax_summary(100_000, filing_status="single", state_code="ZZ", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state_income_tax"]["status"], "not_covered")
        self.assertTrue(result["result"]["state_income_tax"]["not_covered"])
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 0.00)
        self.assertEqual(result["result"]["total_tax"], 22_760.15)
        self.assertIn(
            "total tax includes federal income tax and total payroll tax", "\n".join(result["assumptions"])
        )

    def test_state_capital_gains_excise_uses_stored_thresholds(self):
        wa = load_state_rules(2026)["states"]["WA"]

        result = state_capital_gains_excise(wa, net_long_term_gain=1_500_000)

        self.assertIsNotNone(result)
        self.assertEqual(result["tax"], 91_978)
        self.assertEqual(result["taxable_capital_gains"], 1_222_000)

    def test_income_tax_summary_wa_long_term_gain_adds_capital_gains_excise(self):
        result = income_tax_summary(long_term_capital_gain=500_000, state_code="WA")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 0.00)
        self.assertEqual(result["result"]["state_capital_gains_excise"], 15_540.00)
        self.assertEqual(result["result"]["total_tax"], 92_107.50)
        breakdown = {item["label"]: item["amount"] for item in result["breakdown"]}
        self.assertEqual(breakdown["state_income_tax"], 0.00)
        self.assertEqual(breakdown["state_capital_gains_excise"], 15_540.00)
        self.assertIn("net long-term capital gains", "\n".join(result["assumptions"]))

    def test_income_tax_summary_wa_short_term_gain_has_zero_capital_gains_excise(self):
        result = income_tax_summary(short_term_capital_gain=300_000, state_code="WA")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state_capital_gains_excise"], 0.00)

    def test_income_tax_summary_non_excise_state_shape_stays_unchanged(self):
        result = income_tax_summary(100_000, filing_status="single", state_code="FL", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("state_capital_gains_excise", result["result"])
        self.assertEqual(result["result"]["total_tax"], 22_760.15)

    def test_income_tax_summary_co_adds_back_qbi_to_state_base(self):
        result = income_tax_summary(100_000, filing_status="single", state_code="CO", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["taxable_income"], 62_348.18)
        self.assertEqual(result["result"]["qbi_deduction"], 15_587.04)
        self.assertEqual(result["result"]["state_taxable_base"], 77_935.22)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 3_429.15)
        self.assertIn("Colorado QBI addback", "\n".join(result["assumptions"]))

    def test_income_tax_summary_invalid_filing_status(self):
        result = income_tax_summary(100_000, filing_status="unsupported", state_code="FL", tax_year=2025)

        self.assertEqual(result["status"], "invalid_input")
        self.assertIn("Unsupported filing_status", result["reason"])

    def test_income_tax_summary_w2_wages_share_social_security_base_with_se_income(self):
        result = income_tax_summary(60_000, w2_wages=250_000, filing_status="single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["w2_fica_tax"], 14_543.20)
        self.assertEqual(result["result"]["self_employment_tax"], 1_606.89)
        self.assertEqual(result["result"]["total_payroll_tax"], 17_098.78)

    def test_income_tax_summary_combines_w2_and_se_for_additional_medicare(self):
        result = income_tax_summary(60_000, w2_wages=250_000, filing_status="single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["additional_medicare_tax"], 948.69)

    def test_income_tax_summary_high_income_qbi_phases_out_without_qbi_wages(self):
        result = income_tax_summary(60_000, w2_wages=250_000, filing_status="single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["qbi_deduction"], 0.00)

    def test_income_tax_summary_w2_default_zero_reproduces_self_employment_only(self):
        result = income_tax_summary(100_000, filing_status="single", state_code="FL", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["w2_fica_tax"], 0.00)
        self.assertEqual(result["result"]["total_payroll_tax"], 14_129.55)
        self.assertEqual(result["result"]["self_employment_tax"], 14_129.55)
        self.assertEqual(result["result"]["adjusted_gross_income"], 92_935.22)
        self.assertEqual(result["result"]["qbi_deduction"], 15_587.04)
        self.assertEqual(result["result"]["taxable_income"], 62_348.18)
        self.assertEqual(result["result"]["federal_income_tax"], 8_630.60)
        self.assertEqual(result["result"]["total_tax"], 22_760.15)

    def test_income_tax_summary_short_term_gain_is_ordinary_but_not_payroll_income(self):
        result = income_tax_summary(
            w2_wages=100_000, short_term_capital_gain=10_000, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["ordinary_taxable_income"], 95_000.00)
        self.assertEqual(result["result"]["federal_income_tax"], 15_814.00)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 0.00)
        self.assertEqual(result["result"]["total_payroll_tax"], 7_650.00)

    def test_income_tax_summary_niit_can_apply_to_full_net_investment_income(self):
        result = income_tax_summary(
            w2_wages=200_000, long_term_capital_gain=50_000, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["net_investment_income_tax"], 1_900.00)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 7_500.00)
        self.assertEqual(result["result"]["total_tax"], 60_465.20)

    def test_income_tax_summary_niit_is_capped_by_magi_excess(self):
        result = income_tax_summary(
            w2_wages=150_000,
            net_self_employment_profit=50_000,
            long_term_capital_gain=40_000,
            filing_status="single",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["qbi_deduction"], 4_692.55)
        self.assertEqual(result["result"]["net_investment_income_tax"], 1_433.07)
        self.assertEqual(result["result"]["total_tax"], 59_055.28)

    def test_income_tax_summary_long_term_gain_can_land_in_zero_percent_band(self):
        result = income_tax_summary(long_term_capital_gain=40_000, filing_status="single", tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["ordinary_taxable_income"], 0.00)
        self.assertEqual(result["result"]["taxable_income"], 25_000.00)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 0.00)
        self.assertEqual(result["result"]["total_tax"], 0.00)

    def test_income_tax_summary_capital_gains_default_zero_reproduces_block1(self):
        result = income_tax_summary(
            w2_wages=150_000, net_self_employment_profit=50_000, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["ordinary_taxable_income"], 173_169.81)
        self.assertEqual(result["result"]["taxable_income"], 173_169.81)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 0.00)
        self.assertEqual(result["result"]["net_investment_income_tax"], 0.00)
        self.assertEqual(result["result"]["total_tax"], 50_458.23)

    def test_income_tax_summary_feie_applies_rate_stacking(self):
        result = income_tax_summary(
            foreign_earned_income=200_000, days_abroad=330, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["feie_excluded_income"], 130_000.00)
        self.assertTrue(result["result"]["foreign_tax_rate_stacking_applied"])
        self.assertEqual(result["result"]["ordinary_taxable_income"], 55_000.00)
        self.assertEqual(result["result"]["federal_income_tax"], 13_200.00)
        self.assertEqual(result["result"]["total_tax"], 13_200.00)

    def test_income_tax_summary_feie_below_330_days_does_not_exclude_income(self):
        result = income_tax_summary(
            foreign_earned_income=100_000, days_abroad=329, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["feie_excluded_income"], 0.00)
        self.assertFalse(result["result"]["foreign_tax_rate_stacking_applied"])
        self.assertEqual(result["result"]["adjusted_gross_income"], 100_000.00)
        self.assertEqual(result["result"]["federal_income_tax"], 13_614.00)

    def test_income_tax_summary_feie_under_limit_can_exclude_full_foreign_income(self):
        result = income_tax_summary(
            foreign_earned_income=50_000, days_abroad=330, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["feie_excluded_income"], 50_000.00)
        self.assertTrue(result["result"]["foreign_tax_rate_stacking_applied"])
        self.assertEqual(result["result"]["adjusted_gross_income"], 0.00)
        self.assertEqual(result["result"]["total_tax"], 0.00)

    def test_income_tax_summary_feie_addback_can_trigger_niit(self):
        result = income_tax_summary(
            foreign_earned_income=200_000,
            days_abroad=330,
            w2_wages=50_000,
            long_term_capital_gain=30_000,
            filing_status="single",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["net_investment_income_tax"], 1_140.00)
        self.assertEqual(result["result"]["total_tax"], 37_681.00)

    def test_income_tax_summary_modified_agi_overrides_feie_niit_addback(self):
        result = income_tax_summary(
            foreign_earned_income=200_000,
            days_abroad=330,
            w2_wages=50_000,
            long_term_capital_gain=30_000,
            modified_agi=150_000,
            filing_status="single",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["net_investment_income_tax"], 0.00)

    def test_income_tax_summary_feie_keeps_qbi_net_capital_gain_guard(self):
        result = income_tax_summary(
            net_self_employment_profit=60_000,
            long_term_capital_gain=40_000,
            foreign_earned_income=100_000,
            days_abroad=330,
            filing_status="single",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["qbi_deduction"], 8_152.23)
        self.assertEqual(result["result"]["federal_income_tax"], 7_759.14)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 6_000.00)
        self.assertEqual(result["result"]["total_tax"], 22_236.87)

    def test_income_tax_summary_foreign_zero_reproduces_block2(self):
        result = income_tax_summary(
            foreign_earned_income=0,
            w2_wages=200_000,
            long_term_capital_gain=50_000,
            filing_status="single",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["feie_excluded_income"], 0.00)
        self.assertFalse(result["result"]["foreign_tax_rate_stacking_applied"])
        self.assertEqual(result["result"]["federal_income_tax"], 37_247.00)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 7_500.00)
        self.assertEqual(result["result"]["net_investment_income_tax"], 1_900.00)
        self.assertEqual(result["result"]["total_tax"], 60_465.20)

    def test_income_tax_summary_rejects_fractional_days_abroad(self):
        # Whole-number floats are accepted as the integer day count.
        accepted = income_tax_summary(
            foreign_earned_income=100_000, days_abroad=330.0, filing_status="single", tax_year=2025
        )
        self.assertEqual(accepted["status"], "ok")
        self.assertTrue(accepted["result"]["foreign_tax_rate_stacking_applied"])

        # Fractional day counts are rejected, not silently floored (would change FEIE qualification).
        rejected = income_tax_summary(
            foreign_earned_income=100_000, days_abroad=329.9, filing_status="single", tax_year=2025
        )
        self.assertEqual(rejected["status"], "invalid_input")
        self.assertIn("days_abroad", rejected["reason"])

    def test_income_tax_summary_rejects_out_of_range_days_abroad(self):
        result = income_tax_summary(
            foreign_earned_income=100_000, days_abroad=400, filing_status="single", tax_year=2025
        )

        self.assertEqual(result["status"], "invalid_input")
        self.assertIn("days_abroad", result["reason"])

    def test_state_taxable_base_blocks_unmodeled_agi_qbi_allowed_combo(self):
        state_block = {
            "tax_base": {
                "start_from": "federal_agi",
                "allows_qbi": True,
                "standard_deduction": {"single": 1_000},
            }
        }

        with self.assertRaisesRegex(ValueError, "allows_qbi=true is not modeled"):
            _state_taxable_base(
                state_block,
                gross_income=100_000,
                federal_agi=100_000,
                federal_taxable_income=80_000,
                federal_qbi_deduction=10_000,
                filing="single",
            )

    def test_state_taxable_base_gross_income_exemption_per_person(self):
        nj = load_state_rules(2026)["states"]["NJ"]

        self.assertEqual(
            _state_taxable_base(
                nj,
                gross_income=150_000,
                federal_agi=140_000,
                federal_taxable_income=120_000,
                federal_qbi_deduction=0,
                filing="single",
            ),
            149_000,
        )
        self.assertEqual(
            _state_taxable_base(
                nj,
                gross_income=150_000,
                federal_agi=140_000,
                federal_taxable_income=120_000,
                federal_qbi_deduction=0,
                filing="married_filing_jointly",
            ),
            148_000,
        )
        self.assertEqual(
            _state_taxable_base(
                nj,
                gross_income=150_000,
                federal_agi=140_000,
                federal_taxable_income=120_000,
                federal_qbi_deduction=0,
                filing="qualifying_surviving_spouse",
            ),
            148_000,
        )
        self.assertEqual(
            _state_taxable_base(
                nj,
                gross_income=10_000,
                federal_agi=10_000,
                federal_taxable_income=0,
                federal_qbi_deduction=0,
                filing="single",
            ),
            0,
        )
        self.assertEqual(
            _state_taxable_base(
                nj,
                gross_income=20_000,
                federal_agi=20_000,
                federal_taxable_income=0,
                federal_qbi_deduction=0,
                filing="married_filing_jointly",
            ),
            0,
        )

    def test_income_tax_summary_nj_w2_uses_gross_income_tax_base(self):
        result = income_tax_summary(w2_wages=150_000, filing_status="single", state_code="NJ")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["gross_income"], 150_000.00)
        self.assertEqual(result["result"]["state_taxable_base"], 149_000.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 7_365.05)
        self.assertEqual(result["result"]["total_tax"], 43_574.05)
        self.assertIn("Gross-income state taxable bases", "\n".join(result["assumptions"]))

    def test_income_tax_summary_pa_w2_uses_gross_income_flat_tax_base(self):
        result = income_tax_summary(w2_wages=150_000, filing_status="single", state_code="PA")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["gross_income"], 150_000.00)
        self.assertEqual(result["result"]["state_taxable_base"], 150_000.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 4_605.00)
        self.assertEqual(result["result"]["total_tax"], 40_814.00)

    def test_income_tax_summary_nj_treats_long_term_capital_gain_as_ordinary_state_income(self):
        result = income_tax_summary(w2_wages=100_000, long_term_capital_gain=50_000, state_code="NJ")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["gross_income"], 150_000.00)
        self.assertEqual(result["result"]["state_taxable_base"], 149_000.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 7_365.05)

    def test_income_tax_summary_nj_low_income_threshold_pays_no_state_income_tax(self):
        result = income_tax_summary(w2_wages=10_000, filing_status="single", state_code="NJ")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["gross_income"], 10_000.00)
        self.assertEqual(result["result"]["state_taxable_base"], 0.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 0.00)

    def test_income_tax_summary_gross_income_state_includes_feie_excluded_income(self):
        result = income_tax_summary(
            foreign_earned_income=50_000,
            days_abroad=330,
            filing_status="single",
            state_code="NJ",
            tax_year=2026,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["adjusted_gross_income"], 0.00)
        self.assertEqual(result["result"]["feie_excluded_income"], 50_000.00)
        self.assertEqual(result["result"]["gross_income"], 50_000.00)
        self.assertEqual(result["result"]["state_taxable_base"], 49_000.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 1_214.75)

    def test_state_taxable_base_federal_tax_subtraction_phaseout(self):
        oregon = load_state_rules(2026)["states"]["OR"]

        self.assertEqual(
            _state_taxable_base(
                oregon,
                gross_income=100_000,
                federal_agi=100_000,
                federal_taxable_income=83_900,
                federal_qbi_deduction=0,
                filing="single",
                federal_income_tax=13_170,
            ),
            88_665,
        )
        self.assertEqual(
            _state_taxable_base(
                oregon,
                gross_income=129_000,
                federal_agi=129_000,
                federal_taxable_income=112_900,
                federal_qbi_deduction=0,
                filing="single",
                federal_income_tax=19_694,
            ),
            119_365,
        )
        self.assertEqual(
            _state_taxable_base(
                oregon,
                gross_income=145_000,
                federal_agi=145_000,
                federal_taxable_income=128_900,
                federal_qbi_deduction=0,
                filing="single",
                federal_income_tax=23_534,
            ),
            142_165,
        )
        self.assertEqual(
            _state_taxable_base(
                oregon,
                gross_income=100_000,
                federal_agi=100_000,
                federal_taxable_income=83_900,
                federal_qbi_deduction=0,
                filing="married_filing_separately",
                federal_income_tax=13_170,
            ),
            92_915,
        )

    def test_income_tax_summary_or_w2_uses_federal_tax_subtraction(self):
        result = income_tax_summary(w2_wages=100_000, filing_status="single", state_code="OR")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["federal_income_tax"], 13_170.00)
        self.assertEqual(result["result"]["long_term_capital_gains_tax"], 0.00)
        self.assertEqual(result["result"]["federal_income_tax_liability"], 13_170.00)
        self.assertNotIn(
            "federal_income_tax_liability",
            {line["label"] for line in result["breakdown"]},
        )
        self.assertEqual(result["result"]["state_taxable_base"], 88_665.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 7_449.19)
        self.assertEqual(result["result"]["total_tax"], 28_269.19)
        self.assertIn("State federal-tax subtraction", "\n".join(result["assumptions"]))

    def test_income_tax_summary_non_subtraction_state_does_not_emit_federal_tax_liability(self):
        result = income_tax_summary(w2_wages=100_000, filing_status="single", state_code="CA")

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("federal_income_tax_liability", result["result"])

    def test_income_tax_summary_or_phaseout_band(self):
        result = income_tax_summary(w2_wages=129_000, filing_status="single", state_code="OR")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["federal_income_tax_liability"], 19_694.00)
        self.assertEqual(result["result"]["state_taxable_base"], 119_365.00)
        self.assertEqual(result["result"]["state_income_tax"]["tax"], 10_135.44)
        self.assertEqual(result["result"]["total_tax"], 39_697.94)

    def test_nexus_ca_equal_threshold_uses_strict_greater_than(self):
        result = nexus_estimate("CA", 500_000, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["exceeded"])
        self.assertTrue(result["result"]["approaching"])
        self.assertEqual(result["result"]["status_label"], "approaching")

    def test_nexus_tx_equal_threshold_uses_greater_than_or_equal(self):
        result = nexus_estimate("TX", 500_000, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["exceeded"])
        self.assertFalse(result["result"]["approaching"])
        self.assertEqual(result["result"]["status_label"], "triggered")

    def test_nexus_ny_equal_transaction_threshold_uses_strict_greater_than(self):
        result = nexus_estimate("NY", 600_000, 100, tax_year=2025)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["exceeded"])
        self.assertTrue(result["result"]["approaching"])
        self.assertEqual(result["result"]["status_label"], "approaching")

    def test_nexus_ny_missing_transaction_count_does_not_trigger(self):
        result = nexus_estimate("NY", 600_000, tax_year=2025)

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
            tax_year=2025,
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
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["lots_matched"][0]["term"], "long")

    def test_crypto_zero_quantity_is_invalid_input(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2024-01-01", "quantity": 0, "cost_basis": 10000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 12000}],
            method="FIFO",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "invalid_input")
        self.assertIn("quantity", result["reason"])

    def test_crypto_state_code_none_preserves_federal_only_shape(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2023-01-10", "quantity": 1, "cost_basis": 20000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 50000}],
            method="FIFO",
            other_taxable_income=100_000,
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("state", result["result"])
        self.assertNotIn("total_tax_including_state", result["result"])

    def test_crypto_state_tax_flat_state_equals_gain_times_rate(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2023-01-10", "quantity": 1, "cost_basis": 20000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 55000}],
            method="FIFO",
            other_taxable_income=100_000,
            state_code="GA",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state"]["tax"], 1816.50)
        self.assertEqual(result["result"]["state"]["type"], "ordinary_income")

    def test_crypto_state_tax_unknown_state_is_not_covered_inside_result(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2023-01-10", "quantity": 1, "cost_basis": 20000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 55000}],
            method="FIFO",
            other_taxable_income=100_000,
            state_code="ZZ",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state"]["status"], "not_covered")
        self.assertEqual(result["result"]["state"]["tax"], 0.00)

    def test_crypto_state_tax_federal_tax_subtraction_state_is_not_covered(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2023-01-10", "quantity": 1, "cost_basis": 20000}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 55000}],
            method="FIFO",
            other_taxable_income=100_000,
            state_code="OR",
            tax_year=2026,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state"]["status"], "not_covered")
        self.assertEqual(result["result"]["state"]["tax"], 0.00)
        self.assertIn("federal income tax liability", result["result"]["state"]["reason"])

    def test_crypto_wa_short_term_gain_has_zero_excise(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2024-06-01", "quantity": 1, "cost_basis": 0}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 500000}],
            method="FIFO",
            state_code="WA",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["realized"]["short_term_gain"], 500000.00)
        self.assertEqual(result["result"]["state"]["tax"], 0.00)

    def test_crypto_wa_excise_applies_tier_above_one_million(self):
        result = crypto_gain_estimate(
            lots=[{"asset": "BTC", "date": "2023-01-10", "quantity": 1, "cost_basis": 0}],
            disposals=[{"asset": "BTC", "date": "2025-03-01", "quantity": 1, "proceeds": 1500000}],
            method="FIFO",
            state_code="WA",
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["state"]["tax"], 91978.00)
        self.assertEqual(result["result"]["state"]["taxable_washington_capital_gain"], 1222000.00)

    def test_rsu_sale_exactly_one_year_after_vest_is_short_term(self):
        result = rsu_tax_estimate(
            shares_vested=100,
            fair_market_value_per_share=50,
            vest_date="2024-03-01",
            other_taxable_income=100_000,
            sale_scenario={"sale_date": "2025-03-01", "sale_price_per_share": 80},
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["hold_vs_sell"]["term"], "short")

    def test_rsu_sale_below_fmv_has_zero_capital_gains_tax_and_loss_assumption(self):
        result = rsu_tax_estimate(
            shares_vested=100,
            fair_market_value_per_share=50,
            vest_date="2024-03-01",
            other_taxable_income=100_000,
            sale_scenario={"sale_date": "2025-06-01", "sale_price_per_share": 40},
            tax_year=2025,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["hold_vs_sell"]["capital_gain"], -1000.00)
        self.assertEqual(result["result"]["hold_vs_sell"]["capital_gains_tax"], 0.00)
        self.assertIn("$3,000", "\n".join(result["assumptions"]))


if __name__ == "__main__":
    unittest.main()
