"""Labeled evaluation datasets for the M4 eval harness.

Canonical home for the labeled sets that score model-facing quality. The only
import is the fact-checker's verdict constants (so expected verdicts stay in
sync with the checker); no I/O and no LLM, so the harness runs in CI.

- ``INTENT_TESTSET``: 50 natural-language queries with their acceptable intent
  label(s). Some queries legitimately serve the user through either of two
  intents (e.g. a FEIE skill route or a knowledge explanation); those list
  every acceptable label explicitly, first = primary.
- ``FACTCHECK_TESTSET``: ``(answer_text, engine_answer, sources, expected_verdict)``
  cases exercising the fact-checker's pass / warn / block paths. Authored so the
  current ``check_response_fidelity`` returns the expected verdict for each,
  making this dimension a regression guard on the fact-checker.
"""

from __future__ import annotations

from typing import Any

from backend.guardrail.fact_checker import VERDICT_BLOCK, VERDICT_PASS, VERDICT_WARN

# (query, acceptable intents — first is primary)
INTENT_TESTSET: list[tuple[str, list[str]]] = [
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

# (answer_text, engine_answer, sources, expected_verdict)
FACTCHECK_TESTSET: list[tuple[str, dict[str, Any], list[str], str]] = [
    # --- pass (3): every amount matches engine, no language issues ---
    ("您的联邦所得税约为 $24,734.00。", {"federal_income_tax": 24734.00}, [], VERDICT_PASS),
    (
        "工资 $100,000.00，联邦所得税 $13,170.00。",
        {"w2_wages": 100000.00, "federal_income_tax": 13170.00},
        [],
        VERDICT_PASS,
    ),
    (
        "联邦税 $24,734.00，来源 irs_pub_17。",
        {"federal_income_tax": 24734.00},
        ["irs_pub_17"],
        VERDICT_PASS,
    ),
    # --- warn (3): amounts match but a soft language/source issue ---
    (
        "联邦税 $24,734.00，建议你去做投资理财。",
        {"federal_income_tax": 24734.00},
        [],
        VERDICT_WARN,
    ),  # out_of_scope_advice
    (
        "联邦税 $24,734.00。",
        {"federal_income_tax": 24734.00},
        ["irs_pub_17"],
        VERDICT_WARN,
    ),  # no_source_cited
    ("这样保证能帮你省税。", {}, [], VERDICT_WARN),  # absolute_claim
    # --- block (3): unmatched / unverifiable / tampered amount ---
    ("联邦税 $99,999.00。", {"federal_income_tax": 24734.00}, [], VERDICT_BLOCK),  # not in engine
    ("大约十三万美元。", {"federal_income_tax": 130000.00}, [], VERDICT_BLOCK),  # cn numeral
    ("联邦税 $24,734.50。", {"federal_income_tax": 24734.00}, [], VERDICT_BLOCK),  # tampered cents
]
