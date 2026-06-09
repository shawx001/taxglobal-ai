from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import create_app


class TestIntentClassifier(unittest.TestCase):
    def test_classify_income_tax_english(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX, classify_intent

        result = classify_intent("How much income tax do I owe on 150000 in California?")

        self.assertEqual(result.intent, INTENT_INCOME_TAX)
        self.assertEqual(result.confidence, "keyword_match")

    def test_classify_income_tax_chinese(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX, classify_intent

        result = classify_intent("加州收入15万交多少税")

        self.assertEqual(result.intent, INTENT_INCOME_TAX)

    def test_classify_feie(self) -> None:
        from backend.orchestrator.intent import INTENT_FEIE, classify_intent

        self.assertEqual(classify_intent("FEIE 330 day test").intent, INTENT_FEIE)

    def test_classify_rsu(self) -> None:
        from backend.orchestrator.intent import INTENT_RSU, classify_intent

        self.assertEqual(classify_intent("RSU vesting tax").intent, INTENT_RSU)

    def test_classify_crypto(self) -> None:
        from backend.orchestrator.intent import INTENT_CRYPTO, classify_intent

        self.assertEqual(classify_intent("bitcoin capital gains").intent, INTENT_CRYPTO)

    def test_classify_nexus(self) -> None:
        from backend.orchestrator.intent import INTENT_NEXUS, classify_intent

        self.assertEqual(classify_intent("economic nexus threshold").intent, INTENT_NEXUS)

    def test_classify_knowledge(self) -> None:
        from backend.orchestrator.intent import INTENT_KNOWLEDGE, classify_intent

        self.assertEqual(classify_intent("what is standard deduction").intent, INTENT_KNOWLEDGE)

    def test_explanatory_feie_routes_to_knowledge(self) -> None:
        from backend.orchestrator.intent import INTENT_KNOWLEDGE, classify_intent

        self.assertEqual(classify_intent("what is FEIE").intent, INTENT_KNOWLEDGE)

    def test_explanatory_feie_chinese_suffix_routes_to_knowledge(self) -> None:
        from backend.orchestrator.intent import INTENT_KNOWLEDGE, classify_intent

        self.assertEqual(classify_intent("FEIE是什么").intent, INTENT_KNOWLEDGE)

    def test_explanatory_nexus_routes_to_knowledge(self) -> None:
        from backend.orchestrator.intent import INTENT_KNOWLEDGE, classify_intent

        self.assertEqual(classify_intent("explain economic nexus").intent, INTENT_KNOWLEDGE)

    def test_classify_ambiguous_fallback(self) -> None:
        from backend.orchestrator.intent import INTENT_CLARIFY, classify_intent

        result = classify_intent("hello")

        self.assertEqual(result.intent, INTENT_CLARIFY)
        self.assertEqual(result.confidence, "fallback")


class TestParameterExtraction(unittest.TestCase):
    def test_extract_state_chinese(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import extract_skill_params

        self.assertEqual(extract_skill_params("加州收入15万", INTENT_INCOME_TAX)["state_code"], "CA")

    def test_extract_state_english(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import extract_skill_params

        self.assertEqual(extract_skill_params("California income 150000", INTENT_INCOME_TAX)["state_code"], "CA")

    def test_extract_number_chinese(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import extract_skill_params

        self.assertEqual(extract_skill_params("收入15万", INTENT_INCOME_TAX)["w2_wages"], "150000")

    def test_extract_number_plain(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import extract_skill_params

        self.assertEqual(extract_skill_params("income 100000", INTENT_INCOME_TAX)["w2_wages"], "100000")

    def test_extract_self_employment_income(self) -> None:
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import extract_skill_params

        params = extract_skill_params("self-employment tax on 100000 income", INTENT_INCOME_TAX)

        self.assertEqual(params["net_self_employment_profit"], "100000")
        self.assertNotIn("w2_wages", params)

    def test_extract_feie_days_and_income(self) -> None:
        from backend.orchestrator.intent import INTENT_FEIE
        from backend.orchestrator.nodes import extract_skill_params

        params = extract_skill_params("FEIE income 120000 330 days", INTENT_FEIE)

        self.assertEqual(params["foreign_earned_income"], "120000")
        self.assertEqual(params["days_abroad"], 330)

    def test_year_not_treated_as_income(self) -> None:
        """Tax years 2025-2030 (and broader 2020-2040 range) must not become amounts."""
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import extract_skill_params

        for year in ("2025", "2026", "2027", "2029", "2030"):
            params = extract_skill_params(f"income tax {year}", INTENT_INCOME_TAX)
            self.assertNotIn("w2_wages", params, f"Year {year} should not become w2_wages")

    def test_self_employment_missing_params(self) -> None:
        """Self-employment query without amount should ask for SE profit, not W-2."""
        from backend.orchestrator.intent import INTENT_INCOME_TAX
        from backend.orchestrator.nodes import _missing_params

        missing = _missing_params(INTENT_INCOME_TAX, {"tax_year": 2026}, "self-employment tax")
        self.assertEqual(missing, ["net_self_employment_profit"])

        missing_w2 = _missing_params(INTENT_INCOME_TAX, {"tax_year": 2026}, "how much tax")
        self.assertEqual(missing_w2, ["w2_wages"])


class TestWorkflow(unittest.TestCase):
    def test_skill_workflow_income_tax(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("California income tax on income 150000", request_id="r1")

        self.assertEqual(response["intent"], "income_tax")
        self.assertEqual(response["answer"]["type"], "skill_result")
        self.assertEqual(response["answer"]["engine_function"], "income_tax_summary")
        self.assertIn("guardrail", response["trace"]["nodes_visited"])
        self.assertIn("IRS", response["sources"][0])

    def test_skill_workflow_feie(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("FEIE foreign earned income 120000 330 days", request_id="r2")

        self.assertEqual(response["intent"], "feie")
        self.assertEqual(response["answer"]["type"], "skill_result")
        self.assertEqual(response["answer"]["engine_function"], "feie_estimate")

    def test_kb_workflow(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        fake_results = {
            "results": [
                {
                    "title": "Standard deduction",
                    "content": "Federal standard deduction overview.",
                    "sources": [{"source_id": "irs_pub_17", "title": "IRS Pub 17"}],
                }
            ],
            "total": 1,
            "query_metadata": {"retrieval_method": "hybrid"},
        }
        with patch("backend.orchestrator.nodes.hybrid_search", return_value=fake_results):
            response = run_assistant_query("what is standard deduction", request_id="r3")

        self.assertEqual(response["intent"], "knowledge")
        self.assertEqual(response["answer"]["type"], "knowledge")
        self.assertEqual(response["answer"]["total"], 1)
        self.assertEqual(response["sources"], ["irs_pub_17"])
        self.assertEqual(response["trace"]["nodes_visited"], ["classify", "kb_route", "format"])

    def test_clarify_workflow(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("hello", request_id="r4")

        self.assertEqual(response["intent"], "clarify")
        self.assertEqual(response["answer"]["type"], "clarification")
        self.assertEqual(response["trace"]["nodes_visited"], ["classify", "clarify"])

    def test_missing_skill_params_clarifies_without_invoking(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("FEIE?", request_id="r5")

        self.assertEqual(response["intent"], "feie")
        self.assertEqual(response["answer"]["type"], "clarification")
        self.assertIn("foreign_earned_income", response["answer"]["missing_params"])

    def test_self_employment_workflow_uses_se_profit(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("self-employment tax on 100000 income", request_id="r5b")

        engine_input = response["answer"]["data"]["input"]
        self.assertEqual(engine_input["net_self_employment_profit"], 100000.0)
        self.assertEqual(engine_input["w2_wages"], 0.0)

    def test_guardrail_blocks_in_workflow(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        class FakeSkill:
            def invoke(self, _: dict[str, object]) -> dict[str, object]:
                return {
                    "status": "ok",
                    "result": {"status": "ok"},
                    "source_attribution": "fake",
                    "engine_function": "fabricated",
                }

        with patch("backend.orchestrator.nodes.get_skill", return_value=FakeSkill()):
            response = run_assistant_query("income tax 100000", request_id="r6")

        self.assertEqual(response["answer"]["type"], "error")
        self.assertFalse(response["answer"]["guardrail_passed"])

    def test_unexpected_skill_error_returns_structured_response(self) -> None:
        """Unexpected Skill exception → structured error, not 500."""
        from backend.orchestrator.graph import run_assistant_query

        class CrashingSkill:
            def invoke(self, _: dict[str, object]) -> dict[str, object]:
                raise RuntimeError("unexpected boom")

        with patch("backend.orchestrator.nodes.get_skill", return_value=CrashingSkill()):
            response = run_assistant_query("income tax 100000", request_id="r-crash")

        self.assertEqual(response["answer"]["type"], "error")
        self.assertIn("skill_route", response["trace"]["nodes_visited"])

    def test_trace_records_nodes(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("income tax 100000", request_id="r7")

        self.assertEqual(response["trace"]["nodes_visited"], ["classify", "skill_route", "guardrail", "format"])

    def test_response_structure(self) -> None:
        from backend.orchestrator.graph import run_assistant_query

        response = run_assistant_query("what is FEIE", request_id="r8")

        self.assertEqual({"intent", "confidence", "answer", "sources", "tips", "trace"}, set(response))


class TestAssistantRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_assistant_query_endpoint_200(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "income tax 100000"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "income_tax")

    def test_assistant_query_skill_route(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "California income tax 150000"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"]["type"], "skill_result")

    def test_assistant_query_kb_route(self) -> None:
        with patch("backend.orchestrator.nodes.hybrid_search", return_value={"results": [], "total": 0}):
            response = self.client.post("/api/assistant/query", json={"query": "what is standard deduction"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"]["type"], "knowledge")

    def test_assistant_query_clarify(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": "hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"]["type"], "clarification")

    def test_empty_query_rejected(self) -> None:
        response = self.client.post("/api/assistant/query", json={"query": ""})

        self.assertEqual(response.status_code, 422)

    def test_existing_routes_unaffected(self) -> None:
        calc_response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )
        skills_response = self.client.get("/api/skills")
        search_response = self.client.get("/api/knowledge/search", params={"q": "FEIE"})

        self.assertEqual(calc_response.status_code, 200)
        self.assertEqual(skills_response.status_code, 200)
        self.assertEqual(search_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
