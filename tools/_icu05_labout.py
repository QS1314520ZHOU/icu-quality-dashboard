"""k1=None 患者: 检验系统 VI_ICU_EXAM_ITEM 里窗口内有没有 LAC? K1只查血气是否漏检。"""
import os
import sys
from datetime import timedelta

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

# 先摸清 LAC 文档结构
sample = dc.VI_ICU_EXAM_ITEM.find_one({"itemName": {"$regex": "^LAC|乳酸"}},
                                      {"_id": 0})
if not sample:
    sample = dc.VI_ICU_EXAM_ITEM.find_one({"$or": [{"itemCode": "LAC"}, {"code": "LAC"}]}, {"_id": 0})
print("LAC 文档字段:", sorted(sample.keys()) if sample else "未找到")
if sample:
    print("样例:", {k: sample[k] for k in list(sample)[:12]})

# 字段名探测
item_field = "itemName" if sample and "itemName" in sample else ("itemCode" if sample and "itemCode" in sample else None)
pid_field = "hisPid" if sample and "hisPid" in sample else ("pid" if sample and "pid" in sample else None)
time_field = next((f for f in ("authTime", "collectTime", "reportTime", "orderTime", "time")
                   if sample and f in sample), None)
val_field = next((f for f in ("result", "value", "itemValue", "val")
                  if sample and f in sample), None)
print(f"使用字段: item={item_field} pid={pid_field} time={time_field} value={val_field}")

d = get_bundle_data_v2(["3439", "2927"], "2026-08-01", "2026-08-31")
for p in d.get("den_patients", []):
    v3 = p.get("v3") or {}
    if v3.get("k1") is not None:
        continue
    t0, mrn = p.get("t0"), str(p.get("mrn") or "")
    if not (t0 and mrn and item_field and pid_field and time_field):
        print(f"pid={p.get('_id')} 跳过(字段缺失)")
        continue
    q = {pid_field: mrn, time_field: {"$gte": t0 - timedelta(hours=2),
                                      "$lte": t0 + timedelta(hours=6)}}
    if item_field == "itemName":
        q["itemName"] = {"$regex": "^LAC|乳酸"}
    elif item_field == "itemCode":
        q["itemCode"] = "LAC"
    n = dc.VI_ICU_EXAM_ITEM.count_documents(q)
    ex = list(dc.VI_ICU_EXAM_ITEM.find(q, {"_id": 0}).limit(3))
    # 窗口外最近一条
    outside = dc.VI_ICU_EXAM_ITEM.find_one(
        {**{k: v for k, v in q.items() if k != time_field},
         time_field: {"$lt": t0 - timedelta(hours=2)}},
        {time_field: 1}, sort=[(time_field, -1)])
    print(f"pid={p.get('_id')} T0={t0} | 窗口内检验LAC={n}条"
          f" | 窗口外最近={outside.get(time_field) if outside else None}"
          f" | 样例值={[ (e.get(time_field), e.get(val_field)) for e in ex ]}")

