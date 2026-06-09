from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.main import create_app


class TestTipContext(unittest.TestCase):
    def test_context_from_params_basic(self) -> None:
        from backend.knowledge.tips import context_from_params

        ctx = context_from_params(state="ca", filing_status="single", income_types="w2,self_employment")

        self.assertEqual(ctx.state, "CA")
        self.assertEqual(ctx.filing_status, "single")
        self.assertEqual(ctx.income_types, ("w2", "self_employment"))

    def test_context_from_params_crypto_and_rsu_flags(self) -> None:
        from backend.knowledge.tips import context_from_params

        ctx = context_from_params(income_types="crypto,rsu")

        self.assertTrue(ctx.has_crypto)
        self.assertTrue(ctx.has_rsu)

    def test_context_from_params_empty(self) -> None:
        from backend.knowledge.tips import context_from_params

        ctx = context_from_params()

        self.assertEqual(ctx.state, "")
        self.assertEqual(ctx.income_types, ())

    def test_context_from_profile_data(self) -> None:
        from backend.knowledge.tips import context_from_profile

        ctx = context_from_profile(
            {
                "filing_status": "married_filing_jointly",
                "state": "NY",
                "gross_income": 200000,
                "w2_wages": 150000,
                "self_employment_income": 50000,
                "foreign_earned_income": 10000,
                "crypto_transactions": [{"asset": "BTC"}],
            }
        )

        self.assertEqual(ctx.state, "NY")
        self.assertEqual(ctx.filing_status, "married_filing_jointly")
        self.assertIn("w2", ctx.income_types)
        self.assertIn("self_employment", ctx.income_types)
        self.assertIn("foreign", ctx.income_types)
        self.assertTrue(ctx.has_crypto)
        self.assertEqual(ctx.gross_income, 200000)
        self.assertEqual(ctx.w2_wages, 150000)
        self.assertEqual(ctx.self_employment_income, 50000)

    def test_context_from_profile_non_finite_amounts_are_ignored(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        ctx = context_from_profile({"taxable_income": "NaN", "w2_wages": "Infinity", "investment_income": 1000})
        tips = get_tips(ctx)
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertEqual(ctx.taxable_income, 0)
        self.assertEqual(ctx.w2_wages, 0)
        self.assertNotIn("us_2026_niit", ids)


class TestTipMatcher(unittest.TestCase):
    def test_self_employment_gets_estimated_tax_tip(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(income_types=("self_employment",)))
        topics = [tip["topic"] for tip in tips]

        self.assertTrue(any(topic in {"estimated_tax", "self_employment_tax"} for topic in topics))

    def test_self_employment_counts_as_earned_income_for_tips(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(income_types=("self_employment",)))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertIn("us_2026_eitc_overview", ids)

    def test_net_self_employment_income_threshold_tip_matches_amount(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"self_employment_income": 1000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertIn("us_2026_se_tax_threshold", ids)

    def test_foreign_income_gets_feie_tip(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(income_types=("foreign",)))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertTrue(any("feie" in knowledge_id for knowledge_id in ids))

    def test_ma_high_income_gets_surtax_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"state": "MA", "taxable_income": 1200000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertTrue(any("surtax" in knowledge_id for knowledge_id in ids))

    def test_ma_high_income_below_surtax_threshold_does_not_get_surtax_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"state": "MA", "gross_income": 200000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertFalse(any("surtax" in knowledge_id for knowledge_id in ids))

    def test_ma_gross_income_without_taxable_income_does_not_get_surtax_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"state": "MA", "gross_income": 1200000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertFalse(any("surtax" in knowledge_id for knowledge_id in ids))

    def test_mfj_investment_income_below_high_income_threshold_does_not_get_niit_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(
            context_from_profile(
                {
                    "filing_status": "married_filing_jointly",
                    "gross_income": 200000,
                    "investment_income": 1000,
                }
            )
        )
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertNotIn("us_2026_niit", ids)

    def test_explicit_high_income_with_investment_gets_niit_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"income_types": ["high_income"], "investment_income": 1000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertIn("us_2026_niit", ids)

    def test_string_false_high_income_does_not_get_niit_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"high_income": "false", "investment_income": 1000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertNotIn("us_2026_niit", ids)

    def test_mfj_wages_below_additional_medicare_threshold_do_not_get_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"filing_status": "married_filing_jointly", "w2_wages": 200000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertNotIn("us_2026_additional_medicare_tax", ids)

    def test_mfj_wages_above_additional_medicare_threshold_get_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"filing_status": "married_filing_jointly", "w2_wages": 300000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertIn("us_2026_additional_medicare_tax", ids)

    def test_gross_investment_income_does_not_get_additional_medicare_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"gross_income": 300000, "investment_income": 300000}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertNotIn("us_2026_additional_medicare_tax", ids)

    def test_explicit_boolean_trigger_evidence_can_match_amt_tip(self) -> None:
        from backend.knowledge.tips import context_from_profile, get_tips

        tips = get_tips(context_from_profile({"income_types": ["high_income", "preference_items"]}))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertIn("us_2026_amt_overview", ids)

    def test_wa_capital_gain_gets_excise_tip(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(state="WA", income_types=("capital_gain",)))
        ids = [tip["knowledge_id"].lower() for tip in tips]

        self.assertTrue(any("wa" in knowledge_id and "capital" in knowledge_id for knowledge_id in ids))

    def test_wa_state_only_does_not_get_excise_tip(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(state="WA"))
        ids = [tip["knowledge_id"].lower() for tip in tips]

        self.assertFalse(any("wa" in knowledge_id and "capital" in knowledge_id for knowledge_id in ids))

    def test_crypto_only_does_not_get_wa_capital_gain_excise_tip(self) -> None:
        from backend.knowledge.tips import context_from_params, get_tips

        tips = get_tips(context_from_params(state="WA", income_types="crypto"))
        ids = [tip["knowledge_id"].lower() for tip in tips]

        self.assertFalse(any("wa" in knowledge_id and "capital" in knowledge_id for knowledge_id in ids))

    def test_ny_city_tax_note_reachable(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(state="NY", income_types=("w2",)))
        ids = [tip["knowledge_id"] for tip in tips]

        self.assertIn("ny_2026_city_tax_note", ids)

    def test_empty_context_gets_generic_tips(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext())

        self.assertGreater(len(tips), 0)
        ids = {tip["knowledge_id"] for tip in tips}
        self.assertNotIn("us_2026_niit", ids)
        self.assertNotIn("us_2026_additional_medicare_tax", ids)
        self.assertNotIn("us_2026_capital_gains_rates", ids)

    def test_unsupported_knowledge_year_does_not_rewrite_default_year_items(self) -> None:
        from backend.knowledge.tips import TipContext, get_deadlines, get_tips

        ctx = TipContext(tax_year=2027)

        self.assertEqual(get_tips(ctx), [])
        self.assertEqual(get_deadlines(ctx), [])

    def test_tips_have_required_fields(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(state="CA", income_types=("w2",)))

        for tip in tips:
            self.assertIn("knowledge_id", tip)
            self.assertIn("title", tip)
            self.assertIn("topic", tip)
            self.assertIn("summary", tip)
            self.assertIn("sources", tip)

    def test_tips_sorted_by_relevance(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(state="CA", income_types=("self_employment",)))

        self.assertEqual([tip["relevance"] for tip in tips], sorted((tip["relevance"] for tip in tips), reverse=True))

    def test_max_tips_cap(self) -> None:
        from backend.knowledge.tips import TipContext, get_tips

        tips = get_tips(TipContext(), max_tips=3)

        self.assertLessEqual(len(tips), 3)


class TestDeadlines(unittest.TestCase):
    def test_deadlines_include_april_filing(self) -> None:
        from backend.knowledge.tips import TipContext, get_deadlines

        deadlines = get_deadlines(TipContext())
        dates = [deadline["date"] for deadline in deadlines]

        self.assertIn("2027-04-15", dates)

    def test_deadlines_sorted_by_date(self) -> None:
        from backend.knowledge.tips import TipContext, get_deadlines

        deadlines = get_deadlines(TipContext(income_types=("self_employment",)))
        dates = [deadline["date"] for deadline in deadlines]

        self.assertEqual(dates, sorted(dates))

    def test_self_employed_sees_estimated_deadlines(self) -> None:
        from backend.knowledge.tips import TipContext, get_deadlines

        deadlines = get_deadlines(TipContext(income_types=("self_employment",)))
        summaries = " ".join(deadline["summary"] for deadline in deadlines).lower()

        self.assertIn("estimated", summaries)
        self.assertIn("2027-01-15", [deadline["date"] for deadline in deadlines])

    def test_foreign_sees_june_extension(self) -> None:
        from backend.knowledge.tips import TipContext, get_deadlines

        deadlines = get_deadlines(TipContext(income_types=("foreign",)))
        summaries = " ".join(deadline["summary"] for deadline in deadlines).lower()

        self.assertTrue("abroad" in summaries or "june" in summaries)
        self.assertIn("2027-06-15", [deadline["date"] for deadline in deadlines])

    def test_deadlines_have_required_fields(self) -> None:
        from backend.knowledge.tips import TipContext, get_deadlines

        deadlines = get_deadlines(TipContext())

        for deadline in deadlines:
            self.assertIn("knowledge_id", deadline)
            self.assertIn("title", deadline)
            self.assertIn("summary", deadline)
            self.assertIn("date", deadline)
            self.assertIn("sources", deadline)


class TestTipsRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_tips_endpoint_200(self) -> None:
        response = self.client.get("/api/tips")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("tips", data)
        self.assertIn("deadlines", data)
        self.assertIn("profile_used", data)
        self.assertIn("context", data)

    def test_tips_with_state_param(self) -> None:
        response = self.client.get("/api/tips", params={"state": "CA", "income_types": "w2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["context"]["state"], "CA")

    def test_tips_self_employment(self) -> None:
        response = self.client.get("/api/tips", params={"income_types": "self_employment"})

        self.assertEqual(response.status_code, 200)
        topics = [tip["topic"] for tip in response.json()["tips"]]
        self.assertTrue(any("self_employment" in topic or "estimated" in topic for topic in topics))

    def test_tips_fallback_when_profile_id_missing_or_pg_unavailable(self) -> None:
        response = self.client.get("/api/tips", params={"profile_id": "08af5e52-8b75-4d69-a98f-7225939c91d0"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["profile_used"])

    def test_existing_routes_unaffected(self) -> None:
        calc = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )
        skills = self.client.get("/api/skills")
        search = self.client.get("/api/knowledge/search", params={"q": "FEIE"})
        assistant = self.client.post("/api/assistant/query", json={"query": "hello"})

        self.assertEqual(calc.status_code, 200)
        self.assertEqual(skills.status_code, 200)
        self.assertEqual(search.status_code, 200)
        self.assertEqual(assistant.status_code, 200)


if __name__ == "__main__":
    unittest.main()
