import os
import sys

os.chdir(r"D:\icu-quality-dashboard\icu-quality-backend")
sys.path.insert(0, ".")

from db import get_client

dc = get_client("DataCenter")["DataCenter"]
sc = get_client("SmartCare")["SmartCare"]

z = dc.VI_ICU_ZYBR.find_one({"pid": "1744377"})
print("ZYBR keys:", sorted(z.keys()))
for k in ("hisPid", "his_pid", "patientId", "visitId", "recordId", "mrn", "pid"):
    if k in z:
        print(f"  {k} = {z[k]!r}")

for k in ("hisPid", "his_pid", "patientId"):
    v = z.get(k)
    if v:
        n = dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": str(v)}, limit=1)
        print(f"  EXAM_ITEM[hisPid={v}] -> hit={n}")

# EXAM_ITEM 的 hisPid 是否等于 SmartCare patient.hisPid
p = sc.patient.find_one({"hisPid": "1672592"}, {"mrn": 1, "hisPid": 1, "_id": 0})
print("SC patient.hisPid=1672592 ->", p)

cnt = sc.patient.count_documents({"hisPid": {"$exists": True, "$nin": ["", None]}})
print("SC patient 有 hisPid 的数量:", cnt)

# 关键: 该患者 SC patient 的 hisPid 是什么
row = sc.patient.find_one({"mrn": "2062385"}, {"mrn": 1, "hisPid": 1, "_id": 0})
print("SC patient[mrn=2062385] ->", row)
if row and row.get("hisPid"):
    n = dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": str(row["hisPid"])}, limit=1)
    n_lac = dc.VI_ICU_EXAM_ITEM.count_documents(
        {"hisPid": str(row["hisPid"]), "itemName": "LAC"}, limit=5)
    print(f"  用 hisPid={row['hisPid']} 查检验: 全部hit={n} LAC样本={n_lac}")
