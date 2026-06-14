"""M4 eval harness: scores model-facing quality and applies the deploy gate.

Two deterministic, offline dimensions:

- ``intent``: classification accuracy over ``INTENT_TESTSET``. ``evaluate_intent``
  accepts any ``classifier(query) -> intent_label`` so the same harness scores
  the keyword baseline (default) or a fine-tuned model.
- ``factcheck``: fact-check fidelity over ``FACTCHECK_TESTSET`` — the share of
  cases where ``check_response_fidelity`` returns the expected verdict.

``run_eval_harness`` combines them into a weighted ``overall`` and compares it to
``gate`` (default 0.80, project plan v3.1 §6.6) to decide whether a model may
ship. Engine numeric correctness is guaranteed separately by the golden tests
and is intentionally not folded into this model-quality score.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.guardrail.fact_checker import check_response_fidelity
from backend.orchestrator.intent import classify_intent

from .datasets import FACTCHECK_TESTSET, INTENT_TESTSET

DEFAULT_GATE = 0.80
DEFAULT_WEIGHTS: dict[str, float] = {"intent": 0.5, "factcheck": 0.5}


@dataclass(frozen=True)
class DimensionScore:
    """Score for one eval dimension."""

    name: str
    score: float
    correct: int
    total: int
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EvalReport:
    """Combined eval result with the deploy-gate verdict."""

    dimensions: dict[str, DimensionScore]
    overall: float
    gate: float
    passed: bool
    weights: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "gate": self.gate,
            "passed": self.passed,
            "weights": self.weights,
            "dimensions": {
                name: {
                    "score": dim.score,
                    "correct": dim.correct,
                    "total": dim.total,
                    "rows": dim.rows,
                }
                for name, dim in self.dimensions.items()
            },
        }


def _keyword_classifier(query: str) -> str:
    return classify_intent(query).intent


def evaluate_intent(classifier: Callable[[str], str] | None = None) -> DimensionScore:
    """Score intent accuracy. ``classifier`` defaults to the keyword baseline."""

    classify = classifier or _keyword_classifier
    rows: list[dict[str, Any]] = []
    correct = 0
    for query, acceptable in INTENT_TESTSET:
        predicted = classify(query)
        ok = predicted in acceptable
        correct += int(ok)
        rows.append({"query": query, "expected": acceptable, "predicted": predicted, "ok": ok})
    total = len(INTENT_TESTSET)
    return DimensionScore("intent", correct / total if total else 0.0, correct, total, rows)


def evaluate_factcheck() -> DimensionScore:
    """Score how often the fact-checker returns the expected verdict."""

    rows: list[dict[str, Any]] = []
    correct = 0
    for answer_text, answer, sources, expected in FACTCHECK_TESTSET:
        verdict = check_response_fidelity(answer_text, answer, sources).verdict
        ok = verdict == expected
        correct += int(ok)
        rows.append({"answer_text": answer_text, "expected": expected, "verdict": verdict, "ok": ok})
    total = len(FACTCHECK_TESTSET)
    return DimensionScore("factcheck", correct / total if total else 0.0, correct, total, rows)


def run_eval_harness(
    intent_classifier: Callable[[str], str] | None = None,
    weights: dict[str, float] | None = None,
    gate: float = DEFAULT_GATE,
) -> EvalReport:
    """Run every dimension and apply the weighted deploy gate.

    Because this decides whether a model ships, misconfiguration must fail loudly
    rather than silently skew ``overall``: ``gate`` must be within ``[0, 1]`` and
    ``weights`` must use known dimension keys, be non-negative, and sum positive.
    """

    # Validate everything BEFORE running the (potentially model-backed, expensive)
    # dimensions, so misconfiguration fails fast without wasting that compute.
    if not 0.0 <= gate <= 1.0:  # also rejects NaN (all NaN comparisons are False)
        raise ValueError(f"gate must be within [0, 1], got {gate!r}")

    weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
    valid_dimensions = set(DEFAULT_WEIGHTS)
    unknown = set(weights) - valid_dimensions
    if unknown:
        raise ValueError(f"unknown weight keys {sorted(unknown)}; expected a subset of {sorted(valid_dimensions)}")
    if not all(math.isfinite(value) for value in weights.values()):
        raise ValueError(f"weights must be finite, got {weights!r}")
    if any(value < 0 for value in weights.values()):
        raise ValueError(f"weights must be non-negative, got {weights!r}")
    total_weight = sum(weights.get(name, 0.0) for name in valid_dimensions)
    if total_weight <= 0:
        raise ValueError("weights must sum to a positive total over the eval dimensions")

    dimensions = {
        "intent": evaluate_intent(intent_classifier),
        "factcheck": evaluate_factcheck(),
    }
    overall = sum(dimensions[name].score * weights.get(name, 0.0) for name in dimensions) / total_weight
    return EvalReport(
        dimensions=dimensions,
        overall=overall,
        gate=gate,
        passed=overall >= gate,
        weights=dict(weights),
    )
