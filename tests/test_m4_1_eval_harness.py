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

    def test_invalid_gate_raises(self):
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                run_eval_harness(gate=bad)

    def test_unknown_weight_key_raises(self):
        with self.assertRaises(ValueError):
            run_eval_harness(weights={"intnet": 1.0})  # typo

    def test_negative_or_zero_sum_weights_raise(self):
        with self.assertRaises(ValueError):
            run_eval_harness(weights={"intent": -1.0, "factcheck": 1.0})
        with self.assertRaises(ValueError):
            run_eval_harness(weights={"intent": 0.0, "factcheck": 0.0})

    def test_nan_weight_raises(self):
        with self.assertRaises(ValueError):
            run_eval_harness(weights={"intent": float("nan"), "factcheck": 1.0})

    def test_validation_runs_before_classifier(self):
        # Misconfiguration must fail before the (possibly expensive) classifier runs.
        def boom(_query):
            raise AssertionError("classifier should not be called when config is invalid")

        with self.assertRaises(ValueError):
            run_eval_harness(intent_classifier=boom, weights={"intnet": 1.0})
        with self.assertRaises(ValueError):
            run_eval_harness(intent_classifier=boom, gate=2.0)

    def test_single_dimension_weight_is_allowed(self):
        # Weighting only one known dimension is valid (subset, positive sum).
        report = run_eval_harness(weights={"factcheck": 1.0})
        self.assertEqual(report.overall, report.dimensions["factcheck"].score)

    def test_zero_weight_dimension_is_skipped(self):
        # weight 0 for a dimension disables it: its (here expensive/booming)
        # evaluator is never run and it is absent from the report.
        def boom(_query):
            raise AssertionError("intent classifier should be skipped at weight 0")

        report = run_eval_harness(intent_classifier=boom, weights={"factcheck": 1.0})
        self.assertEqual(set(report.dimensions), {"factcheck"})
        self.assertEqual(report.overall, report.dimensions["factcheck"].score)

    def test_as_dict_is_json_serializable(self):
        import json

        report = run_eval_harness()
        payload = json.loads(json.dumps(report.as_dict()))
        self.assertIn("dimensions", payload)
        self.assertIn("intent", payload["dimensions"])
        self.assertIn("overall", payload)


if __name__ == "__main__":
    unittest.main()
