"""冒烟: query_detail ICU-05 分母 → 验证 reason/reason_codes/step/人话desc。"""
import os
import sys

os.chdir(r"D:\icu-quality-dashboard\icu-quality-backend")
sys.path.insert(0, ".")

from db import get_client  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

import main  # noqa: E402

# 分母明细
items = main.query_detail("ICU-05-6h", "2026-08", "denominator", "all")
print(f"分母 items: {len(items)}")
for p in items[:6]:
    v3 = p.get("v3") or {}
    print(f"  pid={p.get('patient_id')} finish={v3.get('finish')} "
          f"step=({v3.get('step1')},{v3.get('step2')},{v3.get('step3')}) "
          f"reason={v3.get('reason')!r} codes={v3.get('reason_codes')}")

# reason_summary 逻辑（endpoint 里的同款）
from collections import Counter
done = failed = uncertain = 0
fc, uc = Counter(), Counter()
for p in items:
    v3 = p.get("v3") or {}
    codes = v3.get("reason_codes") or []
    fin = v3.get("finish")
    if fin is True:
        done += 1
        continue
    primary = (codes[0] if codes else None) or v3.get("reason") or ""
    if fin is False:
        failed += 1
        if primary:
            fc[primary] += 1
    else:
        uncertain += 1
        if primary:
            uc[primary] += 1
print(f"\nreason_summary: done={done} failed={failed} uncertain={uncertain}")
print("failed:", dict(fc))
print("uncertain:", dict(uc))

# 分子
nums = main.query_detail("ICU-05-6h", "2026-08", "numerator", "all")
print(f"\n分子 items: {len(nums)}")
for p in nums[:3]:
    v3 = p.get("v3") or {}
    print(f"  pid={p.get('patient_id')} finish={v3.get('finish')} step=({v3.get('step1')},{v3.get('step2')},{v3.get('step3')})")
