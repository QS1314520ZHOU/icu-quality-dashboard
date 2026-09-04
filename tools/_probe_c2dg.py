#!/usr/bin/env python3
"""C2 + D + E + G 探测"""
import sys, os, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from collections import Counter
from db import get_datacenter_db, iter_bed_dbs, EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES

def sc():
    for _, db in iter_bed_dbs(): return db
def topn(c, n=10, label=""):
    t = sum(c.values())
    print(f"  [{label}] total={t}")
    for v,cnt in c.most_common(n):
        print(f"    {v!r:55s} {cnt:6d} ({cnt/t*100:.1f}%)" if t else "")
def fmt_dt(v):
    if v is None: return "None"
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:25]

database = sc()
dc = get_datacenter_db()

# ============================================================
# C2. 病原学送检
# ============================================================
print("=== C2. 病原学送检 ===")
order_counter = Counter()
for doc in dc["VI_ICU_ZYYZ"].find(
    {"yaoType": {"$in": LAB_ORDER_TYPES}, "orderName": {"$regex": "培养|涂片|药敏"}},
    {"orderName": 1}
).limit(300):
    name = doc.get("orderName", "")[:50]
    order_counter[name] += 1
topn(order_counter, 30, "培养/药敏医嘱")

# ============================================================
# D1. VI_ZYYZ vs VI_ICU_ZYYZ
# ============================================================
print("\n=== D1. VI_ZYYZ vs VI_ICU_ZYYZ ===")
for coll_name in ["VI_ZYYZ", "VI_ICU_ZYYZ"]:
    if coll_name in dc.list_collection_names():
        cnt = dc[coll_name].count_documents({}, limit=1)
        sample = list(dc[coll_name].find().limit(1))
        fields = sorted(sample[0].keys()) if sample else []
        print(f"  {coll_name}: exists, fields({len(fields)})={fields}")
    else:
        print(f"  {coll_name}: NOT EXISTS")

# ============================================================
# D2. VI_ICU_ZYYZ 完整字段 + reviewTime
# ============================================================
print("\n=== D2. VI_ICU_ZYYZ 字段清单 ===")
sample = list(dc["VI_ICU_ZYYZ"].find().limit(1))
if sample:
    all_fields = sorted(sample[0].keys())
    print(f"  完整字段({len(all_fields)}): {all_fields}")
    rt_count = dc["VI_ICU_ZYYZ"].count_documents({"reviewTime": {"$exists": True, "$ne": None}})
    total_zyyz = dc["VI_ICU_ZYYZ"].count_documents({})
    print(f"  reviewTime 非空: {rt_count}/{total_zyyz} ({rt_count/total_zyyz*100:.1f}%)" if total_zyyz else "")

    # 时间字段非空率
    for f in ["orderTime","reviewTime","planTime","stopTime","cancelTime","exeTime","startTime"]:
        cnt = dc["VI_ICU_ZYYZ"].count_documents({f: {"$exists": True, "$ne": None}})
        print(f"  {f} 非空: {cnt}/{total_zyyz} ({cnt/total_zyyz*100:.1f}%)" if total_zyyz else "")

    # 样例
    for s in sample[:2]:
        print(f"  样例: {json.dumps({k: str(v)[:30] for k,v in s.items()}, ensure_ascii=False)}")

# ============================================================
# D3. 血培养
# ============================================================
print("\n=== D3. 血培养 ===")
bc_count = dc["VI_ICU_ZYYZ"].count_documents(
    {"orderName": {"$regex": "血培养"}, "status": {"$in": EXECUTED_ORDER_STATUSES}})
print(f"  血培养(已执行): {bc_count}")

# ICU-06 可复用函数
print("  ICU-06 复用: db.CULTURE_KEYWORDS_FULL, db._keyword_regex()")

# ============================================================
# D4. 抗生素识别
# ============================================================
print("\n=== D4. 抗生素识别 ===")
abx_codes = [d.get("code") for d in database.configDrug.find(
    {"classification": "抗生素"}, {"code": 1})]
print(f"  configDrug classification='抗生素': {len(abx_codes)} codes")

# 抗生素执行记录时间字段
if abx_codes:
    abx_sample = list(database.drugExe.find(
        {"drugList.code": {"$in": abx_codes[:50]}},
        {"startTime": 1, "exeTime": 1, "hisStartTime": 1, "status": 1, "orderTime": 1}
    ).limit(50))
    print(f"  抗生素执行记录: {len(abx_sample)}")
    tf = {"startTime": 0, "exeTime": 0, "hisStartTime.exeTime": 0, "orderTime": 0}
    for doc in abx_sample:
        if doc.get("startTime"): tf["startTime"] += 1
        if doc.get("exeTime"): tf["exeTime"] += 1
        hs = doc.get("hisStartTime")
        if isinstance(hs, dict) and hs.get("exeTime"): tf["hisStartTime.exeTime"] += 1
        if doc.get("orderTime"): tf["orderTime"] += 1
    for f, cnt in tf.items():
        print(f"    {f} 非空: {cnt}/{len(abx_sample)}")

