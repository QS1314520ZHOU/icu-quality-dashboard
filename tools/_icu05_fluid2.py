"""窗口内全部大容量液体记录 vs 关键词命中情况 —— 判断 FLUID_INSUFFICIENT 是真低还是漏统计。"""
import os
import sys
from datetime import timedelta

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client, get_bundle_data_v2  # noqa: E402
from scoring.bundle_engine import CRYSTALLOID_KEYWORDS, COLLOID_KEYWORDS, set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})
KW = list(CRYSTALLOID_KEYWORDS | COLLOID_KEYWORDS)

d = get_bundle_data_v2(["3439", "2927"], "2026-08-01", "2026-08-31")
targets = [p for p in d.get("den_patients", [])
           if (p.get("v3") or {}).get("k1") is True and (p.get("v3") or {}).get("k2") is True]

TOTAL = {"hit": 0.0, "miss_big": 0.0}
for p in targets:
    t0, sc_pid = p.get("t0"), p.get("sc_pid") or p.get("_id")
    v3 = p.get("v3") or {}
    print("=" * 100)
    print(f"pid={p.get('_id')}  系统统计算 fluid_3h={v3.get('fluid_3h_ml')}")
    for label, endh in (("3h", 3), ("6h", 6)):
        hit = miss = 0.0
        rows = []
        for dd in sc.drugExe.find({"pid": sc_pid,
                                   "startTime": {"$gte": t0, "$lte": t0 + timedelta(hours=endh)}},
                                  {"drugList.name": 1, "drugList.liquidAmount": 1, "startTime": 1}):
            st = dd.get("startTime")
            for dl in (dd.get("drugList") or []):
                nm = str(dl.get("name") or "")
                amt = dl.get("liquidAmount")
                try:
                    a = float(amt)
                except (TypeError, ValueError):
                    continue
                if a < 50:          # 只看 ≥50ml 的，排除微量溶媒
                    continue
                matched = any(k in nm for k in KW)
                if matched:
                    hit += a
                else:
                    miss += a
                rows.append((matched, st, a, nm[:42]))
        print(f"  [{label}窗口 ≥50ml记录] 命中={hit:.0f}ml 未命中={miss:.0f}ml")
        for matched, st, a, nm in sorted(rows, key=lambda x: x[1]):
            mark = "HIT " if matched else "MISS"
            print(f"    {mark} {st:%m-%d %H:%M} {a:7.0f}ml  {nm}")
        if label == "3h":
            TOTAL["hit"] += hit
            TOTAL["miss_big"] += miss

print("=" * 100)
print(f"6例合计 3h 窗口: 关键词命中 {TOTAL['hit']:.0f}ml | 未命中的大容量液体 {TOTAL['miss_big']:.0f}ml")
