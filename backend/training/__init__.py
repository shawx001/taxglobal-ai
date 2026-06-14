"""M4 training pipeline: trace -> SFT dataset, and LoRA fine-tuning.

``trace_export`` turns production interaction traces (audit-log rows or a JSONL
file) into quality-filtered SFT examples in chat format, matching the production
system prompts so the fine-tune transfers. Numbers are never invented here:
traces are filtered, not edited, and fact-check-blocked responses are dropped.
"""

from .trace_export import (
    DEFAULT_ALLOWED_VERDICTS,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_NEW_RATIO,
    Trace,
    export_jsonl,
    gold_answer_text,
    gold_intent,
    is_quality_trace,
    mix_datasets,
    quality_filter,
    to_sft_intent_examples,
    to_sft_response_examples,
    traces_from_jsonl,
    traces_from_records,
)

__all__ = [
    "DEFAULT_ALLOWED_VERDICTS",
    "DEFAULT_CONFIDENCE_FLOOR",
    "DEFAULT_NEW_RATIO",
    "Trace",
    "export_jsonl",
    "gold_answer_text",
    "gold_intent",
    "is_quality_trace",
    "mix_datasets",
    "quality_filter",
    "to_sft_intent_examples",
    "to_sft_response_examples",
    "traces_from_jsonl",
    "traces_from_records",
]
