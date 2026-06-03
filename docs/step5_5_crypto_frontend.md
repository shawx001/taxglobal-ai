# Step 5.5 交付记录 — 加密前端接 `/calc/crypto`

日期:2026-06-02
分支:`feature/step5_5-crypto-frontend`

## 目标

把前端加密模块从单字段假算迁移到后端 `/calc/crypto`,用真实 lots/disposals 成本匹配展示 FIFO/LIFO/HIFO 三法对比、联邦资本利得税、NIIT 和 Form 8949 逐笔行。

## 改动

- `frontend/api.js`:新增 `TaxGlobalApi.crypto(payload)`。
- `frontend/index.html`:加密模块改为买入批次和卖出记录逐行录入,新增申报状态、成本法、其他普通应税收入和 Modified AGI 输入。
- `frontend/index.html`:重写 `calcCrypto` 为 async,并发调用 FIFO/LIFO/HIFO 三种方法,高亮总税最低方法,明细金额全部来自引擎返回。
- `frontend/index.html`:删除 `cr-proceeds` 单字段路径和 `CM` 假乘数估算,展示 8949 逐笔匹配行、citations、assumptions 和显著州税边界提示。
- `docs/feature_status.md`:新增 Step 5.5 前端加密税务接后端状态和文档索引。
- `docs/product_backlog.md`:新增 REQ-012,记录 crypto 州税后续缺口。

## 验收重点

- 默认数据集 BTC lots/disposal 打开即可计算;FIFO 显示短期利得 5000、长期利得 30000、总税 5633。
- 三法都调用真实后端 `/calc/crypto`,不再使用前端假乘数。
- 超卖或坏输入显示后端 `invalid_input` reason。
- 结果区醒目标注:本测算仅含联邦资本利得 + NIIT,不含州税。
- 根 `index.html` 未修改。

## 已知限制

- 本步不生成 Form 8949 PDF,只展示逐笔 8949 行。
- 本步不接 `profile.cryptoGain`;crypto lots/disposals 在模块内直接录入。
- 州资本利得税尚未建模,已记录为 REQ-012。
- 引擎 assumptions 继续负责提示 wash sale、specific-ID 文档、跨年 carryover、NFT collectible、staking/airdrop/fork 等范围限制。
