# 产品需求台账（Product Backlog）

用途：记录开发过程中 Shaw 提出的增量产品/体验需求，映射到落地 step，避免在分步推进中遗漏。与 `feature_status.md`（工程进度）配套——本表记"要做什么需求"，那表记"做到哪了"。

状态：🟢 已记录待设计 ｜ 🟡 已纳入某 step 设计 ｜ ✅ 已实现

---

| ID | 需求（用户原话/意图） | 落地 Step | 状态 | 设计要点 |
|---|---|---|---|---|
| REQ-001 | 建档案时收入分「美国境内」和「海外」两大类，便于计算 | 档案 schema：Step 4（计算输入）+ onboarding；持久化 Step 9 | 🟢 | 收入按来源分桶：US-domestic vs foreign-earned；桶内再分类型(W-2/自雇/加密/经营)。**直接对应引擎入参**：US 桶 → `federal_income_tax`/`state_income_tax`/`fica_tax`；foreign 桶 → `feie_estimate`(330天测试)，豁免后余额仍计美国税(公民全球征税)。后续 FTC/NIIT 也依赖此区分。 |
| REQ-002 | 点开「税务计算」模块时，自动把档案数据同步过去（不用重填） | Step 5（前端接后端）+ 合并计税 `income_tax_summary` | ✅ | 普通收入总览已改为档案驱动的单次 `/calc/income-summary` 调用，自动带入 W-2/自雇/资本利得等档案桶；前端不再把 federal/FICA/state 三段结果相加当总税。 |
| REQ-003 | 删除前端遗留 caStateTax/nyStateTax，州税一律走后端 | Step 5.4/5.7 + PR #87/#88 收尾 | ✅ | Step 5.4 `calcSE`、Step 5.7 ecom Nexus 先迁后端。收尾(2026-06-14)：PR #87 删除零调用的死原型(`nyStateTax`/`STATES`/`stateTaxOf`/`usEff`/`foreignTax`/`sgTax`/`ukTax`)；PR #88 把最后两处活路径(仪表盘 `renderDash`「预估年税额」、W-2 演示 `generateReport`)改走 `/calc/income-summary`，按 `profile.state` 真实州计算（带请求序号防竞态 + payload 缓存防刷 API + 按身份分桶 w2/SE/LTCG + 州未覆盖时诚实标注「未含州税」）。**`caStateTax/nyStateTax` 已从 `frontend/index.html` 完全消失**；根 `index.html` 冻结未动。 |
| REQ-004 | 海外收入拆成「海外赚取收入 FEIE」和「海外被动收入/FTC」 | 档案收入分桶 + FTC 引擎步骤 | 🟢 | FEIE 只适用于海外劳动/服务赚取收入，不适用于海外股息、利息、租金、资本利得等被动收入。海外被动收入仍可能需要美国申报，并可能走外国税收抵免(FTC)、税收协定、NIIT、PFIC 等规则。约束：前端不得把所有海外收入都展示为 FEIE 可豁免；后续建知识库/规则数据后再实现 FTC 与被动收入模块。 |
| REQ-005 | 档案模型拆成「职业身份 / 收入资产类型 / 居住税务状态」 | 档案 schema 重构 | 🟢 | 数字游民是居住/工作地点状态，不是收入类型；大厂员工也可能有海外收入，数字游民也可能有 W-2、RSU、加密或自雇收入。约束：税务计算入口不应只由单一身份决定；后续档案应允许独立勾选 RSU/期权、海外赚取收入、海外被动收入、加密、自雇等收入/资产类型。 |
| REQ-006 | 股票期权(NQSO/ISO/ESPP)单独模块 | 待引擎+数据 | 🟢 | RSU 面板移除了"未行权期权价值"输入。期权与 RSU 税务规则不同(行权价、AMT、持有期),需独立数据+引擎,不混入 RSU。本步只移除,记录待后续。 |
| REQ-009 | 全收入合并计税,把 W-2/自雇/其它普通收入/资本利得/海外剩余等汇成一个总税 | 分块扩 `income_tax_summary` | 🟡 | 引擎三块已齐:Block 1(Step 2.7)覆盖 W-2 + 自雇 + 其它普通收入;Block 2(Step 2.8)覆盖资本利得和 NIIT;Block 3(Step 2.9)覆盖 FEIE 税率叠加和 NIIT MAGI 加回；REQ-002 已把前端普通收入总览接到该合并入口。FTC、州级 FEIE 差异仍在后续。 |
| REQ-011 | 州级税基一致性 | 州数据+引擎 | 🟡 | 核心税基已精确(Step 1.4 数据 + Step 2.5 helper:起点/州标准扣除/免税额/QBI 一致性)。残余未建模:NY recapture、IL/GA 退休减项、CA Schedule CA、年龄/盲人额外扣除、州级抵免、IL 受养人数。命中时引擎 assumptions 标注。 |
| REQ-012 | 加密资本利得接州税 | Step 2.6 后端数据+引擎；Step 5.6 前端展示 | ✅ | `/calc/crypto` 支持可选 `state_code`:CA/NY/GA/IL/CO 按普通收入增量法计算州税,WA 按 2025 DOR capital gains excise(长期、$278,000 标准扣除、7%/9.9% 分档)计算,FL/NV 为 $0,未覆盖州诚实 not_covered。前端 crypto 模块已加州选择器、按含州总税排序三法,并展示 `state` 与 `total_tax_including_state`。 |
| REQ-013 | 2026 税年默认口径升级 | Step A 2026 tax year data | ✅ | 新增 `data/tax_years/2026/`，默认 `tax_year` 切到 2026；2025 测试/接口仍可显式 `tax_year=2025` 回归。州/Nexus 2026 暂沿用 2025 参数并标 `state_parameter_year:2025`，后续 Step B 更新州参数。 |
| REQ-014 | WA 长期资本利得 excise 接入合并计税 | Step B1 WA capital gains excise | ✅ | `income_tax_summary` 在常规 `state_income_tax` 外，数据驱动读取州规则里的 `capital_gains_excise` 并计入总税；WA 所得税行仍为 $0，excise 单独展示。计算 helper 与 crypto WA 路径共用，避免重复公式。 |
| REQ-015 | NJ/PA 所得税州接入合并计税 | Step B2 NJ + PA gross-income states | ✅ | 新增 `start_from:"gross_income"` 州税基，NJ 按 gross income 减 $1,000/人 exemption 后累进计税，PA 按 gross-income proxy flat 3.07%；资本利得在 NJ/PA 州侧按普通收入处理，OR 留 Step B2b。 |
| REQ-016 | OR state income tax in combined summary | Step B2b OR federal-tax subtraction state | done | Adds Oregon progressive state income tax. Tax base is federal AGI minus OR standard deduction minus federal tax liability subtraction. Subtraction limit is AGI-stepped from data, with no OR engine branch. Kicker, credits, additions, subtractions, and allocation are not modeled and are disclosed in assumptions. |

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
- 合并 → `income_tax_summary` 已按 REQ-009 完成引擎三块:Step 2.7 覆盖 W-2 + 自雇 + 其它普通收入;Step 2.8 覆盖资本利得和 NIIT;Step 2.9 覆盖 FEIE 税率叠加。后续再并入 FTC 与前端总览。

> 注意（合规诚实）：海外那块目前只做 FEIE 基础估算；外国税收抵免(FTC)、税收协定、各国当地税都标为"二期/暂未覆盖"，不伪造确定结论。

## REQ-002 设计草案（档案 → 计算同步）
- 档案是唯一数据源；各税务模块"打开即带入"，不让用户重复输入。
- 改档案(收入/州/身份/海外天数) → 相关计算与提醒实时重算。
- 没数据的部分(如未覆盖的州)沿用引擎现有 `not_covered` 行为，界面诚实提示。
