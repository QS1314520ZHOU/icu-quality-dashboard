# ICU-08 修复改动清单

**修复日期**: 2026-09-03
**修复内容**: ICU-08 分子窗口交集化 + 配置收拢 + 闰年修正

---

## 改动文件清单

### 1. icu-quality-backend/db.py

| 行号 | 函数/位置 | 改动说明 |
|------|-----------|----------|
| 53-73 | `_month_window()` | **新增**：统计窗口交集化工具函数，返回 `[max(月初,入科), min(月末,出科)]` |
| 785-792 | `get_ards_denominator()` | 注释修正：`P/F ≤150` → `P/F <150`，docstring 修正"±N分钟"→"向前回溯N分钟" |
| 944-945 | `get_ards_prone_numerator()` | **签名变更**：新增 `start_date, end_date` 参数 |
| 989-997 | `get_ards_prone_numerator()` | **核心修复**：分子窗口从 `admit~discharge` 改为 `_month_window(pat, start_dt, end_dt)`，移除 `dt.now()` |
| 1165 | `get_icu08_data()` | 调用点同步：`get_ards_prone_numerator(den_patients, dept_codes, start_date, end_date)` |
| 1168-1172 | `get_icu08_data()` | **新增**：分子>分母时截断并 warning |
| 1054 | `get_icu08_data()` | **新增**：函数入口日志 `logger.info("[ICU-08] window=...")` |
| 2325-2332 | `get_icu09_data()` | 分子时间校验改用 `_month_window()` |
| 2380-2386 | `get_icu09_data()` | score 源时间校验改用 `_month_window()` |
| 2521-2528 | `get_icu10_data()` | bedside 源时间校验改用 `_month_window()` |
| 2560-2566 | `get_icu10_data()` | score 源时间校验改用 `_month_window()` |

### 2. icu-quality-backend/config/indicator_windows.py（新增）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ARDS_PF_OP` | `"lt"` | P/F 阈值比较符 |
| `ARDS_PRONE_AFTER_PF` | `True` | 俯卧位是否必须晚于血气 |
| `ARDS_PAIR_LOOKBACK_MIN` | `60` | 配对回溯窗口(分钟) |
| `ARDS_PAIR_BIDIRECTIONAL` | `False` | 配对是否双向 |
| `WINDOW_CLAMP_STRICT` | `True` | 开发期 now() 自检 |

### 3. icu-quality-backend/main.py

| 行号 | 改动说明 |
|------|----------|
| 14 | 新增 `import calendar` |
| 101 | 新增 `CACHE_VERSION = 2`（缓存版本号） |
| 248-253 | `_read_detail_cache()` 查询条件加 `cache_version: CACHE_VERSION` |
| 262-285 | `_write_detail_cache()` 写入 `cache_version: CACHE_VERSION` |
| 502 | `_live_summary_row()` 闰年修正：`else 28` → `calendar.monthrange()` |
| 641 | `_compute_dashboard_row()` 闰年修正 |
| 1766-1770 | `_month_end_day()` 简化为 `calendar.monthrange()` |
| 418 | 文案统一：`OI≤150` → `P/F<150` |

### 4. icu-quality-dashboard/src/config/indicators.js

| 行号 | 改动说明 |
|------|----------|
| 92 | 文案统一：`OI≤150` → `P/F<150` |

### 5. 新增文件

| 文件 | 说明 |
|------|------|
| `tools/out/icu08_before_snapshot.csv` | 改造前快照（30行，12个月） |
| `tools/out/icu08_before_after.md` | 前后对照报告 + 给质控办的说明 |
| `icu-quality-backend/config/indicator_windows.py` | 指标窗口配置 |
| `icu-quality-backend/config/__init__.py` | 包初始化 |
