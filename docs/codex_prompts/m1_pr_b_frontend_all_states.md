# Codex Prompt: PR-B 前端州下拉 10→51 动态加载

> 先读：`/AGENTS.md`（铁律）→ `/ARCHITECTURE.md` → `docs/m1_closure_design.md` PR-B 节

## 任务

前端 3 个州下拉（`#tx-state`、`#se-state`、`#cr-state`）当前硬编码 10 个州，引擎已覆盖 51 州。改为从后端 API 动态加载全部州。

## 后端：新增 `/api/states` 端点

### 文件：`backend/main.py`

新增路由：

```python
@app.get("/api/states")
def get_available_states(tax_year: int = DEFAULT_TAX_YEAR):
    """Return all available states for the given tax year."""
    from engine.rules_loader import load_rule_file
    states_data = load_rule_file(tax_year, "us_states.json")
    
    STATE_NAMES = {
        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
        "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
        "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
        "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
        "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
        "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
        "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
        "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
        "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
        "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
        "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
        "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
        "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    }
    
    result = []
    for code, state in sorted(states_data.get("states", {}).items()):
        result.append({
            "code": code,
            "name": STATE_NAMES.get(code, code),
            "income_tax_type": state.get("income_tax_type", "unknown"),
        })
    
    return {"tax_year": tax_year, "states": result}
```

**注意**：`STATE_NAMES` 应抽成模块级常量（在文件顶部或 `backend/constants.py`），不要每次请求重建。

### 新增测试

`tests/test_api_states.py`：
- `test_states_endpoint_returns_51`：GET `/api/states` 返回 51 个州
- `test_states_have_required_fields`：每个州有 code, name, income_tax_type
- `test_states_sorted_by_code`：结果按 code 字母序

## 前端：动态加载

### 文件：`frontend/index.html`

#### 1. 移除硬编码 `<option>`

三个 `<select>` 改为只保留占位：

```html
<!-- #tx-state -->
<select class="sel" id="tx-state" onchange="calcTax()">
  <option value="">不计州税</option>
  <!-- 动态填充 -->
</select>

<!-- #se-state -->
<select class="sel" id="se-state" onchange="calcSE()">
  <option value="">选择州</option>
  <!-- 动态填充 -->
</select>

<!-- #cr-state -->
<select class="sel" id="cr-state" onchange="calcCrypto()">
  <option value="">（不计州税）</option>
  <!-- 动态填充 -->
</select>
```

#### 2. 新增 `populateStateDropdowns()` 函数

```javascript
async function populateStateDropdowns() {
  try {
    const resp = await fetch(API_BASE_URL + '/api/states');
    if (!resp.ok) return;
    const data = await resp.json();
    const states = data.states || [];
    
    // 分组：有税 vs 无税
    const withTax = states.filter(s => s.income_tax_type !== 'none');
    const noTax = states.filter(s => s.income_tax_type === 'none');
    
    function buildOptions(selectId, includeEmpty) {
      const sel = document.getElementById(selectId);
      // 保留第一个 option（空值占位）
      while (sel.options.length > 1) sel.remove(1);
      
      // 有州税的州
      withTax.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.code;
        opt.textContent = s.name + ' ' + s.code;
        sel.appendChild(opt);
      });
      
      // 分隔线
      if (noTax.length) {
        const sep = document.createElement('option');
        sep.disabled = true;
        sep.textContent = '── 无州所得税 ──';
        sel.appendChild(sep);
      }
      
      // 无州税的州
      noTax.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.code;
        let label = s.name + ' ' + s.code + '（无州所得税）';
        // WA 特殊标注（crypto 下拉用）
        if (s.code === 'WA' && selectId === 'cr-state') {
          label = s.name + ' ' + s.code + '（长期 excise）';
        }
        opt.textContent = label;
        sel.appendChild(opt);
      });
    }
    
    buildOptions('tx-state');
    buildOptions('se-state');
    buildOptions('cr-state');
  } catch (e) {
    console.warn('Failed to load states:', e);
    // 降级：下拉保持空或显示错误提示
  }
}
```

#### 3. 在页面初始化时调用

在现有的 `DOMContentLoaded` 或 `init()` 函数末尾加入：

```javascript
populateStateDropdowns();
```

## 验收门禁

```powershell
python -m unittest discover -s tests
python -m ruff check engine backend tests
git diff --check
# 根 index.html hash 不变（改的是 frontend/index.html）
```

## 验收场景

1. 打开 http://127.0.0.1:3000/index.html → 税务计算 → 州下拉显示 51 个州
2. 选 AL（Alabama）→ 州税正确计算
3. 选 TX（Texas）→ 州税 = $0（无州税）
4. 选 MA（Massachusetts）→ MA 4% surtax 对 $1M+ 收入生效
5. 3 个下拉全部正常（#tx-state, #se-state, #cr-state）

## Commit 格式

```
feat(frontend+api): dynamic state dropdown with all 51 jurisdictions

Add GET /api/states endpoint returning all available states from rule
data. Frontend now dynamically populates all three state dropdowns on
page load instead of hardcoding 10 states.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
