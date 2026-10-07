"""分母漏斗: ZYBR脓毒症住院 → 24h过滤 → 进入den → K1∧K2。只看2026-08两科。"""
import os
import sys
from datetime import datetime

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client, get_bundle_data_v2  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
dc = get_client("DataCenter")["DataCenter"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

DEPTS = ["3439", "2927"]
KW = "感染性休克|脓毒性休克|脓毒症休克|脓毒血症|败血症|脓毒症"

rows = list(dc.VI_ICU_ZYBR.find(
    {"deptCode": {"$in": DEPTS}, "diagnose": {"$regex": KW, "$options": "i"},
     "admitTime": {"$gte": datetime(2026, 8, 1), "$lte": datetime(2026, 8, 31, 23, 59, 59)}},
    {"pid": 1, "admitTime": 1, "inPatientTime": 1, "diagnose": 1}))
print(f"ZYBR 2026-08 两科脓毒症住院: {len(rows)} 人")

# 24h 过滤
pass24, fail24 = [], []
for r in rows:
    inp, adm = r.get("inPatientTime"), r.get("admitTime")
    if isinstance(inp, datetime) and isinstance(adm, datetime):
        if (adm - inp).total_seconds() / 3600 <= 24:
            pass24.append(r)
        else:
            fail24.append(r)
    else:
        fail24.append(r)  # 字段缺失也排除
print(f"  入院→入ICU ≤24h: {len(pass24)} 通过 / {len(fail24)} 被过滤")

d = get_bundle_data_v2(DEPTS, "2026-08-01", "2026-08-31")
den = d.get("den_patients", [])
den_ids = {str(p.get("_id")) for p in den}
p24_ids = {str(r.get("pid")) for r in pass24}
print(f"  进入 den(候选): {len(den_ids)} 人")
print(f"  过了24h但没进den(候选引擎判not_candidate/其他): {len(p24_ids - den_ids)} 人")
for pid in list(p24_ids - den_ids)[:8]:
    print(f"    pid={pid}")

# den 里 K1 状态分布
from collections import Counter
c = Counter()
for p in den:
    v3 = p.get("v3") or {}
    k1 = v3.get("k1")
    if k1 is True:
        c["k1=True(乳酸≥2)"] += 1
    elif k1 is False:
        c["k1=False(乳酸<2)"] += 1
    else:
        c["k1=None(乳酸缺失)"] += 1
    k2 = v3.get("k2")
    c[f"k2={'T' if k2 is True else 'F' if k2 is False else 'None'}"] += 1
print(f"  den 内判定分布: {dict(c)}")
