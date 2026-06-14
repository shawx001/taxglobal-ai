"""M4.2 trace -> SFT dataset exporter.

Reads interaction traces from a JSONL file (each line either an audit pair
``{"request": {...}, "response": {...}}`` or a flat response-shaped record with
a ``query`` field), quality-filters them, formats chat SFT examples for intent
and/or response, optionally blends with a historical JSONL at a target new
ratio, and writes JSONL.

Usage:
  python scripts/export_training_data.py --traces traces.jsonl --kind intent \
      --out-intent docs/eval/sft_intent.jsonl
  python scripts/export_training_data.py --traces traces.jsonl --kind both \
      --historical-intent docs/eval/sft_intent_history.jsonl \
      --historical-response docs/eval/sft_response_history.jsonl --new-ratio 0.2 \
      --out-intent out_intent.jsonl --out-response out_response.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_jsonl_examples(path: str | None) -> list[dict]:
    if not path:
        return []
    import json

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def main() -> int:
    from backend.training.trace_export import (
        DEFAULT_NEW_RATIO,
        export_jsonl,
        mix_datasets,
        quality_filter,
        to_sft_intent_examples,
        to_sft_response_examples,
        traces_from_jsonl,
    )

    parser = argparse.ArgumentParser(description="Export quality-filtered SFT data from traces.")
    parser.add_argument("--traces", required=True, help="input traces JSONL")
    parser.add_argument("--kind", choices=["intent", "response", "both"], default="intent")
    parser.add_argument("--out-intent", default="docs/eval/sft_intent.jsonl")
    parser.add_argument("--out-response", default="docs/eval/sft_response.jsonl")
    parser.add_argument("--historical-intent", default=None, help="historical intent JSONL to blend")
    parser.add_argument("--historical-response", default=None, help="historical response JSONL to blend")
    parser.add_argument("--new-ratio", type=float, default=DEFAULT_NEW_RATIO)
    args = parser.parse_args()

    traces = quality_filter(traces_from_jsonl(args.traces))
    print(f"kept {len(traces)} quality traces")

    if args.kind in ("intent", "both"):
        examples = to_sft_intent_examples(traces)
        history = _load_jsonl_examples(args.historical_intent)
        if history:
            examples = mix_datasets(examples, history, new_ratio=args.new_ratio)
        n = export_jsonl(examples, args.out_intent)
        print(f"intent SFT: {n} examples -> {args.out_intent}")

    if args.kind in ("response", "both"):
        examples = to_sft_response_examples(traces)
        history = _load_jsonl_examples(args.historical_response)
        if history:
            examples = mix_datasets(examples, history, new_ratio=args.new_ratio)
        n = export_jsonl(examples, args.out_response)
        print(f"response SFT: {n} examples -> {args.out_response}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
