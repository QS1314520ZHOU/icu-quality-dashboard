"""用正确 hisPid(ZYBR.pid) 查6例 k1=None 患者窗口内检验LAC。"""
import os
import sys
from datetime import timedelta

os.chdir(r"D:\icu-quality-dashboard\icu-quality-backend")
sys.path.insert(0, ".")

from db import get_client, get_bundle_data_v2  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
dc = get_client("DataCenter")["DataCenter"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

d = get_bundle_data_v2(["3439", "2927"], "2026-08-01", "2026-08-31")
for p in d.get("den_patients", []):
    v3 = p.get("v3") or {}
    if v3.get("k1") is not None:
        continue
    t0, pid = p.get("t0"), str(p.get("_id"))
    # 正确key: ZYBR.pid = _id
    n_win = list(dc.VI_ICU_EXAM_ITEM.find(
        {"hisPid": pid, "itemName": "LAC",
         "authTime": {"$gte": t0 - timedelta(hours=2), "$lte": t0 + timedelta(hours=6)}},
        {"authTime": 1, "result": 1, "_id": 0}).limit(5))
    # 全窗口外有多少
    n_any = dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": pid, "itemName": "LAC"})
    print(f"pid={pid} T0={t0} | 检验LAC总数={n_any} | 窗口内={len(n_win)} | "
          f"{[(x['authTime'].strftime('%m-%d %H:%M'), x['result']) for x in n_win]}")
