# -*- coding: utf-8 -*-
"""清理旧版本明细缓存 + 预热 ICU-07 明细（只算 ICU-07，不跑全指标）。"""
import sys, io, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as m
from db import get_client, BED_DB_NAMES

DEPT = sys.argv[1] if len(sys.argv) > 1 else "3439"
CODE = "ICU-07"

coll = m._get_detail_cache_collection()
if coll is not None:
    n = coll.delete_many({"cache_version": {"$ne": m.CACHE_VERSION}}).deleted_count
    print(f"清理旧版本明细缓存: {n} 条 (当前 v{m.CACHE_VERSION})")

db = get_client(BED_DB_NAMES[0])[BED_DB_NAMES[0]]
periods = sorted({r["period"] for r in db.icu_monthly_summary.find(
    {"indicator": CODE, "dept_code": DEPT}, {"period": 1, "_id": 0})})
hist = [p for p in periods if m._is_historical_period(p)]
print(f"预热 {CODE} / {DEPT}: {len(hist)} 个历史期 (只算 ICU-07)")

t0 = time.time()
stats = m.rebuild_detail_cache([DEPT], hist, indicators=[CODE], icu_unit=DEPT)
print(f"耗时 {time.time() - t0:.1f}s  success={stats['success']} failed={stats['failed']}")
for e in stats["errors"]:
    print("  ERROR:", e)

if coll is not None:
    docs = list(coll.find({"code": CODE, "dept_code": DEPT},
                          {"period": 1, "part": 1, "count": 1,
                           "cache_version": 1, "_id": 0}))
    print(f"ICU-07/{DEPT} 缓存条目 {len(docs)} 个, 全部 v{m.CACHE_VERSION}: "
          f"{all(d.get('cache_version') == m.CACHE_VERSION for d in docs)}")
    for d in sorted(docs, key=lambda x: (x.get("period", ""), x.get("part", ""))):
        print("   ", d["period"], d["part"], d["count"], "v" + str(d["cache_version"]))
sys.exit(1 if stats["failed"] else 0)
