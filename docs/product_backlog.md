# 产品需求台账（Product Backlog）

用途：记录开发过程中 Shaw 提出的增量产品/体验需求，映射到落地 step，避免在分步推进中遗漏。与 `feature_status.md`（工程进度）配套——本表记"要做什么需求"，那表记"做到哪了"。

状态：🟢 已记录待设计 ｜ 🟡 已纳入某 step 设计 ｜ ✅ 已实现

---

| ID | 需求（用户原话/意图） | 落地 Step | 状态 | 设计要点 |
|---|---|---|---|---|
| REQ-001 | 建档案时收入分「美国境内」和「海外」两大类，便于计算 | 档案 schema：Step 4（计算输入）+ onboarding；持久化 Step 9 | 🟢 | 收入按来源分桶：US-domestic vs foreign-earned；桶内再分类型(W-2/自雇/加密/经营)。**直接对应引擎入参**：US 桶 → `federal_income_tax`/`state_income_tax`/`fica_tax`；foreign 桶 → `feie_estimate`(330天测试)，豁免后余额仍计美国税(公民全球征税)。后续 FTC/NIIT 也依赖此区分。 |
| REQ-002 | 点开「税务计算」模块时，自动把档案数据同步过去（不用重填） | Step 5（前端接后端）+ 合并计税 `income_tax_summary` | 🟡 | Step 5.4 已让自雇模块可选择州/申报身份并调用 `/calc/income-summary`；档案作为单一数据源、打开计算模块自动带入仍待后续档案同步步骤完成。 |
| REQ-003 | 删除前端遗留 caStateTax/nyStateTax，州税一律走后端 | 迁移自雇/W-2/6国对比模块到后端时 | 🟡 | Step 5.4 已让 `calcSE` 不再使用前端硬编码州税，改走 `/calc/income-summary`；Step 5.7 已让 ecom Nexus 监控改走 `/calc/nexus`，删掉前端硬编码阈值/假销售税额。`caStateTax/nyStateTax` 仍被 6 国对比/旧原型模块使用，本步保留；待这些模块迁移后再删除。 |
| REQ-004 | 海外收入拆成「海外赚取收入 FEIE」和「海外被动收入/FTC」 | 档案收入分桶 + FTC 引擎步骤 | 🟢 | FEIE 只适用于海外劳动/服务赚取收入，不适用于海外股息、利息、租金、资本利得等被动收入。海外被动收入仍可能需要美国申报，并可能走外国税收抵免(FTC)、税收协定、NIIT、PFIC 等规则。约束：前端不得把所有海外收入都展示为 FEIE 可豁免；后续建知识库/规则数据后再实现 FTC 与被动收入模块。 |
| REQ-005 | 档案模型拆成「职业身份 / 收入资产类型 / 居住税务状态」 | 档案 schema 重构 | 🟢 | 数字游民是居住/工作地点状态，不是收入类型；大厂员工也可能有海外收入，数字游民也可能有 W-2、RSU、加密或自雇收入。约束：税务计算入口不应只由单一身份决定；后续档案应允许独立勾选 RSU/期权、海外赚取收入、海外被动收入、加密、自雇等收入/资产类型。 |
| REQ-006 | 股票期权(NQSO/ISO/ESPP)单独模块 | 待引擎+数据 | 🟢 | RSU 面板移除了"未行权期权价值"输入。期权与 RSU 税务规则不同(行权价、AMT、持有期),需独立数据+引擎,不混入 RSU。本步只移除,记录待后续。 |
| REQ-011 | 州级税基一致性 | 州数据+引擎 | 🟡 | 核心税基已精确(Step 1.4 数据 + Step 2.5 helper:起点/州标准扣除/免税额/QBI 一致性)。残余未建模:NY recapture、IL/GA 退休减项、CA Schedule CA、年龄/盲人额外扣除、州级抵免、IL 受养人数。命中时引擎 assumptions 标注。 |
| REQ-012 | 加密资本利得接州税 | Step 2.6 后端数据+引擎；Step 5.6 前端展示 | ✅ | `/calc/crypto` 支持可选 `state_code`:CA/NY/GA/IL/CO 按普通收入增量法计算州税,WA 按 2025 DOR capital gains excise(长期、$278,000 标准扣除、7%/9.9% 分档)计算,FL/NV 为 $0,未覆盖州诚实 not_covered。前端 crypto 模块已加州选择器、按含州总税排序三法,并展示 `state` 与 `total_tax_including_state`。 |

---

## REQ-001 设计草案（收入分桶）

建议档案里的收入结构（onboarding 收集、Step 9 持久化、Step 4 作为计算输入）：

```
income:
  us_domestic:                      # 美国境内
    w2_wages
    self_employment_net_profit
    crypto: { lots[], disposals[] }
    business_profit
    state                           # 所在/来源州
  foreign:                          # 海外
    foreign_earned_income
    days_abroad                     # FEIE 330 天测试
    foreign_tax_paid                # 预留给 FTC(二期)
  filing_status
```

计算时的分流（引擎都已就绪）：
- US 桶 → 联邦累进税 + 州税 + FICA
- foreign 桶 → FEIE 估算；**豁免后的余额并回美国应税收入**（美国对公民/居民全球征税，FEIE 只豁免到上限）
- 合并 → `income_tax_summary`（待建）把两边汇总成"总税负 + 总方案"

> 注意（合规诚实）：海外那块目前只做 FEIE 基础估算；外国税收抵免(FTC)、税收协定、各国当地税都标为"二期/暂未覆盖"，不伪造确定结论。

## REQ-002 设计草案（档案 → 计算同步）
- 档案是唯一数据源；各税务模块"打开即带入"，不让用户重复输入。
- 改档案(收入/州/身份/海外天数) → 相关计算与提醒实时重算。
- 没数据的部分(如未覆盖的州)沿用引擎现有 `not_covered` 行为，界面诚实提示。
