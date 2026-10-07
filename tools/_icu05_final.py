"""端到端：直接调 summary._compute_icu05，与 icu_monthly_summary 存量记录对比。"""
import os
import sys
import time

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

from summary import _compute_icu05  # noqa: E402

# 用存量记录的 dept_code 原样喂回去
coll = sc["icu_monthly_summary"]
sample = coll.find_one({"indicator": "ICU-05-1h", "period": "2026-08",
                        "denominator": {"$gt": 0}})
DEPT_STR = sample["dept_code"]
dept_codes = [x for x in DEPT_STR.split(",") if x]
print(f"dept_codes({len(dept_codes)}) 前几个: {dept_codes[:5]}")

for hour in ("1h", "3h", "6h"):
    t0 = time.time()
    r = _compute_icu05(dept_codes, "2026-08-01", "2026-08-31", hour)
    ms = (time.time() - t0) * 1000
    stored = coll.find_one({"indicator": f"ICU-05-{hour}", "period": "2026-08",
                            "denominator": {"$gt": 0}})
    print(f"\n=== ICU-05-{hour} 2026-08 ===")
    print(f"  实算: num={r['num']} den={r['den']} val={r['val']}% "
          f"raw_den={r['raw_den']} old_shock={r['old_shock_count']} "
          f"cand={r['candidate_den']} mode={r['candidate_mode']} ({ms:.0f}ms)")
    if stored:
        print(f"  库存: num={stored['numerator']} den={stored['denominator']} "
              f"val={stored['value']}% raw_den={stored.get('raw_den')} "
              f"old_shock={stored.get('old_shock_count')} "
              f"cand={stored.get('new_shock_count')}")
    print(f"  一致: {bool(stored) and r['num'] == stored['numerator'] and r['den'] == stored['denominator']}")
