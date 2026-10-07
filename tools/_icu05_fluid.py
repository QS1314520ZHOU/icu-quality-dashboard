"""核查液体统计：窗口内晶体/胶体记录的 liquidAmount 覆盖率。"""
import os
import sys
from datetime import timedelta

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_bundle_data_v2, get_client  # noqa: E402
from scoring.bundle_engine import CRYSTALLOID_KEYWORDS, COLLOID_KEYWORDS, set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})
KW = list(CRYSTALLOID_KEYWORDS | COLLOID_KEYWORDS)
print("液体关键词:", KW)

d = get_bundle_data_v2(["3439"], "2026-08-01", "2026-08-31")
targets = [p for p in d.get("den_patients", [])
           if (p.get("v3") or {}).get("k1") is True and (p.get("v3") or {}).get("k2") is True]

for p in targets:
    t0 = p.get("t0")
    if not t0:
        continue
    v3 = p.get("v3") or {}
    docs = list(sc.drugExe.find(
        {"pid": p.get("sc_pid") or p.get("_id"),
         "startTime": {"$gte": t0, "$lte": t0 + timedelta(hours=6)}},
        {"drugList.name": 1, "drugList.liquidAmount": 1, "drugList.unit": 1, "startTime": 1}))
    matched, sum3, sum6, no_amt = [], 0.0, 0.0, 0
    for dd in docs:
        st = dd.get("startTime")
        hrs = (st - t0).total_seconds() / 3600
        for dl in (dd.get("drugList") or []):
            nm = str(dl.get("name") or "")
            if not any(k in nm for k in KW):
                continue
            amt = dl.get("liquidAmount")
            matched.append((st, nm[:34], amt, dl.get("unit")))
            if amt in (None, "", 0):
                no_amt += 1
                continue
            try:
                a = float(amt)
            except (TypeError, ValueError):
                no_amt += 1
                continue
            if hrs <= 3:
                sum3 += a
            if hrs <= 6:
                sum6 += a
    print("=" * 90)
    print(f"pid={p.get('_id')} t0={t0:%m-%d %H:%M} | 系统算的 fluid_3h={v3.get('fluid_3h_ml')}")
    print(f"  窗口内匹配液体记录: {len(matched)} 条, 其中无liquidAmount: {no_amt}")
    for st, nm, amt, unit in matched[:10]:
        print(f"    {st:%m-%d %H:%M} {nm} amount={amt!r} unit={unit}")
    print(f"  重算: 3h累计={sum3:.0f}ml  6h累计={sum6:.0f}ml")