# ============================================================
# D5. 窗口内多条记录统计
# ============================================================
print("\n=== D5. 窗口内多条记录统计(20例) ===")
if abx_codes:
    pids_with_abx = []
    for doc in database.drugExe.find(
        {"drugList.code": {"$in": abx_codes[:50]}, "status": "finished"},
        {"pid": 1, "startTime": 1}
    ).sort("startTime", -1).limit(200):
        pid = doc.get("pid")
        if pid and pid not in pids_with_abx:
            pids_with_abx.append(pid)
        if len(pids_with_abx) >= 20: break

    multi_count = 0
    time_gaps = []
    for pid in pids_with_abx:
        docs = list(database.drugExe.find(
            {"pid": pid, "drugList.code": {"$in": abx_codes[:50]}, "status": "finished"},
            {"startTime": 1}
        ).sort("startTime", 1))
        if len(docs) > 1:
            multi_count += 1
            times = [d["startTime"] for d in docs if d.get("startTime")]
            if len(times) >= 2:
                gap_h = (times[-1] - times[0]).total_seconds() / 3600
                time_gaps.append(gap_h)
    print(f"  20例中有多条抗生素: {multi_count}/20")
    if time_gaps:
        s = sorted(time_gaps)
        n = len(s)
        print(f"  首剂-最晚剂差(h): P50={s[int(n*.5)]:.1f}, P95={s[int(n*.95)]:.1f}, max={s[-1]:.1f}")

# ============================================================
# E1. 剂量字段
# ============================================================
print("\n=== E1. drugExe 剂量字段 ===")
dose_units = Counter()
dose_ml_count = 0
dose_total = 0
for doc in database.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(500):
    for dl in doc.get("drugList", []):
        unit = str(dl.get("unit", "")).strip()
        dose = dl.get("dose")
        if unit:
            dose_units[unit] += 1
            dose_total += 1
        if unit == "ml" and dose is not None:
            dose_ml_count += 1
topn(dose_units, 15, "drugList.unit 分布")
print(f"  可直接累加ml: {dose_ml_count}/{dose_total}")

# ============================================================
# E2. 液体分类
# ============================================================
print("\n=== E2. 液体分类 ===")
CRYSTALLOID_KW = ["氯化钠", "葡萄糖", "林格", "乳酸钠", "碳酸氢钠"]
COLLOID_KW = ["羟乙基淀粉", "白蛋白", "血浆", "明胶", "右旋糖酐"]
crystal_re = "|".join(CRYSTALLOID_KW)
colloid_re = "|".join(COLLOID_KW)

counts = {"晶体": 0, "胶体": 0, "其他ml": 0}
total_fluid = 0
for doc in database.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(500):
    for dl in doc.get("drugList", []):
        name = str(dl.get("name", ""))
        unit = str(dl.get("unit", ""))
        dose = dl.get("dose")
        if unit == "ml" and dose is not None:
            total_fluid += 1
            if re.search(crystal_re, name):
                counts["晶体"] += 1
            elif re.search(colloid_re, name):
                counts["胶体"] += 1
            else:
                counts["其他ml"] += 1
print(f"  液体分类(ml): {counts}, 总计={total_fluid}")

# ============================================================
# G1. infectionShockV2
# ============================================================
print("\n=== G1. infectionShockV2 ===")
total_shock = database.infectionShockV2.count_documents({})
print(f"  总文档数: {total_shock}")

# 样例结构
for doc in database.infectionShockV2.find().limit(3):
    did = doc.get("diseaseId", "")
    g1 = doc.get("group1H") or {}
    g3 = doc.get("group3H") or {}
    g6 = doc.get("group6H") or {}
    print(f"\n  diseaseId={did}")
    print(f"    group1H: {json.dumps(g1, ensure_ascii=False, default=str)[:400]}")
    print(f"    group3H: {json.dumps(g3, ensure_ascii=False, default=str)[:400]}")
    print(f"    group6H: {json.dumps(g6, ensure_ascii=False, default=str)[:400]}")

# 逐字段填写率
ALL_FIELDS = set()
for doc in database.infectionShockV2.find():
    for gk in ["group1H", "group3H", "group6H"]:
        g = doc.get(gk) or {}
        for k in g: ALL_FIELDS.add(f"{gk}.{k}")
print(f"\n  所有子字段: {sorted(ALL_FIELDS)}")
for field in sorted(ALL_FIELDS):
    gk, sk = field.split(".", 1)
    cnt = database.infectionShockV2.count_documents({f"{gk}.{sk}": {"$exists": True, "$ne": None}})
    pct = cnt / total_shock * 100 if total_shock else 0
    print(f"    {field}: {cnt}/{total_shock} ({pct:.0f}%)")

print("\n"+"="*80)
print("D~G 探测完成")
