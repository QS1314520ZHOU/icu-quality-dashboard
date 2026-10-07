"""k1=None 的患者: bGATemp 里到底有没有乳酸? 是窗口问题还是mrn关联问题?"""
import os
import sys
from datetime import timedelta

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client, get_bundle_data_v2  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

d = get_bundle_data_v2(["3439", "2927"], "2026-08-01", "2026-08-31")
for p in d.get("den_patients", []):
    v3 = p.get("v3") or {}
    if v3.get("k1") is not None:
        continue
    t0, mrn = p.get("t0"), str(p.get("mrn") or "")
    cnt_all = cnt_win = 0
    first_t = last_t = None
    if mrn and t0:
        for doc in sc.bGATemp.find({"mrn": mrn,
                                    "bedsides": {"$elemMatch": {"code": "param_bg_Lac",
                                                               "valid": "valid"}}},
                                   {"bedsides": 1}):
            for bs in doc.get("bedsides", []):
                if bs.get("fVal") is None or not bs.get("time"):
                    continue
                cnt_all += 1
                tt = bs["time"]
                first_t = tt if first_t is None or tt < first_t else first_t
                last_t = tt if last_t is None or tt > last_t else last_t
                if t0 - timedelta(hours=2) <= tt <= t0 + timedelta(hours=6):
                    cnt_win += 1
    print(f"pid={p.get('_id')} mrn={mrn!r} t0={t0} "
          f"| bGA乳酸总条数={cnt_all} 窗口[T0-2h,T0+6h]内={cnt_win} "
          f"首条={first_t} 末条={last_t}")
