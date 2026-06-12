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

# (query, acceptable intents — first is primary)
TESTSET: list[tuple[str, list[str]]] = [
    # --- income_tax (10) ---
    ("我在加州年薪15万要交多少税", ["income_tax"]),
    ("单身在纽约挣12万，税后能拿多少", ["income_tax"]),
    ("I make 200k in Texas, what is my federal tax", ["income_tax"]),
    ("自雇收入8万要交多少税", ["income_tax"]),
    ("我的W-2工资是95000，帮我算税", ["income_tax"]),
    ("加州州税多少", ["income_tax", "knowledge"]),
    ("年收入50万的边际税率是多少", ["income_tax", "knowledge"]),
    ("我和老婆联合报税收入30万要交多少", ["income_tax"]),
    ("self employment tax on 120000 profit", ["income_tax"]),
    ("工资10万在西雅图，要交州税吗", ["income_tax"]),
    # --- feie (7) ---
    ("我在日本工作了340天，收入20万，FEIE能免多少", ["feie"]),
    ("海外收入怎么免税", ["feie", "knowledge"]),
    ("I lived in Singapore for 11 months, can I exclude my income", ["feie"]),
    ("Form 2555 怎么用", ["feie", "knowledge"]),
    ("330天测试怎么算", ["feie", "knowledge"]),
    ("我去年在德国住了300天挣了18万美元，能用海外收入豁免吗", ["feie"]),
    ("expat 报税收入排除怎么申请", ["feie", "knowledge"]),
    # --- rsu (7) ---
    ("我的RSU下个月vest 500股，怎么交税", ["rsu"]),
    ("RSU归属时按什么价格计税", ["rsu", "knowledge"]),
    ("公司股票归属了，要算税吗", ["rsu"]),
    ("equity compensation 怎么报税", ["rsu", "knowledge"]),
    ("1000股restricted stock vest，FMV是50块，税是多少", ["rsu"]),
    ("RSU vest 后马上卖会怎样", ["rsu", "knowledge"]),
    ("受限股票单位的税务处理", ["rsu", "knowledge"]),
    # --- crypto (7) ---
    ("我卖了比特币赚了5万，资本利得税多少", ["crypto"]),
    ("crypto tax 怎么算", ["crypto", "knowledge"]),
    ("以太坊亏损能抵税吗", ["crypto"]),
    ("NFT 出售要交税吗", ["crypto"]),
    ("加密货币的成本基础怎么算", ["crypto", "knowledge"]),
    ("wash sale 规则适用于crypto吗", ["crypto", "knowledge"]),
    ("卖币的钱要报税吗", ["crypto"]),
    # --- nexus (7) ---
    ("我在加州卖了60万的货，要交销售税吗", ["nexus"]),
    ("economic nexus 阈值是多少", ["nexus", "knowledge"]),
    ("远程电商在德州有nexus吗", ["nexus"]),
    ("Wayfair案对我有什么影响", ["nexus", "knowledge"]),
    ("我的网店在多个州有销售，需要注册吗", ["nexus"]),
    ("marketplace facilitator 代缴后我还要申报吗", ["nexus", "knowledge"]),
    ("销售税什么时候需要收", ["nexus", "knowledge"]),
    # --- knowledge (8) ---
    ("什么是standard deduction", ["knowledge"]),
    ("QBI扣除怎么算的", ["knowledge"]),
    ("报税截止日期是哪天", ["knowledge"]),
    ("what is the difference between tax credit and deduction", ["knowledge"]),
    ("AMT是什么意思", ["knowledge"]),
    ("401k供款能抵税吗", ["knowledge"]),
    ("Roth IRA 和 traditional IRA 有什么区别", ["knowledge"]),
    ("海外账户超过1万美元要申报什么表", ["knowledge", "feie"]),
    # --- clarify (4) ---
    ("你好", ["clarify"]),
    ("今天天气怎么样", ["clarify"]),
    ("帮我写首诗", ["clarify"]),
    ("asdfgh", ["clarify"]),
]


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
