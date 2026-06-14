"""Tests for the M4.1 eval harness.

The harness must be deterministic and offline, so these assert the machinery
(perfect classifier -> 1.0, gate logic, report shape) and use the fact-check
dimension as a regression guard on the fact-checker (every labeled case must
still receive its expected verdict).
"""

from __future__ import annotations

import unittest

from backend.eval.datasets import FACTCHECK_TESTSET, INTENT_TESTSET
from backend.eval.harness import (
    DEFAULT_GATE,
    evaluate_factcheck,
    evaluate_intent,
    run_eval_harness,
)


class EvalHarnessTests(unittest.TestCase):
    def test_factcheck_dimension_is_perfect_regression_guard(self):
        # Every labeled fact-check case must still receive its expected verdict.
        dim = evaluate_factcheck()
        failures = [row for row in dim.rows if not row["ok"]]
        self.assertEqual(failures, [], f"fact-checker drifted on: {failures}")
        self.assertEqual(dim.score, 1.0)
        self.assertEqual(dim.total, len(FACTCHECK_TESTSET))

    def test_perfect_intent_classifier_scores_one(self):
        # A classifier that always returns the primary acceptable label is perfect.
        primary = {query: acceptable[0] for query, acceptable in INTENT_TESTSET}
        dim = evaluate_intent(lambda q: primary[q])
        self.assertEqual(dim.score, 1.0)
        self.assertEqual(dim.correct, len(INTENT_TESTSET))

    def test_wrong_intent_classifier_scores_zero(self):
        dim = evaluate_intent(lambda q: "__never_a_real_label__")
        self.assertEqual(dim.score, 0.0)
        self.assertEqual(dim.correct, 0)

    def test_keyword_baseline_runs_and_is_in_range(self):
        # The default keyword baseline must run without error; we don't assert it
        # clears the deploy gate (that gate is for a fine-tuned model).
        dim = evaluate_intent()
        self.assertEqual(dim.total, len(INTENT_TESTSET))
        self.assertGreaterEqual(dim.score, 0.0)
        self.assertLessEqual(dim.score, 1.0)

    def test_run_eval_harness_shape_and_overall(self):
        report = run_eval_harness()
        self.assertEqual(set(report.dimensions), {"intent", "factcheck"})
        self.assertEqual(report.gate, DEFAULT_GATE)
        # overall is the weighted mean of the two dimension scores.
        expected = (
            report.dimensions["intent"].score * report.weights["intent"]
            + report.dimensions["factcheck"].score * report.weights["factcheck"]
        ) / (report.weights["intent"] + report.weights["factcheck"])
        self.assertAlmostEqual(report.overall, expected, places=9)
        self.assertEqual(report.passed, report.overall >= report.gate)

    def test_gate_logic_with_perfect_classifier(self):
        # Perfect intent + perfect fact-check -> overall 1.0 -> passes any sane gate.
        primary = {query: acceptable[0] for query, acceptable in INTENT_TESTSET}
        report = run_eval_harness(intent_classifier=lambda q: primary[q], gate=0.80)
        self.assertEqual(report.dimensions["intent"].score, 1.0)
        self.assertEqual(report.dimensions["factcheck"].score, 1.0)
        self.assertEqual(report.overall, 1.0)
        self.assertTrue(report.passed)

    def test_as_dict_is_json_serializable(self):
        import json

        report = run_eval_harness()
        payload = json.loads(json.dumps(report.as_dict()))
        self.assertIn("dimensions", payload)
        self.assertIn("intent", payload["dimensions"])
        self.assertIn("overall", payload)


if __name__ == "__main__":
    unittest.main()
