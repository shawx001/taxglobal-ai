from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.main import create_app
from engine.rules_loader import RuleLoadError


class TestSkillBase(unittest.TestCase):
    def test_tax_skill_result_envelope(self) -> None:
        from backend.skills.base import TaxSkill

        class DummyInput(BaseModel):
            value: int

        class DummySkill(TaxSkill):
            name: str = "dummy"
            description: str = "Dummy skill."
            args_schema: type[BaseModel] = DummyInput
            source_attribution = "dummy-source"
            engine_function_name = "dummy_engine"

            def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
                return {"status": "ok", "value": params["value"]}

        result = DummySkill().invoke({"value": 7})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], {"status": "ok", "value": 7})
        self.assertEqual(result["source_attribution"], "dummy-source")
        self.assertEqual(result["engine_function"], "dummy_engine")

    def test_skill_is_langchain_tool(self) -> None:
        from backend.skills.base import LangChainBaseTool
        from backend.skills.registry import get_all_skills

        for skill in get_all_skills():
            self.assertIsInstance(skill, LangChainBaseTool)


class TestSkillRegistry(unittest.TestCase):
    def test_registry_has_five_skills(self) -> None:
        from backend.skills.registry import get_all_skills

        self.assertEqual(len(get_all_skills()), 5)

    def test_registry_skill_names(self) -> None:
        from backend.skills.registry import get_all_skills

        self.assertEqual(
            sorted(skill.name for skill in get_all_skills()),
            [
                "analyze_rsu",
                "assess_feie",
                "calculate_income_tax",
                "detect_nexus",
                "track_crypto",
            ],
        )

    def test_get_skill_not_found(self) -> None:
        from backend.skills.registry import get_skill

        self.assertIsNone(get_skill("nonexistent"))


class TestSkillExecution(unittest.TestCase):
    def test_calculate_income_tax_calls_engine(self) -> None:
        from backend.skills.calculate_income_tax import CalculateIncomeTax

        engine_result = {"status": "ok", "total_tax": "123.45"}
        with patch("backend.skills.calculate_income_tax.income_tax_summary", return_value=engine_result) as mocked:
            result = CalculateIncomeTax().invoke(
                {
                    "w2_wages": 120000,
                    "filing_status": "single",
                    "state_code": "CA",
                    "tax_year": 2026,
                }
            )

        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["w2_wages"], Decimal("120000"))
        self.assertEqual(call_kwargs["filing_status"], "single")
        self.assertEqual(call_kwargs["state_code"], "CA")
        self.assertEqual(call_kwargs["tax_year"], 2026)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], engine_result)
        self.assertEqual(result["engine_function"], "income_tax_summary")
        self.assertIn("source_attribution", result)

    def test_calculate_income_tax_preserves_decimal_string_amounts(self) -> None:
        from backend.skills.calculate_income_tax import CalculateIncomeTax

        with patch(
            "backend.skills.calculate_income_tax.income_tax_summary",
            return_value={"status": "ok", "total_tax": "0.00"},
        ) as mocked:
            CalculateIncomeTax().invoke({"w2_wages": "120000.10", "filing_status": "single", "tax_year": 2026})

        self.assertEqual(mocked.call_args.kwargs["w2_wages"], Decimal("120000.10"))

    def test_assess_feie_calls_engine(self) -> None:
        from backend.skills.assess_feie import AssessFeie

        engine_result = {"status": "ok", "excluded_income": "120000.00"}
        with patch("backend.skills.assess_feie.feie_estimate", return_value=engine_result) as mocked:
            result = AssessFeie().invoke(
                {"foreign_earned_income": 120000, "days_abroad": 335, "tax_year": 2026}
            )

        mocked.assert_called_once_with(foreign_earned_income=Decimal("120000"), days_abroad=335, tax_year=2026)
        self.assertEqual(result["result"], engine_result)
        self.assertEqual(result["engine_function"], "feie_estimate")

    def test_analyze_rsu_calls_engine(self) -> None:
        from backend.skills.analyze_rsu import AnalyzeRsu

        engine_result = {"status": "ok", "vest_income_tax": "1000.00"}
        with patch("backend.skills.analyze_rsu.rsu_tax_estimate", return_value=engine_result) as mocked:
            result = AnalyzeRsu().invoke(
                {
                    "shares_vested": 100,
                    "fmv_per_share": 40,
                    "vest_date": "2026-02-01",
                    "sale_scenario": {"sale_date": "2027-03-01", "sale_price_per_share": "50.25"},
                    "tax_year": 2026,
                }
            )

        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["shares_vested"], Decimal("100"))
        self.assertEqual(call_kwargs["fair_market_value_per_share"], Decimal("40"))
        self.assertEqual(
            call_kwargs["sale_scenario"],
            {"sale_date": "2027-03-01", "sale_price_per_share": Decimal("50.25")},
        )
        self.assertNotIn("fmv_per_share", call_kwargs)
        self.assertEqual(result["result"], engine_result)
        self.assertEqual(result["engine_function"], "rsu_tax_estimate")

    def test_track_crypto_calls_engine(self) -> None:
        from backend.skills.track_crypto import TrackCrypto

        engine_result = {"status": "ok", "net_capital_gain": "2500.00"}
        body = {
            "lots": [{"asset": "BTC", "date": "2025-01-01", "quantity": 1, "cost_basis": 10000}],
            "disposals": [{"asset": "BTC", "date": "2026-01-15", "quantity": 1, "proceeds": 12500}],
            "method": "fifo",
            "tax_year": 2026,
        }
        with patch("backend.skills.track_crypto.crypto_gain_estimate", return_value=engine_result) as mocked:
            result = TrackCrypto().invoke(body)

        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["method"], "FIFO")
        self.assertEqual(call_kwargs["lots"][0]["cost_basis"], Decimal("10000"))
        self.assertEqual(call_kwargs["disposals"][0]["proceeds"], Decimal("12500"))
        self.assertEqual(result["result"], engine_result)
        self.assertEqual(result["engine_function"], "crypto_gain_estimate")

    def test_detect_nexus_calls_engine(self) -> None:
        from backend.skills.detect_nexus import DetectNexus

        engine_result = {"status": "ok", "nexus_status": "triggered"}
        with patch("backend.skills.detect_nexus.nexus_estimate", return_value=engine_result) as mocked:
            result = DetectNexus().invoke(
                {"state_code": "CA", "sales_amount": 600000, "transaction_count": 200, "tax_year": 2026}
            )

        mocked.assert_called_once_with(
            state_code="CA",
            sales_amount=Decimal("600000"),
            transaction_count=200,
            tax_year=2026,
        )
        self.assertEqual(result["result"], engine_result)
        self.assertEqual(result["engine_function"], "nexus_estimate")


