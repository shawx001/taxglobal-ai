"""M4 evaluation harness package.

Measures model-facing quality (intent classification + fact-check fidelity)
deterministically and offline, producing an overall score plus the >=0.80
deployment gate used to admit a fine-tuned model (project plan v3.1 §6.6).
"""

from .harness import (
    DEFAULT_GATE,
    DEFAULT_WEIGHTS,
    DimensionScore,
    EvalReport,
    evaluate_factcheck,
    evaluate_intent,
    run_eval_harness,
)

__all__ = [
    "DEFAULT_GATE",
    "DEFAULT_WEIGHTS",
    "DimensionScore",
    "EvalReport",
    "evaluate_factcheck",
    "evaluate_intent",
    "run_eval_harness",
]
