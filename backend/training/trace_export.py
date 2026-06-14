"""Turn production interaction traces into quality-filtered SFT examples.

Source-agnostic: a ``Trace`` can be built from an audit-log row pair
(``request_payload`` + ``response_payload`` from ``/api/assistant/query``) or
from a plain JSONL record. The pipeline only ever *filters* traces — it never
edits an answer.

Gold label precedence: an explicit user correction (``corrected_intent`` /
``corrected_answer_text``) always wins over the model's own prediction and is
the trusted signal. Without a correction, a predicted trace is admitted only as
a weak positive when it was fact-check ``pass`` and classified with enough
confidence — never reinforcing a ``clarify`` punt. A fact-check-``block``
*prediction* is therefore never used as training text; a user-corrected trace is
kept, but response examples only ever emit the correction or a ``pass`` answer
(never the blocked original). The new/historical mix (default 20% / 80%) follows
the plan's incremental-finetune recipe (project plan v3.1 §6.6).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.guardrail.fact_checker import VERDICT_PASS
from backend.orchestrator.intent import _INTENT_SYSTEM_PROMPT, _VALID_INTENTS, INTENT_CLARIFY
from backend.orchestrator.response import _RESPONSE_SYSTEM_PROMPT

DEFAULT_CONFIDENCE_FLOOR = 0.6
DEFAULT_ALLOWED_VERDICTS = frozenset({VERDICT_PASS})
DEFAULT_NEW_RATIO = 0.2


def _parse_confidence(value: Any) -> float:
    """Normalize a confidence value to a float in [0, 1].

    Production stores confidence as a string: ``"llm:0.95"`` (LLM score),
    ``"keyword_match"`` (deterministic keyword hit — treated as confident), or
    ``"fallback"`` / ``"unknown"`` (no real signal -> 0.0). Numeric values pass
    through. Anything unparseable degrades to 0.0 rather than raising.
    """

    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    if text.startswith("llm:"):
        try:
            return float(text[4:])
        except ValueError:
            return 0.0
    if text == "keyword_match":
        return 1.0
    try:
        return float(text)
    except ValueError:
        return 0.0


@dataclass(frozen=True)
class Trace:
    """One normalized production interaction."""

    query: str
    intent: str
    confidence: float = 0.0
    answer_text: str = ""
    sources: tuple[str, ...] = ()
    fact_check_verdict: str = ""
    answer: dict[str, Any] = field(default_factory=dict)
    corrected_intent: str | None = None
    corrected_answer_text: str | None = None

    @classmethod
    def from_audit(cls, request_payload: dict[str, Any], response_payload: dict[str, Any]) -> Trace:
        """Build from an audit-log request/response pair (PII already sanitized)."""

        fact_check = response_payload.get("fact_check")
        if isinstance(fact_check, dict):
            verdict = str(fact_check.get("verdict") or "")
        else:
            verdict = str(fact_check or "")
        sources = response_payload.get("sources") or []
        answer = response_payload.get("answer")
        return cls(
            query=str(request_payload.get("query") or ""),
            intent=str(response_payload.get("intent") or ""),
            confidence=_parse_confidence(response_payload.get("confidence")),
            answer_text=str(response_payload.get("answer_text") or ""),
            sources=tuple(str(s) for s in sources),
            fact_check_verdict=verdict,
            answer=answer if isinstance(answer, dict) else {},
            corrected_intent=request_payload.get("corrected_intent") or response_payload.get("corrected_intent"),
            corrected_answer_text=(
                request_payload.get("corrected_answer_text") or response_payload.get("corrected_answer_text")
            ),
        )


def gold_intent(trace: Trace) -> str:
    """The label to train on: a user correction wins over the prediction."""

    return trace.corrected_intent or trace.intent


def gold_answer_text(trace: Trace) -> str:
    return trace.corrected_answer_text or trace.answer_text


def is_quality_trace(
    trace: Trace,
    *,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    allowed_verdicts: frozenset[str] = DEFAULT_ALLOWED_VERDICTS,
) -> bool:
    """Keep a trace for training.

    A user-corrected trace is always gold. An uncorrected (predicted) trace is
    admitted only when its response was fact-check-acceptable, it was confident
    enough, and its label is a real, non-``clarify`` intent.
    """

    label = gold_intent(trace)
    if not label or label not in _VALID_INTENTS:
        return False
    if trace.corrected_intent or trace.corrected_answer_text:
        return True
    if label == INTENT_CLARIFY:
        return False
    if trace.fact_check_verdict not in allowed_verdicts:
        return False
    if not gold_answer_text(trace).strip():
        return False
    return trace.confidence >= confidence_floor


def quality_filter(traces: Iterable[Trace], **kwargs: Any) -> list[Trace]:
    return [trace for trace in traces if is_quality_trace(trace, **kwargs)]


def to_sft_intent_examples(traces: Iterable[Trace]) -> list[dict[str, Any]]:
    """Chat-format SFT examples for intent classification (query -> label)."""

    return [
        {
            "messages": [
                {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": trace.query},
                {"role": "assistant", "content": gold_intent(trace)},
            ]
        }
        for trace in traces
    ]


def to_sft_response_examples(traces: Iterable[Trace]) -> list[dict[str, Any]]:
    """Chat-format SFT examples for answer generation.

    The user message mirrors ``llm_format_response`` exactly (QUESTION /
    ENGINE_RESULT / SOURCES) so the system prompt's "match the engine numbers"
    instruction is meaningful at train time. Only trustworthy answers are
    emitted: an explicit user correction, or a fact-check ``pass`` original —
    never a blocked answer (even if the trace was intent-corrected)."""

    examples: list[dict[str, Any]] = []
    for trace in traces:
        answer_text = gold_answer_text(trace).strip()
        if not answer_text:
            continue
        trustworthy = bool(trace.corrected_answer_text) or trace.fact_check_verdict == VERDICT_PASS
        if not trustworthy:
            continue
        user = (
            f"QUESTION:\n{trace.query}\n\n"
            f"ENGINE_RESULT:\n{json.dumps(trace.answer, ensure_ascii=False, default=str)}\n\n"
            f"SOURCES:\n{json.dumps(list(trace.sources), ensure_ascii=False)}"
        )
        examples.append(
            {
                "messages": [
                    {"role": "system", "content": _RESPONSE_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": answer_text},
                ]
            }
        )
    return examples


def mix_datasets(
    new: list[dict[str, Any]],
    historical: list[dict[str, Any]],
    *,
    new_ratio: float = DEFAULT_NEW_RATIO,
) -> list[dict[str, Any]]:
    """Blend new and historical examples so ``new`` is ``new_ratio`` of the mix.

    Deterministic: keeps every ``new`` example and prepends as many leading
    ``historical`` examples as the ratio allows (caller pre-shuffles historical
    with its own seed if a random sample is wanted). Degrades gracefully when
    either side is short.
    """

    if not 0.0 < new_ratio <= 1.0:
        raise ValueError(f"new_ratio must be within (0, 1], got {new_ratio!r}")
    if not new:
        return list(historical)
    # ceil so every new example is kept and the new share never exceeds new_ratio.
    target_total = math.ceil(len(new) / new_ratio)
    historical_quota = max(0, target_total - len(new))
    chosen_historical = historical[:historical_quota]
    return list(new) + list(chosen_historical)


def traces_from_records(records: Iterable[dict[str, Any]]) -> list[Trace]:
    """Normalize raw records into ``Trace`` objects.

    Each record is either ``{"request": {...}, "response": {...}}`` (an audit
    pair) or a flat dict already shaped like the response payload (plus
    ``query``). Unrecognized records are skipped.
    """

    traces: list[Trace] = []
    for record in records:
        if "request" in record or "response" in record:
            traces.append(Trace.from_audit(record.get("request") or {}, record.get("response") or {}))
        elif "query" in record:
            traces.append(Trace.from_audit({"query": record.get("query")}, record))
    return traces


def export_jsonl(examples: Iterable[dict[str, Any]], path: str | Path) -> int:
    """Write examples as JSONL; returns the count written."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def traces_from_jsonl(path: str | Path) -> list[Trace]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    return traces_from_records(records)


# Re-export so callers don't reach into private names elsewhere.
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