class TestSkillRoutes(unittest.TestCase):
    def setUp(self) -> None:
        from backend import config

        self._config_patchers = [
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
        ]
        for patcher in self._config_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = create_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_list_skills_returns_200(self) -> None:
        response = self.client.get("/api/skills")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 5)
        self.assertEqual(len(body["skills"]), 5)
        for skill in body["skills"]:
            self.assertIn("name", skill)
            self.assertIn("description", skill)
            self.assertIn("input_schema", skill)

    def test_invoke_skill_returns_200(self) -> None:
        engine_result = {
            "status": "ok",
            "input": {"tax_year": 2026},
            "result": {"total_tax": 123.45},
            "breakdown": [],
            "rule_version": "test",
            "citations": [],
            "assumptions": [],
            "reason": None,
        }
        with patch(
            "backend.skills.calculate_income_tax.income_tax_summary",
            return_value=engine_result,
        ):
            response = self.client.post(
                "/api/skills/calculate_income_tax",
                json={"w2_wages": 120000, "filing_status": "single", "state_code": "CA", "tax_year": 2026},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["result"]["total_tax"], 123.45)
        self.assertEqual(body["engine_function"], "income_tax_summary")

    def test_invoke_skill_not_found_returns_404(self) -> None:
        response = self.client.post("/api/skills/nonexistent", json={})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "skill_not_found")

    def test_invoke_skill_invalid_input_returns_422(self) -> None:
        response = self.client.post("/api/skills/assess_feie", json={})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_invoke_skill_engine_invalid_input_returns_422(self) -> None:
        with patch(
            "backend.skills.calculate_income_tax.income_tax_summary",
            return_value={"status": "invalid_input", "reason": "Negative income"},
        ):
            response = self.client.post(
                "/api/skills/calculate_income_tax",
                json={"w2_wages": 120000, "filing_status": "single", "tax_year": 2026},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_input")

    def test_invoke_skill_unsupported_tax_year_returns_422(self) -> None:
        with patch("backend.skills.assess_feie.feie_estimate", side_effect=RuleLoadError("missing")):
            response = self.client.post(
                "/api/skills/assess_feie",
                json={"foreign_earned_income": 120000, "days_abroad": 335, "tax_year": 2030},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unsupported_tax_year")

    def test_invoke_skill_unexpected_error_returns_500(self) -> None:
        with patch(
            "backend.skills.assess_feie.feie_estimate",
            side_effect=RuntimeError("unexpected engine failure"),
        ):
            response = self.client.post(
                "/api/skills/assess_feie",
                json={"foreign_earned_income": 120000, "days_abroad": 335, "tax_year": 2026},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")

    def test_invoke_skill_invalid_filing_status_returns_422(self) -> None:
        response = self.client.post(
            "/api/skills/calculate_income_tax",
            json={"w2_wages": 120000, "filing_status": "bad_status", "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 422)

    def test_existing_calc_routes_unaffected(self) -> None:
        response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class TestSkillGracefulDegradation(unittest.TestCase):
    def setUp(self) -> None:
        from backend import config

        self._config_patchers = [
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
        ]
        for patcher in self._config_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = create_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_skills_work_without_pg(self) -> None:
        response = self.client.post(
            "/api/skills/assess_feie",
            json={"foreign_earned_income": 120000, "days_abroad": 335, "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine_function"], "feie_estimate")

    def test_calc_unaffected_by_skills(self) -> None:
        response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
