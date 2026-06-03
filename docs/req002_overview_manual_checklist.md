# REQ-002 合并计税总览手动核对清单

## 启动

```powershell
& "C:\Users\shawx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\run_overview_dev.py
```

打开 `http://127.0.0.1:5173/index.html` 后进入「税务计算」→「普通收入」。每次场景先清空不相关输入，州留空代表不计州税。

## 表单映射

| 表单 id | 引擎参数 |
|---|---|
| `tx-filing` | `filing_status` |
| `tx-state` | `state_code` |
| `tx-income` | `w2_wages` |
| `tx-se-profit` | `net_self_employment_profit` |
| `tx-other-income` | `other_ordinary_income` |
| `tx-ltcg` | `long_term_capital_gain` |
| `tx-stcg` | `short_term_capital_gain` |
| `tx-feie-income` | `foreign_earned_income` |
| `tx-days-abroad` | `days_abroad` |
| `tx-401k` | `retirement_contributions` |
| `tx-se-health` | `se_health_insurance` |
| `tx-itemamt` | `deduction` |
| `tx-qbi-w2` | `qbi_w2_wages` |
| `tx-qbi-ubia` | `qbi_ubia` |
| `tx-sstb` | `is_sstb` |
| `tx-magi` | `modified_agi` |

## 黄金场景

| 场景 | 输入 | 期望 |
|---|---|---|
| A 工资+长期利得 | `single`; `tx-income=200000`; `tx-ltcg=50000`; 州留空; 其它收入桶清空或填 0 | 总税 `$60,465.20`; federal `$37,247.00`; LTCG `$7,500.00`; NIIT `$1,900.00`; payroll `$13,818.20` |
| B FEIE | `single`; `tx-feie-income=200000`; `tx-days-abroad=330`; 州留空; 其它收入桶清空或填 0 | FEIE 豁免 `$130,000.00`; 总税 `$13,200.00` |
| C 全组合 | `single`; `tx-se-profit=60000`; `tx-ltcg=40000`; `tx-feie-income=100000`; `tx-days-abroad=330`; 州留空 | QBI `$8,152.23`; 总税 `$19,875.71` |
| D 自雇+州 | `single`; `tx-se-profit=100000`; `tx-state=CA`; 其它收入桶清空或填 0 | 总税 `$27,311.11`; CA 州税 `$4,550.96` |

## 防御性输入

- 空输入不进入 payload；显式输入 `0` 会进入 payload。
- 金额负数会在前端夹到 `0`，避免无意义 422。
- `days_abroad` 非整数或大于 366 时，应显示后端错误，不显示假总额。
- 未覆盖州应显示「州税未覆盖」和 reason，总税仍显示引擎已计算部分。
