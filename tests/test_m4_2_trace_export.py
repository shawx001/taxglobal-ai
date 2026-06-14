"""Tests for the M4.2 trace -> SFT pipeline (synthetic traces, no DB)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.orchestrator.intent import _INTENT_SYSTEM_PROMPT
from backend.training.trace_export import (
    Trace,
    export_jsonl,
    gold_answer_text,
    gold_intent,
    is_quality_trace,
    mix_datasets,
    quality_filter,
    to_sft_intent_examples,
    to_sft_response_examples,
    traces_from_records,
)


def _pass(query="加州年薪15万要交多少税", intent="income_tax", **kw):
    base = dict(
        query=query,
        intent=intent,
        confidence=0.9,
        answer_text="您的联邦所得税约为 $24,734.00。",
        sources=("irs_pub_17",),
        fact_check_verdict="pass",
    )
    base.update(kw)
    return Trace(**base)


class QualityFilterTests(unittest.TestCase):
    def test_pass_confident_real_intent_is_kept(self):
        self.assertTrue(is_quality_trace(_pass()))

    def test_block_verdict_dropped(self):
        self.assertFalse(is_quality_trace(_pass(fact_check_verdict="block")))

    def test_warn_dropped_by_default_but_allowed_when_configured(self):
        t = _pass(fact_check_verdict="warn")
        self.assertFalse(is_quality_trace(t))
        self.assertTrue(is_quality_trace(t, allowed_verdicts=frozenset({"pass", "warn"})))

    def test_low_confidence_dropped(self):
        self.assertFalse(is_quality_trace(_pass(confidence=0.3)))

    def test_clarify_prediction_dropped(self):
        self.assertFalse(is_quality_trace(_pass(intent="clarify")))

    def test_unknown_intent_dropped(self):
        self.assertFalse(is_quality_trace(_pass(intent="totally_made_up")))

    def test_empty_answer_text_dropped(self):
        self.assertFalse(is_quality_trace(_pass(answer_text="   ")))

    def test_user_correction_is_always_gold(self):
        # Even a low-confidence, blocked, clarify trace is kept if user-corrected.
        t = _pass(
            intent="clarify",
            confidence=0.1,
            fact_check_verdict="block",
            corrected_intent="feie",
        )
        self.assertTrue(is_quality_trace(t))
        self.assertEqual(gold_intent(t), "feie")

    def test_corrected_answer_overrides(self):
        t = _pass(corrected_answer_text="改正后的答复")
        self.assertEqual(gold_answer_text(t), "改正后的答复")

    def test_quality_filter_keeps_only_good(self):
        traces = [_pass(), _pass(fact_check_verdict="block"), _pass(intent="clarify")]
        self.assertEqual(len(quality_filter(traces)), 1)


class SftFormatTests(unittest.TestCase):
    def test_intent_examples_use_production_prompt_and_gold_label(self):
        ex = to_sft_intent_examples([_pass(corrected_intent="feie")])
        self.assertEqual(len(ex), 1)
        msgs = ex[0]["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": _INTENT_SYSTEM_PROMPT})
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[2], {"role": "assistant", "content": "feie"})

    def test_response_examples_skip_empty_answers(self):
        ex = to_sft_response_examples([_pass(), _pass(answer_text="")])
        self.assertEqual(len(ex), 1)
        user = ex[0]["messages"][1]["content"]
        self.assertIn("QUESTION:", user)
        self.assertIn("ENGINE_RESULT:", user)  # must mirror production layout
        self.assertIn("SOURCES:", user)
        self.assertEqual(ex[0]["messages"][2]["content"], "您的联邦所得税约为 $24,734.00。")

    def test_response_includes_engine_result_json(self):
        t = _pass(answer={"federal_income_tax": 24734.0})
        ex = to_sft_response_examples([t])
        self.assertIn('"federal_income_tax": 24734.0', ex[0]["messages"][1]["content"])

    def test_response_skips_blocked_answer_even_if_intent_corrected(self):
        # Intent-corrected but the answer text was blocked and not rewritten:
        # the intent example is kept (gold label), but no response example is
        # emitted from the untrusted blocked text.
        t = _pass(fact_check_verdict="block", corrected_intent="feie")
        self.assertEqual(len(to_sft_intent_examples([t])), 1)
        self.assertEqual(to_sft_intent_examples([t])[0]["messages"][2]["content"], "feie")
        self.assertEqual(to_sft_response_examples([t]), [])

    def test_response_emits_blocked_answer_when_user_rewrote_it(self):
        t = _pass(fact_check_verdict="block", corrected_answer_text="人工改正后的答复")
        ex = to_sft_response_examples([t])
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["messages"][2]["content"], "人工改正后的答复")


class MixTests(unittest.TestCase):
    def test_default_ratio_blends_80_percent_historical(self):
        new = [{"id": f"n{i}"} for i in range(2)]
        historical = [{"id": f"h{i}"} for i in range(50)]
        mixed = mix_datasets(new, historical, new_ratio=0.2)
        # 2 new should be 20% of total -> total 10 -> 8 historical.
        self.assertEqual(len(mixed), 10)
        self.assertEqual(mixed[:2], new)
        self.assertEqual(len(mixed[2:]), 8)

    def test_short_historical_degrades(self):
        new = [{"id": "n0"}]
        mixed = mix_datasets(new, [{"id": "h0"}], new_ratio=0.2)
        self.assertEqual(mixed, [{"id": "n0"}, {"id": "h0"}])

    def test_empty_new_returns_historical(self):
        self.assertEqual(mix_datasets([], [{"id": "h0"}]), [{"id": "h0"}])

    def test_invalid_ratio_raises(self):
        for bad in (0.0, 1.5, -0.1):
            with self.assertRaises(ValueError):
                mix_datasets([{"a": 1}], [], new_ratio=bad)


class RecordAndIoTests(unittest.TestCase):
    def test_traces_from_audit_pair(self):
        records = [
            {
                "request": {"query": "我的RSU怎么交税"},
                "response": {
                    "intent": "rsu",
                    "confidence": 0.95,
                    "answer_text": "RSU 归属按 FMV 计税。",
                    "sources": ["irc_83"],
                    "fact_check": {"verdict": "pass", "issues": []},
                },
            }
        ]
        traces = traces_from_records(records)
        self.assertEqual(len(traces), 1)
        t = traces[0]
        self.assertEqual(t.query, "我的RSU怎么交税")
        self.assertEqual(t.intent, "rsu")
        self.assertEqual(t.fact_check_verdict, "pass")
        self.assertEqual(t.sources, ("irc_83",))

    def test_string_confidence_is_parsed_not_crashed(self):
        # Production confidence is a string ("llm:0.95" / "keyword_match" /
        # "fallback"); float() would crash on real audit logs.
        def conf(value):
            return traces_from_records(
                [{"query": "q", "response": {"intent": "income_tax", "confidence": value}}]
            )[0].confidence

        self.assertAlmostEqual(conf("llm:0.95"), 0.95)
        self.assertEqual(conf("keyword_match"), 1.0)
        self.assertEqual(conf("fallback"), 0.0)
        self.assertEqual(conf("unknown"), 0.0)
        self.assertAlmostEqual(conf(0.8), 0.8)

    def test_flat_record_shape(self):
        traces = traces_from_records([{"query": "什么是QBI", "intent": "knowledge", "fact_check": "pass"}])
        self.assertEqual(traces[0].intent, "knowledge")

    def test_unrecognized_record_skipped(self):
        self.assertEqual(traces_from_records([{"nope": 1}]), [])

    def test_export_jsonl_roundtrip(self):
        examples = to_sft_intent_examples([_pass()])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "sft.jsonl"
            n = export_jsonl(examples, out)
            self.assertEqual(n, 1)
            lines = out.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0]), examples[0])


if __name__ == "__main__":
    unittest.main()
