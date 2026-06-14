"""M4.1 eval-harness runner.

Runs the offline eval harness (intent accuracy + fact-check fidelity), prints a
summary, writes ``docs/eval/eval_report.json``, and exits non-zero if the
overall score is below the deploy gate (default 0.80, project plan v3.1 §6.6).

By default it scores the deterministic keyword intent baseline — useful as a
regression check. To score a fine-tuned model, import ``run_eval_harness`` and
pass your ``classifier(query) -> intent_label``.

Usage:
  python scripts/eval_harness.py            # keyword baseline, gate 0.80
  python scripts/eval_harness.py --gate 0.7 # custom gate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from backend.eval.harness import DEFAULT_GATE, run_eval_harness

    parser = argparse.ArgumentParser(description="Run the M4 eval harness (offline).")
    parser.add_argument("--gate", type=float, default=DEFAULT_GATE, help="overall deploy gate (default 0.80)")
    args = parser.parse_args()

    report = run_eval_harness(gate=args.gate)

    for name, dim in report.dimensions.items():
        print(f"{name:>10}: {dim.correct}/{dim.total} = {dim.score:.1%}")
    print(f"{'overall':>10}: {report.overall:.1%}  (gate {report.gate:.0%})")
    print("PASS" if report.passed else "FAIL")

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eval_report.json"
    out_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out_path}")

    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
