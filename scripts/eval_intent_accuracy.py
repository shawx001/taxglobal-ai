"""M3 acceptance criterion #3: LLM intent accuracy >= 95% on 50 queries.

Runs the PRODUCTION classification chain (llm_classify_intent with
keyword fallback, exactly like classify_node) against a labeled testset
of natural-language queries and reports accuracy.

Some queries legitimately serve the user through either of two intents
(e.g. "330天测试怎么算" works as a FEIE skill route or a knowledge
explanation) — those entries list every acceptable label explicitly.

Usage (requires a real key — this calls the live API ~50 times):
  $env:ENABLE_LLM="true"; $env:TAXGLOBAL_LLM_API_KEY="sk-..."
  python scripts/eval_intent_accuracy.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical labeled set lives in backend/eval/datasets.py (shared with the M4
# eval harness) so the two never drift.
from backend.eval.datasets import INTENT_TESTSET as TESTSET  # noqa: E402


def main() -> int:
    from backend import config

    if not (config.ENABLE_LLM and config.LLM_API_KEY):
        print("ERROR: set ENABLE_LLM=true and TAXGLOBAL_LLM_API_KEY first.")
        return 1

    from backend.llm.client import init_llm
    from backend.orchestrator.intent import classify_intent, llm_classify_intent

    init_llm()

    rows: list[dict] = []
    correct = 0
    llm_used = 0
    for query, acceptable in TESTSET:
        result = llm_classify_intent(query)
        if result is not None:
            predicted, via = result.intent, "llm"
            llm_used += 1
        else:
            predicted, via = classify_intent(query).intent, "keyword_fallback"
        ok = predicted in acceptable
        correct += ok
        rows.append(
            {"query": query, "expected": acceptable, "predicted": predicted, "via": via, "ok": ok}
        )
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {predicted:>10} ({via:<16}) <- {query}")
        time.sleep(0.2)  # be polite to the API

    accuracy = correct / len(TESTSET)
    print(f"\nAccuracy: {correct}/{len(TESTSET)} = {accuracy:.1%}  (LLM classified: {llm_used}/{len(TESTSET)})")
    print("PASS (>=95%)" if accuracy >= 0.95 else "FAIL (<95%)")

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "intent_accuracy_report.json"
    out_path.write_text(
        json.dumps(
            {"accuracy": accuracy, "correct": correct, "total": len(TESTSET), "llm_used": llm_used, "rows": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Report: {out_path}")
    return 0 if accuracy >= 0.95 else 2


if __name__ == "__main__":
    raise SystemExit(main())
