# M1 Closure — Design Doc

> 目的：列出 M1 正式关闭前的 2 个代码任务设计，指导 Codex 实现。
> 作者：Claude（设计/review），执行：Codex
> 日期：2026-06-07

## PR-A: deepcopy 热路径优化

### 现状
`engine/rules_loader.py` 的 `load_rule_file()` 每次调用都对 LRU 缓存结果执行 `deepcopy()`，防止调用方修改缓存。每个 API 请求触发 1-3 次 deepcopy（联邦规则 + 州规则 + FICA 等），在高并发下是热路径瓶颈。

### 方案：递归冻结（freeze）+ 直接返回
1. 新增 `_freeze(obj)` 工具函数：
   - `dict` → `types.MappingProxyType(dict)` 递归
   - `list` → `tuple` 递归
   - 其他（int/float/str/None/bool）→ 原样
2. `_load_rule_file_cached()` 返回前调用 `_freeze(data)` 冻结整棵树
3. `load_rule_file()` 直接返回缓存引用（不再 deepcopy）——因为冻结后不可变，多线程安全
4. 新增 `load_rule_file_mutable(tax_year, filename)` 函数保留 deepcopy 行为，供极少数需要修改数据的场景（如测试 fixture）

### 注意
- `MappingProxyType` 支持 `[]` 读、`.get()`、`.keys()`、`.values()`、`.items()` ——引擎纯读取无问题
- 不支持 `[]=`、`.pop()`、`.update()` ——若有调用方依赖会立即 TypeError，CI 会捕获
- JSON 序列化：FastAPI response_model 会自动转 dict，但若有 `json.dumps(rules)` 需改为 `dict(rules)` 或用自定义 encoder
- 验收：`python -m unittest discover -s tests` 全绿 + ruff clean + 新增 freeze 单测

### 影响范围
- 改：`engine/rules_loader.py`
- 新增：`tests/test_rules_loader_freeze.py`（测试冻结后读取正常、写入抛 TypeError）
- 不改：引擎计算模块（纯读取，无需适配）

---

## PR-B: 前端州下拉动态加载（50 州 + DC）

### 现状
`frontend/index.html` 的 3 个州下拉（`#tx-state`、`#se-state`、`#cr-state`）各硬编码 10 个州。引擎已覆盖 50 州 + DC（51 jurisdictions）但前端看不到 41 个。"德州 TX（暂未覆盖）""麻省 MA（暂未覆盖）"等标注已过时。

### 方案

#### 后端：新增 `GET /api/states`
```
GET /api/states?tax_year=2026
Response: {
  "tax_year": 2026,
  "states": [
    {"code": "AL", "name": "Alabama", "income_tax_type": "progressive"},
    {"code": "AK", "name": "Alaska", "income_tax_type": "none"},
    ...
  ]
}
```

实现：
- `backend/main.py` 新增 `/api/states` 路由
- 读取 `us_states.json`，遍历 `states` 字段
- 州名优先使用规则数据 `state.name`，缺失/非字符串时 fallback `STATE_NAMES` 常量；非 mapping 的 state block 做防御跳过
- 返回按 code 字母序排列
- 标注 `income_tax_type`（progressive/flat/none）供前端分组显示

#### 前端：动态加载 + 分组
1. 页面加载时 `fetch('/api/states')` 获取州列表
2. 构建 `<option>` 元素，分 3 组：
   - 有州税（progressive + flat）→ 正常显示 "Alabama AL"
   - 无州税（none）→ 显示 "Alaska AK（无州所得税）"
3. 填充到 3 个 `<select>` 元素（`#tx-state` 保留空值选项"不计州税"在最前）
4. 移除全部硬编码 `<option>` 标签
5. `#cr-state` 的 WA 条目额外标注"（长期 excise）"

### 验收
- 全部 3 个下拉显示 50 州 + DC（51 jurisdictions，有税 42 + 无税 9）
- 选任意州触发计算、结果正确
- `python -m unittest discover -s tests` 全绿 + ruff clean
- `index.html` 根文件 hash 不变（改的是 `frontend/index.html`）

---

## PR-C: M1 关闭文档（Claude 直接更新，非代码）
- `docs/feature_status.md`：更新 us_states 行为"50 州 + DC 全覆盖"、添加 C1-C4 steps
- `docs/roadmap_skills_status.md`：M1 状态从"收尾完成"→"✅ 已完成并关闭"
- `project.md`：当前进度更新、M1 正式关闭标记、下一步指向 M2
