"""Tests for M3.4 LLM answer fact-checking."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

import backend.config as cfg
from backend.llm.provider import MockProvider
from backend.orchestrator.nodes import format_node


def _skill_state() -> dict:
    return {
        "query": "加州年薪15万交多少税",
        "intent": "income_tax",
        "confidence": "keyword_match",
        "matched_keyword": "所得税",
        "skill_output": {
            "result": {"total_tax": "24734.00", "effective_rate": "0.1649"},
            "source_attribution": "IRS Rev. Proc. 2024-40",
            "engine_function": "calculate_income_tax",
        },
        "nodes_visited": [],
    }


class TestFactCheckerUnit(unittest.TestCase):
    """Unit tests for check_response_fidelity()."""

    def test_passes_matching_engine_float_amount(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity(
            "联邦税 $24,734.00，来源 IRS Rev. Proc. 2024-40。",
            {"data": {"total_tax": 24734.0}},
            ["IRS Rev. Proc. 2024-40"],
        )
        self.assertEqual(result.verdict, VERDICT_PASS)
        self.assertEqual(result.issues, [])

    def test_blocks_tampered_amount(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        result = check_response_fidelity("联邦税 $24,700.00。", {"data": {"total_tax": 24734.0}}, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)
        self.assertEqual(result.issues, ["llm_amount_not_in_engine_output"])

    def test_blocks_hallucinated_amount(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        result = check_response_fidelity("另外还能省 $1,000.00。", {"data": {"total_tax": 24734.0}}, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)

    def test_passes_formatted_thousands_amount(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity("总税额 $13,200.00。", {"data": {"total_tax": 13200.0}}, [])
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_passes_amount_without_cents(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity("总税额 $24,734。", {"data": {"total_tax": 24734.0}}, [])
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_passes_string_engine_amount(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity("总税额 $24,734.00。", {"data": {"total_tax": "24734.00"}}, [])
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_passes_negative_amount_formats(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        answer = {"data": {"capital_gain": "-1000.00"}}
        for text in ("亏损 -$1,000.00。", "亏损 $-1,000.00。", "亏损 ($1,000.00)。"):
            with self.subTest(text=text):
                result = check_response_fidelity(text, answer, [])
                self.assertEqual(result.verdict, VERDICT_PASS)

    def test_blocks_positive_amount_when_engine_amount_is_negative(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        result = check_response_fidelity("资本利得 $1,000.00。", {"data": {"capital_gain": "-1000.00"}}, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)

    def test_non_money_numbers_do_not_authorize_dollar_amounts(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        answer = {"data": {"tax_year": 2026, "effective_rate": "0.16", "shares": 1000, "days_abroad": 330}}
        self.assertEqual(check_response_fidelity("$2,026.00", answer, []).verdict, VERDICT_BLOCK)
        self.assertEqual(check_response_fidelity("$0.16", answer, []).verdict, VERDICT_BLOCK)
        self.assertEqual(check_response_fidelity("$1,000.00", answer, []).verdict, VERDICT_BLOCK)
        self.assertEqual(check_response_fidelity("$330.00", answer, []).verdict, VERDICT_BLOCK)

    def test_passes_no_amounts_when_source_is_cited(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity(
            "标准扣除是固定扣除额，来源 irs-pub-501。",
            {"type": "knowledge", "results": []},
            ["irs-pub-501"],
        )
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_warns_on_advice(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_WARN, check_response_fidelity

        result = check_response_fidelity("建议你投资指数基金。", {}, [])
        self.assertEqual(result.verdict, VERDICT_WARN)
        self.assertIn("out_of_scope_advice", result.issues)

    def test_warns_on_absolute_claim(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_WARN, check_response_fidelity

        result = check_response_fidelity("保证退税。", {}, [])
        self.assertEqual(result.verdict, VERDICT_WARN)
        self.assertIn("absolute_claim", result.issues)

    def test_warns_on_missing_source_citation(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_WARN, check_response_fidelity

        result = check_response_fidelity("你的税额是这样计算的。", {}, ["IRS Rev. Proc. 2024-40"])
        self.assertEqual(result.verdict, VERDICT_WARN)
        self.assertIn("no_source_cited", result.issues)

    def test_correct_amount_with_advice_warns_not_blocks(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_WARN, check_response_fidelity

        result = check_response_fidelity("总税额 $24,734.00，建议你投资。", {"data": {"total_tax": 24734.0}}, [])
        self.assertEqual(result.verdict, VERDICT_WARN)
        self.assertIn("out_of_scope_advice", result.issues)

    def test_bool_is_not_collected_as_number(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        result = check_response_fidelity("$1.00", {"data": {"covered": True}}, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)

    def test_malformed_amounts_and_nested_non_numbers_do_not_crash(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_BLOCK, VERDICT_PASS, check_response_fidelity

        answer = {"data": [None, False, "not a number", {"total_tax": "24734.00"}]}
        result = check_response_fidelity("这些不是金额 $abc $.，真实金额 $ 24,734.00。", answer, [])
        self.assertEqual(result.verdict, VERDICT_PASS)
        # "$1,2,3" partially parses as $1.00 — fail-closed block, never a crash.
        result = check_response_fidelity("乱码 $1,2,3，真实金额 $ 24,734.00。", answer, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)

    def test_issue_strings_do_not_include_text_or_amounts(self) -> None:
        from backend.guardrail.fact_checker import check_response_fidelity

        result = check_response_fidelity("用户原文里有 $99,999.00 和 PII", {"data": {"total_tax": 24734.0}}, [])
        joined = " ".join(result.issues)
        self.assertNotIn("99,999", joined)
        self.assertNotIn("用户原文", joined)

    def test_non_string_sources_do_not_crash(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_WARN, check_response_fidelity

        result = check_response_fidelity("没有引用。", {}, [123])
        self.assertEqual(result.verdict, VERDICT_WARN)
        self.assertIn("no_source_cited", result.issues)

    def test_blocks_tampered_integer_amount_with_trailing_comma(self) -> None:
        """Regression: '$99,999, including...' must not evade extraction."""
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        answer = {"data": {"total_tax": 24734.0}}
        for text in ("总税额 $99,999, 包括联邦和州税。", "Your tax is $99,999, including state."):
            with self.subTest(text=text):
                self.assertEqual(check_response_fidelity(text, answer, []).verdict, VERDICT_BLOCK)

    def test_passes_legit_integer_amount_with_trailing_comma(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity("总税额 $24,734, 包括联邦税。", {"data": {"total_tax": 24734.0}}, [])
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_blocks_tenths_tamper_with_trailing_comma(self) -> None:
        """Regression: '$24,734.5,' must extract 24734.50, not 24734.00."""
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        result = check_response_fidelity("$24,734.5, 包括州税。", {"data": {"total_tax": 24734.0}}, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)

    def test_blocks_chinese_format_memory_amounts(self) -> None:
        """Regression (live 2026-06-11): '约12万美元' from LLM memory must not
        slip past the $-only pattern."""
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        answer = {"data": {"total_tax": 24734.0}}
        for text in ("最高可免约12万美元。", "免税额是 120,000美元。", "大约1.5万 美金。"):
            with self.subTest(text=text):
                self.assertEqual(check_response_fidelity(text, answer, []).verdict, VERDICT_BLOCK)

    def test_chinese_format_engine_amount_passes(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity("总税额约2万美元。", {"data": {"total_tax": 20000.0}}, [])
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_blocks_k_usd_and_cn_numeral_bypasses(self) -> None:
        """Regression: 130k / USD 130,000 / 十三万美元 / 13萬美刀 must not slip."""
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        answer = {"data": {"total_tax": 24734.0}}
        for text in (
            "上限大约是130k。",
            "上限大约是 USD 130,000。",
            "上限大约是十三万美元。",
            "上限大约是13萬美刀。",
        ):
            with self.subTest(text=text):
                self.assertEqual(check_response_fidelity(text, answer, []).verdict, VERDICT_BLOCK)

    def test_401k_mention_is_not_an_amount(self) -> None:
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity(
            "可以考虑 401k 和 529 计划。", {"data": {"total_tax": 24734.0}}, []
        )
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_blocks_sub_cent_tamper(self) -> None:
        """Regression: text amounts compare exactly — no rounding on the text
        side. ROUND_HALF_EVEN would collapse .005 onto .00 and PASS; even
        ROUND_HALF_UP on the text side would let .004 through."""
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        answer = {"data": {"total_tax": 24734.0}}
        for text in ("总税额 $24,734.005。", "总税额 $24,734.004。"):
            with self.subTest(text=text):
                self.assertEqual(check_response_fidelity(text, answer, []).verdict, VERDICT_BLOCK)

    def test_engine_half_up_rounding_matches_engine_money(self) -> None:
        """Engine-side normalization uses ROUND_HALF_UP like engine/money.py."""
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        # A string engine value with sub-cent precision rounds HALF_UP: .005 -> .01
        result = check_response_fidelity("税额 $24,734.01。", {"data": {"total_tax": "24734.005"}}, [])
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_authorizes_all_real_engine_money_keys(self) -> None:
        """Regression: threshold/limit/cost/fmv/ubia/insurance are money keys."""
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        cases = [
            ({"data": {"threshold": 500000.0}}, "门槛是 $500,000.00。"),
            ({"data": {"overall_limit": 17000.0}}, "上限 $17,000.00。"),
            ({"data": {"unit_cost": 1500.5}}, "单位成本 $1,500.50。"),
            ({"data": {"fmv_per_share": 42.0}}, "每股 $42.00。"),
            ({"data": {"ubia": 80000.0}}, "UBIA $80,000.00。"),
            ({"data": {"se_health_insurance": 6000.0}}, "扣除 $6,000.00。"),
        ]
        for answer, text in cases:
            with self.subTest(answer=answer):
                self.assertEqual(check_response_fidelity(text, answer, []).verdict, VERDICT_PASS)

    def test_engine_float_total_is_money(self) -> None:
        """crypto/payroll engine outputs use a bare 'total' money key."""
        from backend.guardrail.fact_checker import VERDICT_PASS, check_response_fidelity

        result = check_response_fidelity(
            "总税额 $13,200.00。", {"data": {"tax_estimate": {"total": 13200.0}}}, []
        )
        self.assertEqual(result.verdict, VERDICT_PASS)

    def test_knowledge_int_total_is_not_money(self) -> None:
        """knowledge-search 'total' is a result count, not an amount."""
        from backend.guardrail.fact_checker import VERDICT_BLOCK, check_response_fidelity

        result = check_response_fidelity("$5.00", {"type": "knowledge", "results": [], "total": 5}, [])
        self.assertEqual(result.verdict, VERDICT_BLOCK)

    def test_amounts_quoted_from_kb_text_are_authorized(self) -> None:
        """Amounts inside KB chunk text are user-visible facts, not tampering."""
        from backend.guardrail.fact_checker import (
            VERDICT_BLOCK,
            VERDICT_PASS,
            check_response_fidelity,
        )

        answer = {
            "type": "knowledge",
            "results": [{"text": "The standard deduction for single filers is $13,850 in 2023."}],
            "total": 1,
        }
        self.assertEqual(
            check_response_fidelity("单身标准扣除是 $13,850.00。", answer, []).verdict, VERDICT_PASS
        )
        self.assertEqual(
            check_response_fidelity("单身标准扣除是 $14,000.00。", answer, []).verdict, VERDICT_BLOCK
        )


class TestFactCheckerIntegration(unittest.TestCase):
    """Integration tests for format_node + fact-checker."""

    @patch("backend.llm.client.get_provider")
    def test_correct_llm_text_is_attached_with_pass_verdict(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("你的联邦税是 $24,734.00。来源：IRS Rev. Proc. 2024-40。")
            mock_get_provider.return_value = provider

            result = format_node(_skill_state())

            self.assertIn("answer_text", result["response"])
            self.assertEqual(result["response"]["fact_check"]["verdict"], "pass")
            self.assertEqual(result["response"]["fact_check"]["issues"], [])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_tampered_llm_text_is_dropped(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("你的联邦税是 $99,999.00。来源：IRS Rev. Proc. 2024-40。")
            provider.enqueue("重写后仍是 $99,999.00。")  # retry also tampered
            mock_get_provider.return_value = provider

            with self.assertLogs("taxglobal.orchestrator", level=logging.WARNING):
                result = format_node(_skill_state())

            self.assertNotIn("answer_text", result["response"])
            self.assertNotIn("fact_check", result["response"])
            self.assertEqual(result["response"]["answer"]["data"]["total_tax"], "24734.00")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_blocked_draft_rescued_by_feedback_retry(self, mock_get_provider) -> None:
        """First draft tampered → retry with feedback → clean draft attaches."""
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("最高可免约12万美元。来源：IRS Rev. Proc. 2024-40。")  # blocked
            provider.enqueue("你的联邦税是 $24,734.00。来源：IRS Rev. Proc. 2024-40。")  # retry clean
            mock_get_provider.return_value = provider

            result = format_node(_skill_state())

            self.assertIn("answer_text", result["response"])
            self.assertIn("$24,734.00", result["response"]["answer_text"])
            self.assertEqual(result["response"]["fact_check"]["verdict"], "pass")
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_llm_disabled_keeps_m2_schema(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = False
            result = format_node(_skill_state())

            self.assertNotIn("answer_text", result["response"])
            self.assertNotIn("fact_check", result["response"])
            mock_get_provider.assert_not_called()
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_warn_verdict_keeps_answer_text(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("你的联邦税是 $24,734.00。建议你投资。来源：IRS Rev. Proc. 2024-40。")
            mock_get_provider.return_value = provider

            result = format_node(_skill_state())

            self.assertIn("answer_text", result["response"])
            self.assertEqual(result["response"]["fact_check"]["verdict"], "warn")
            self.assertIn("out_of_scope_advice", result["response"]["fact_check"]["issues"])
        finally:
            cfg.ENABLE_LLM = original

    @patch("backend.llm.client.get_provider")
    def test_block_log_contains_no_llm_text_or_amounts(self, mock_get_provider) -> None:
        original = cfg.ENABLE_LLM
        try:
            cfg.ENABLE_LLM = True
            provider = MockProvider()
            provider.enqueue("敏感原文 $99,999.00")
            provider.enqueue("重写仍含 $99,999.00")  # retry also tampered
            mock_get_provider.return_value = provider

            with self.assertLogs("taxglobal.orchestrator", level=logging.WARNING) as logs:
                result = format_node(_skill_state())

            self.assertNotIn("answer_text", result["response"])
            joined = "\n".join(logs.output)
            self.assertNotIn("99,999", joined)
            self.assertNotIn("敏感原文", joined)
            self.assertIn("llm_amount_not_in_engine_output", joined)
        finally:
            cfg.ENABLE_LLM = original


if __name__ == "__main__":
    unittest.main()
