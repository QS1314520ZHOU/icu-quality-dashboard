# -*- coding: utf-8 -*-
"""重建 icu_monthly_summary 中的 ICU-07 汇总行（口径修复后必跑）。

按 dept_code 分组逐组重建（每个 dept_code 单独调用一次 rebuild_summary），
并清理误生成的「逗号拼接」垃圾行。

用法:
    python scripts/icu07_rebuild.py            # 全部 dept_code × 全部周期
    python scripts/icu07_rebuild.py 3439       # 只重建指定 dept_code
"""
import sys, io, time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_client, BED_DB_NAMES
from summary import rebuild_summary, SUMMARY_COLLECTION

for db_name in BED_DB_NAMES:
    try:
        db = get_client(db_name)[db_name]
        coll = db[SUMMARY_COLLECTION]
        break
    except Exception:
        continue
else:
    print("无可用数据库")
    sys.exit(1)

rows = list(coll.find({"indicator": "ICU-07"},
                      {"dept_code": 1, "period": 1, "_id": 0}))
print(f"现有 ICU-07 汇总行: {len(rows)}")

# ---- 1. 清理垃圾行：dept_code 是把多个分组用逗号拼在一起生成的 ----
# 合法的 dept_code 要么是单个科室号，要么是配置文件里那一整串常量（本身就含逗号）。
LEGACY_ALL_KEY = ("配置时认真选择正确的科室,3439,2927,2915,3442,3414,3412,"
                  "2964,2953,3409,3487,3452")
# 上一次误跑把分组键 list 直接传给了 rebuild_summary，生成了这个拼接键
BAD_KEY = "2927,3439," + LEGACY_ALL_KEY
garbage = [r for r in rows if r.get("dept_code") == BAD_KEY]
if garbage:
    print(f"\n删除误生成的拼接行 {len(garbage)} 条:")
    for r in garbage[:5]:
        print(f"  {r['dept_code']}  {r['period']}")
    if len(garbage) > 5:
        print(f"  ... 另外 {len(garbage) - 5} 条")
    coll.delete_many({"indicator": "ICU-07",
                      "dept_code": {"$in": [r["dept_code"] for r in garbage]}})

# ---- 2. 决定重建范围 ----
group_keys = sorted({r.get("dept_code") for r in rows
                     if r.get("dept_code") != BAD_KEY})
if len(sys.argv) > 1 and sys.argv[1] != "all":
    group_keys = [k for k in group_keys if k == sys.argv[1]]
    if not group_keys:
        print(f"未找到 dept_code={sys.argv[1]} 的 ICU-07 行")
        sys.exit(1)

all_periods = sorted({r["period"] for r in rows})

# ---- 3. 逐组重建 ----
for key in group_keys:
    periods = sorted({r["period"] for r in rows
                      if r.get("dept_code") == key}) or all_periods
    # dept_code 是 ",".join(dept_codes) 的结果，反向 split 才能还原原始科室列表；
    # 否则整个含逗号的 key 会被当成一个"科室号"查不到任何在科记录 → 0/0。
    dept_list = key.split(",")
    print(f"\n=== 重建 dept_code = {key}  ({len(periods)} 个周期, {len(dept_list)} 个科室) ===")
    t0 = time.time()
    stats = rebuild_summary(dept_list, periods, indicators=["ICU-07"])
    print(f"耗时 {time.time() - t0:.1f}s  total={stats['total']} "
          f"success={stats['success']} failed={stats['failed']}")
    for e in stats["errors"]:
        print("  ERROR:", e)

# ---- 4. 回读校验 ----
print("\n重建后的 ICU-07 行:")
bad = 0
for r in sorted(coll.find({"indicator": "ICU-07"},
                          {"dept_code": 1, "period": 1, "numerator": 1,
                           "denominator": 1, "value": 1, "_id": 0}),
                key=lambda x: (str(x.get("dept_code")), str(x.get("period")))):
    n, d = r.get("numerator"), r.get("denominator")
    live = round(n / d * 100, 1) if d else None
    if live != r.get("value"):
        bad += 1
    key = r.get("dept_code")
    label = "3439" if key == "3439" else (key[:24] + "…" if len(str(key)) > 24 else key)
    flag = "  ★" if key == "3439" and r.get("period") == "2026-09" else ""
    print(f"  {label:<28} {r.get('period')}  {n}/{d} = {r.get('value')}%{flag}")
print(f"\n校验: 存储值与 n/d 不一致的行 = {bad}")
