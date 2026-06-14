"""M4.3 LoRA fine-tune runner.

Fine-tunes the conversational model on an M4.2 SFT JSONL, then applies the M4.1
eval gate. Requires the optional training extras:

    pip install -r backend/requirements-training.txt

Usage:
  python scripts/run_lora_finetune.py --train docs/eval/sft_intent.jsonl \
      --output artifacts/lora-intent
  python scripts/run_lora_finetune.py --train data.jsonl --output out --no-gate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from backend.eval.harness import DEFAULT_GATE
    from backend.training.lora_finetune import (
        DEFAULT_BASE_MODEL,
        LoraConfigSpec,
        finetune,
        missing_training_deps,
    )

    parser = argparse.ArgumentParser(description="Run the M4.3 LoRA fine-tune + eval gate.")
    parser.add_argument("--train", required=True, help="SFT JSONL (from M4.2)")
    parser.add_argument("--output", required=True, help="adapter output directory")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--gate", type=float, default=DEFAULT_GATE)
    parser.add_argument("--no-gate", action="store_true", help="skip the post-train eval gate")
    args = parser.parse_args()

    missing = missing_training_deps()
    if missing:
        print(f"ERROR: missing optional training deps {missing}")
        print("Install with: pip install -r backend/requirements-training.txt")
        return 1

    spec = LoraConfigSpec(base_model=args.base_model, epochs=args.epochs)
    summary = finetune(args.train, args.output, spec=spec, gate=args.gate, run_gate=not args.no_gate)

    print(json.dumps({k: v for k, v in summary.items() if k != "eval"}, ensure_ascii=False, indent=2))
    if summary.get("eval"):
        ev = summary["eval"]
        print(f"eval overall {ev['overall']:.1%} (gate {ev['gate']:.0%}) -> {'PASS' if ev['passed'] else 'FAIL'}")

    if summary.get("passed") is False:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
