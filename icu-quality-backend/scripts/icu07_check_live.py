# -*- coding: utf-8 -*-
"""快速核对：只算 ICU-07 的实时值 vs icu_monthly_summary 存储值。"""
import sys, io, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calendar
from db import get_client, BED_DB_NAMES
import summary as sm

DEPT = sys.argv[1] if len(sys.argv) > 1 else "3439"
db = get_client(BED_DB_NAMES[0])[BED_DB_NAMES[0]]
periods = sorted({r["period"] for r in db.icu_monthly_summary.find(
    {"indicator": "ICU-07", "dept_code": DEPT}, {"period": 1, "_id": 0})})

computer = sm.INDICATOR_COMPUTERS["ICU-07"]
bad = 0
t0 = time.time()
for p in periods:
    y, m = p.split("-")
    start = f"{y}-{m}-01"
    end = f"{y}-{m}-{calendar.monthrange(int(y), int(m))[1]:02d}"
    live = computer([DEPT], start, end)
    st = db.icu_monthly_summary.find_one(
        {"indicator": "ICU-07", "dept_code": DEPT, "period": p})
    ln, ld, lv = live.get("num"), live.get("den"), live.get("val")
    sn, sd, sv = (st or {}).get("numerator"), (st or {}).get("denominator"), (st or {}).get("value")
    same = (ln, ld, lv) == (sn, sd, sv)
    bad += 0 if same else 1
    star = "  ★" if p == "2026-09" else ""
    print(f"  {'✔' if same else '✘'} {p}  实时 {ln}/{ld}={lv}%   存储 {sn}/{sd}={sv}%{star}")
print(f"\n{len(periods)} 期, 不一致 {bad} 期, 耗时 {time.time()-t0:.1f}s")
sys.exit(1 if bad else 0)
