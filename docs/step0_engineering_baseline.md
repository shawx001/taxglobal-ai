# Step 0 Engineering Baseline

日期：2026-06-02

## 本步目标

建立工程基线：把当前单文件原型放进可持续开发的项目结构，同时保留根目录原型不动，避免在正式拆分前破坏现有演示。

## 本步完成内容

- 初始化 Git 仓库。
- 新建基础目录：
  - `frontend/`
  - `backend/`
  - `engine/`
  - `data/`
  - `tests/`
  - `docs/`
- 复制根目录 `index.html` 到 `frontend/index.html`。
- 新增 `README.md`，说明项目定位、MVP 边界、架构方向和知识库真相源原则。
- 新增 `.gitignore`。
- 新增 `.gitattributes`，固定文本文件和 HTML 的 LF 行尾，降低 Windows/macOS/Linux 跨环境行尾漂移风险。
- 为暂时为空的工程目录新增 `.gitkeep`。
- 更新开发计划，加入：
  - 工程质量底线。
  - 税务规则数据来源原则。
  - 知识库真相源原则。
  - 大厂工程规范。
- 更新 MVP 打勾清单中 Step 0 的完成状态。

## 验收标准

- Git 仓库初始化成功。
- 默认分支改为 `main`。
- 第一个工程基线 commit 已创建。
- 根目录原型仍然存在。
- `frontend/index.html` 与根目录 `index.html` 内容一致。
- 基础目录存在且职责清晰。
- README 能解释当前项目状态、MVP 范围和下一步。
- README 写明每次修改必须验收，以及双份 prototype 的 hash 校验规则。
- 本步不引入业务逻辑变更。

## 实际验收结果

已执行以下校验：

```powershell
git status --short
Get-FileHash -Algorithm SHA256 -LiteralPath index.html, frontend\index.html
Get-ChildItem -Force | Select-Object Name,Length,Mode
Get-Content -Path README.md -TotalCount 80
Select-String -Path README.md -Pattern "Every change must be verified|Prototype Sync Rule|Get-FileHash"
git diff --check
```

结果：

- `git status --short` 正常显示当前未跟踪文件。
- `index.html` 和 `frontend/index.html` 的 SHA256 hash 一致，说明原型副本没有被改坏。
- 基础目录和新增文件均存在。
- README 可读取。
- README 已包含修改验收纪律和 prototype 同步规则。
- `git diff --check` 未发现 whitespace/error marker 问题。

## 修改文件

- `README.md`
- `.gitignore`
- `.gitattributes`
- `frontend/index.html`
- `TaxGlobal_AI_目标驱动开发计划.md`
- `TaxGlobal_AI_MVP执行打勾清单.md`
- `backend/.gitkeep`
- `engine/.gitkeep`
- `data/.gitkeep`
- `tests/.gitkeep`
- `docs/.gitkeep`
- `docs/step0_engineering_baseline.md`

## Claude Review 重点

- 项目结构是否足够清晰，是否有过度设计。
- README 是否准确表达 U.S.-first MVP 边界。
- “数据库/知识库是真相源”的原则是否足够明确。
- 每次修改必须测试的准则是否写清楚。
- 根目录原型和 `frontend/` 过渡方式是否合理。

## 已知限制

- 初始 commit 已创建，本文件作为 Step 0 收尾记录一起进入基线。
- `backend/`、`engine/`、`data/`、`tests/` 仍是占位目录。
- 本步没有业务代码，因此没有运行单元测试；采用文件 hash、目录结构、README 可读性作为结构变更验收。
