# Codex Prompt: PR-A deepcopy 热路径优化

> 先读：`/AGENTS.md`（铁律）→ `/ARCHITECTURE.md` → `docs/m1_closure_design.md` PR-A 节

## 任务

消除 `engine/rules_loader.py` 的 deepcopy 热路径瓶颈。

## 具体要求

### 1. 新增 `_freeze(obj)` 函数（`engine/rules_loader.py`）

```python
import types

def _freeze(obj):
    """Recursively freeze a JSON-deserialized object tree into immutable types."""
    if isinstance(obj, dict):
        return types.MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(item) for item in obj)
    return obj  # int, float, str, None, bool are already immutable
```

### 2. 修改 `_load_rule_file_cached()`

在 `return data` 前，改为 `return _freeze(data)`。缓存的对象现在是不可变的。

### 3. 修改 `load_rule_file()`

移除 `deepcopy` 调用，直接返回缓存引用：

```python
def load_rule_file(tax_year: int, filename: str) -> ...:
    """Load a JSON rule file (immutable, safe to share across threads)."""
    return _load_rule_file_cached(tax_year, filename)
```

### 4. 新增 `load_rule_file_mutable()`

保留可变副本行为供测试/极少数场景。因为缓存数据已是 `MappingProxyType`/`tuple`（`deepcopy()` 对 `MappingProxyType` 会 TypeError），需递归解冻：

```python
def _mutable_copy(obj: Any) -> Any:
    """Recursively thaw frozen data back into mutable dict/list."""
    if isinstance(obj, Mapping):
        return {key: _mutable_copy(value) for key, value in obj.items()}
    if isinstance(obj, tuple):
        return [_mutable_copy(item) for item in obj]
    return obj

def load_rule_file_mutable(tax_year: int, filename: str) -> dict[str, Any]:
    """Load a JSON rule file and return a mutable deep copy."""
    return _mutable_copy(_load_rule_file_cached(tax_year, filename))
```

### 5. 新增测试 `tests/test_rules_loader_freeze.py`

- `test_frozen_read_access`：加载规则后能正常 `[]`、`.get()`、`.keys()` 读取
- `test_frozen_write_raises`：对返回对象做 `[]=` 或 `.pop()` 抛 `TypeError`
- `test_mutable_copy_works`：`load_rule_file_mutable()` 返回可修改的 dict
- `test_load_rule_file_returns_same_object`：连续两次 `load_rule_file()` 返回同一个对象引用（`is` 判断）

### 6. 适配检查

- 搜索 `engine/` 和 `backend/` 中所有调用 `load_rule_file` 的地方
- 确认无写入操作（`[]=`、`.pop()`、`.update()`、`del`）
- 如有写入，改为先 `dict()` 浅拷贝或调用 `load_rule_file_mutable()`
- 搜索 `json.dumps` 对 rules 数据的使用——`MappingProxyType` 不可直接 `json.dumps`，需要自定义 encoder 或转 dict

## 验收门禁

```powershell
# 全部通过才可开 PR
python -m unittest discover -s tests
python -m ruff check engine backend tests
git diff --check
```

## Commit 格式

```
perf(engine): freeze rule data to eliminate deepcopy on hot path

Replace deepcopy with recursive freeze (MappingProxyType + tuple)
in rules_loader. Cached rule data is now immutable and returned
directly, eliminating per-request copy overhead.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
