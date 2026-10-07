"""验证 EXAM_ITEM.hisPid 与 mrn 是否同一ID域。"""
import os
import sys

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client  # noqa: E402

dc = get_client("DataCenter")["DataCenter"]

# 1) 这几个 mrn 在 EXAM_ITEM 里有无任何记录（不限项目）
for mrn in ("2062385", "2062061", "2054704"):
    n_all = dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": mrn})
    n_lac = dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": mrn, "itemName": "LAC"})
    print(f"hisPid={mrn}: 全部检验={n_all} LAC={n_lac}")

# 2) hisPid 长什么样
samples = list(dc.VI_ICU_EXAM_ITEM.find({}, {"hisPid": 1, "_id": 0}).limit(5))
print("hisPid样例:", [s.get("hisPid") for s in samples])

# 3) 是否存在 pid 与 hisPid 不同的情况（同文档对照 ZYBR pid）
zybr_pid = "1744377"
z = dc.VI_ICU_ZYBR.find_one({"pid": zybr_pid}, {"mrn": 1, "pid": 1})
print("ZYBR pid=1744377 →", z)
if z and z.get("mrn"):
    n = dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": str(z["mrn"])})
    print(f"  用 mrn={z['mrn']} 查 EXAM_ITEM: {n} 条")

# 4) 用 mrn 当 hisPid 全库有多少命中（抽查10个ZYBR患者的mrn）
import random
rows = list(dc.VI_ICU_ZYBR.find({"admitTime": {"$gte": __import__('datetime').datetime(2026, 8, 1),
                                                "$lte": __import__('datetime').datetime(2026, 8, 31)}},
                                {"mrn": 1}).limit(50))
hit = sum(1 for r in rows if r.get("mrn") and
          dc.VI_ICU_EXAM_ITEM.count_documents({"hisPid": str(r["mrn"])}, limit=1) > 0)
print(f"抽查 {len(rows)} 个8月患者: mrn 能在 EXAM_ITEM 命中的 = {hit}")
