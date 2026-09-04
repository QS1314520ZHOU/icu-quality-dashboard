#!/usr/bin/env python3
"""D1-D6 SOFA-2 移植前最后数据探查"""
import sys, os, io, json, csv, re, random
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from statistics import median

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from db import (iter_bed_dbs, get_datacenter_db,
                O2_ROUTE_INVASIVE, O2_ROUTE_NON_INVASIVE, _parse_o2_routes)

OUT = os.path.join(os.path.dirname(__file__), "out")

def sc():
    for _, db in iter_bed_dbs(): return db
def dc():
    try: return get_datacenter_db()
    except: return None

db = sc()
dcenter = dc()

def fmt_dt(v):
    if v is None: return ""
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:25]

def percentile(vals, p):
    if not vals: return None
    s = sorted(vals); n = len(s)
    k = (n - 1) * p / 100
    f = int(k); c = f + 1
    if c >= n: return s[-1]
    return s[f] + (k - f) * (s[c] - s[f])

# ============================================================
# D1. param_XiYangTuJing 全量取值普查
# ============================================================
print("=" * 80)
print("D1. param_XiYangTuJing 全量取值普查")
print("=" * 80)

# 用 aggregate group 做全量
pipeline = [
    {"$match": {"code": "param_XiYangTuJing", "valid": True}},
    {"$group": {"_id": "$strVal", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]
results = list(db.bedside.aggregate(pipeline, allowDiskUse=True))
total = sum(r["count"] for r in results)
print(f"\n总记录数: {total}")
print(f"\n{'取值':40s} {'计数':>8s} {'占比':>8s}")
print("-" * 60)
for r in results:
    val = r["_id"] if r["_id"] is not None else "<None>"
    cnt = r["count"]
    pct = cnt / total * 100
    print(f"{val:40s} {cnt:8d} {pct:7.1f}%")

# 确认6个值是否在
print(f"\n--- 确认6个目标值 ---")
target_vals = {"管氧", "切氧", "管文", "切文", "管高", "切高"}
found_vals = {r["_id"] for r in results if r["_id"]}
for tv in sorted(target_vals):
    cnt = next((r["count"] for r in results if r["_id"] == tv), 0)
    status = f"存在, {cnt}条" if cnt > 0 else "不存在"
    print(f"  {tv}: {status}")

# 空值/空字符串
none_cnt = next((r["count"] for r in results if r["_id"] is None), 0)
empty_cnt = next((r["count"] for r in results if r["_id"] == ""), 0)
print(f"\n  None/null: {none_cnt}条")
print(f"  空字符串'': {empty_cnt}条")

# 不在 INVASIVE_ROUTES 九元组里的"其他"取值
print(f"\n--- 不在 O2_ROUTE_INVASIVE 九元组的取值 ---")
print(f"  INVASIVE_ROUTES = {O2_ROUTE_INVASIVE}")
for r in results:
    val = r["_id"]
    if val and val not in O2_ROUTE_INVASIVE and val not in O2_ROUTE_NON_INVASIVE:
        print(f"  其他: '{val}' ({r['count']}条)")

# 多值拼接检查
print(f"\n--- 多值拼接检查 ---")
multi_sep_samples = []
for doc in db.bedside.find(
    {"code": "param_XiYangTuJing", "valid": True, "strVal": {"$regex": "[,/、+|]"}},
    {"strVal": 1}
).limit(20):
    sv = doc.get("strVal", "")
    if sv and re.search(r"[,/、+|]", sv):
        multi_sep_samples.append(sv)

if multi_sep_samples:
    print(f"  含分隔符的记录: 至少{len(multi_sep_samples)}条")
    print(f"  样例(前5):")
    for s in multi_sep_samples[:5]:
        parsed = _parse_o2_routes(s)
        print(f"    原始='{s}' → 解析={parsed}")
else:
    print(f"  未发现含分隔符的记录(抽样20条)")

# _parse_o2_routes 完整实现
print(f"\n--- _parse_o2_routes 完整实现 ---")
import inspect
print(inspect.getsource(_parse_o2_routes))

# ============================================================
# D2. 录入间隔 + 覆盖率
# ============================================================
print("\n" + "=" * 80)
print("D2. param_XiYangTuJing 与 param_vent_peep 录入间隔")
print("=" * 80)

for code_label, code in [("param_XiYangTuJing", "param_XiYangTuJing"),
                          ("param_vent_peep", "param_vent_peep")]:
    cnt = db.bedside.count_documents({"code": code, "valid": True})
    print(f"\n--- {code_label} ---")
    print(f"  总条数: {cnt}")

    if cnt == 0:
        continue

    # 涉及患者日数 & 平均每患者日条数
    pid_day_counter = Counter()
    pid_gaps = defaultdict(list)
    prev = {}
    for doc in db.bedside.find(
        {"code": code, "valid": True},
        {"pid": 1, "time": 1}
    ).sort([("pid", 1), ("time", 1)]).max_time_ms(60000):
        pid = doc.get("pid", "")
        t = doc.get("time")
        if not pid or not t:
            continue
        day = t.strftime("%Y-%m-%d")
        pid_day_counter[f"{pid}|{day}"] += 1
        if pid in prev and prev[pid]:
            gap_h = (t - prev[pid]).total_seconds() / 3600
            if 0 < gap_h < 48:  # 过滤异常大间隔
                pid_gaps[pid].append(gap_h)
        prev[pid] = t

    patient_days = len(pid_day_counter)
    total_records = sum(pid_day_counter.values())
    avg_per_day = total_records / patient_days if patient_days else 0
    print(f"  涉及患者日数: {patient_days}")
    print(f"  平均每患者日条数: {avg_per_day:.2f}")

    # 间隔分布
    all_gaps = []
    for gaps in pid_gaps.values():
        all_gaps.extend(gaps)
    if all_gaps:
        print(f"  间隔统计(相邻两条差h): n={len(all_gaps)}, "
              f"中位数={median(all_gaps):.2f}, "
              f"P75={percentile(all_gaps, 75):.2f}, "
              f"P90={percentile(all_gaps, 90):.2f}, "
              f"P95={percentile(all_gaps, 95):.2f}")

# 覆盖率分析
print(f"\n--- (a) param_XiYangTuJing 对 P/F ratio 的覆盖率 ---")

# 抽 500 条 bGATemp 的 P/F ratio
pf_samples = []
for doc in db.bGATemp.find(
    {"bedsides.code": "param_bg_P/Fratio"},
    {"eventExe.pid": 1, "eventExe.startTime": 1, "bedsides": 1}
).max_time_ms(60000):
    evt = doc.get("eventExe", {})
    pid = evt.get("pid", "")
    t = evt.get("startTime")
    if pid and t:
        pf_samples.append({"pid": pid, "time": t})
    if len(pf_samples) >= 500:
        break

print(f"  P/F 样本数: {len(pf_samples)}")

# 覆盖率统计
windows = [60, 480, 1440, None]  # 60min, 8h, 24h, LOCF(不限)
window_labels = ["60分钟", "8小时", "24小时", "LOCF(不限)"]
coverage_counts = [0] * 4

for pf in pf_samples:
    pid = pf["pid"]
    pf_time = pf["time"]
    for i, w in enumerate(windows):
        if w is not None:
            win_start = pf_time - timedelta(minutes=w)
            doc = db.bedside.find_one(
                {"pid": pid, "code": "param_XiYangTuJing", "valid": True,
                 "time": {"$gte": win_start, "$lte": pf_time}},
                {"_id": 1}, sort=[("time", -1)])
        else:
            doc = db.bedside.find_one(
                {"pid": pid, "code": "param_XiYangTuJing", "valid": True,
                 "time": {"$lte": pf_time}},
                {"_id": 1}, sort=[("time", -1)])
        if doc:
            coverage_counts[i] += 1

print(f"\n  {'窗口':15s} {'命中':>6s} {'覆盖率':>8s}")
print(f"  {'-'*35}")
for label, cnt in zip(window_labels, coverage_counts):
    pct = cnt / len(pf_samples) * 100 if pf_samples else 0
    print(f"  {label:15s} {cnt:6d} {pct:7.1f}%")

# (b) param_vent_peep 覆盖率
print(f"\n--- (b) param_vent_peep 对 P/F ratio 的覆盖率 ---")
peep_coverage = [0] * 4
for pf in pf_samples:
    pid = pf["pid"]
    pf_time = pf["time"]
    for i, w in enumerate(windows):
        if w is not None:
            win_start = pf_time - timedelta(minutes=w)
            doc = db.bedside.find_one(
                {"pid": pid, "code": "param_vent_peep", "valid": True,
                 "time": {"$gte": win_start, "$lte": pf_time}},
                {"_id": 1}, sort=[("time", -1)])
        else:
            doc = db.bedside.find_one(
                {"pid": pid, "code": "param_vent_peep", "valid": True,
                 "time": {"$lte": pf_time}},
                {"_id": 1}, sort=[("time", -1)])
        if doc:
            peep_coverage[i] += 1

print(f"\n  {'窗口':15s} {'命中':>6s} {'覆盖率':>8s}")
print(f"  {'-'*35}")
for label, cnt in zip(window_labels, peep_coverage):
    pct = cnt / len(pf_samples) * 100 if pf_samples else 0
    print(f"  {label:15s} {cnt:6d} {pct:7.1f}%")

# 估算漏掉的患者数
if len(pf_samples) > 0:
    missed_60 = pf_samples.__len__() - coverage_counts[0]
    missed_locf = pf_samples.__len__() - coverage_counts[3]
    print(f"\n  60min窗口漏掉: {missed_60}条({missed_60/len(pf_samples)*100:.1f}%)")
    print(f"  LOCF仍漏掉: {missed_locf}条({missed_locf/len(pf_samples)*100:.1f}%)")
    if missed_60 > missed_locf:
        print(f"  ⚠️ 60min窗口比LOCF多漏 {missed_60 - missed_locf} 条,说明有患者在P/F时刻前60min内无呼吸支持记录")

# ============================================================
# D3. ECMO 记录结构
# ============================================================
print("\n" + "=" * 80)
print("D3. ECMO 记录结构")
print("=" * 80)

# distinct 名称
ecmo_names = db.tubeExe.distinct("name", {"$or": [
    {"type": {"$regex": "ECMO", "$options": "i"}},
    {"strVal": {"$regex": "ECMO", "$options": "i"}},
    {"name": {"$regex": "ECMO", "$options": "i"}},
]})
print(f"  tubeExe ECMO distinct名称({len(ecmo_names)}):")
for n in sorted(ecmo_names):
    cnt = db.tubeExe.count_documents({"name": n, "$or": [
        {"type": {"$regex": "ECMO", "$options": "i"}},
        {"name": {"$regex": "ECMO", "$options": "i"}}
    ]})
    print(f"    '{n}': {cnt}")

# 完整字段
ecmo_sample = list(db.tubeExe.find(
    {"$or": [
        {"type": {"$regex": "ECMO", "$options": "i"}},
        {"name": {"$regex": "ECMO", "$options": "i"}}
    ]}
).limit(3))
print(f"\n  样例记录({len(ecmo_sample)}条):")
for i, doc in enumerate(ecmo_sample):
    print(f"\n  --- 记录 {i+1} ---")
    print(f"  {json.dumps({k: str(v)[:50] for k, v in doc.items()}, ensure_ascii=False, default=str)}")

# VV vs VA 区分
print(f"\n  VV/VA区分检查:")
for doc in db.tubeExe.find(
    {"$or": [
        {"type": {"$regex": "ECMO", "$options": "i"}},
        {"name": {"$regex": "ECMO", "$options": "i"}}
    ]},
    {"name": 1, "type": 1, "strVal": 1, "notes": 1}
).limit(20):
    name = doc.get("name", "")
    typ = doc.get("type", "")
    sv = doc.get("strVal", "")
    notes = doc.get("notes", "")
    vv_va = "VV" if ("VV" in name or "VV" in str(sv) or "VV" in str(notes)) else \
            "VA" if ("VA" in name or "VA" in str(sv) or "VA" in str(notes)) else "未知"
    print(f"    name='{name}', type='{typ}', strVal='{sv}', notes='{str(notes)[:50]}' → {vv_va}")

# ============================================================
# D4. 尿量细粒度
# ============================================================
print("\n" + "=" * 80)
print("D4. 尿量细粒度")
print("=" * 80)

# bedside 里含"尿"的 code
print("  bedside 含'尿'的code:")
尿_codes = db.bedside.distinct("code", {"code": {"$regex": "尿|niao|urine", "$options": "i"}, "valid": True})
for code in sorted(尿_codes):
    cnt = db.bedside.count_documents({"code": code, "valid": True})
    print(f"    {code}: {cnt}")

# nurseRecords 集合
print("\n  nurseRecords 集合探测:")
if "nurseRecord" in db.list_collection_names():
    sample = list(db.nurseRecord.find().limit(1))
    if sample:
        print(f"    nurseRecord 字段: {sorted(sample[0].keys())}")
    nr_cnt = db.nurseRecord.count_documents({})
    print(f"    nurseRecord 总数: {nr_cnt}")

# 看 nurseRecordDuty
if "nurseRecordDuty" in db.list_collection_names():
    sample = list(db.nurseRecordDuty.find().limit(1))
    if sample:
        all_f = set()
        for s in sample: all_f.update(s.keys())
        print(f"    nurseRecordDuty 字段: {sorted(all_f)}")
    nrd_cnt = db.nurseRecordDuty.count_documents({})
    print(f"    nurseRecordDuty 总数: {nrd_cnt}")
    # 找出入量
    io_docs = list(db.nurseRecordDuty.find(
        {"$or": [{"items.name": {"$regex": "尿|出|入"}}, {"name": {"$regex": "尿|出|入"}}]}
    ).limit(5))
    for doc in io_docs:
        print(f"    出入量样例: {json.dumps({k: str(v)[:60] for k, v in doc.items()}, ensure_ascii=False, default=str)[:300]}")

# 24h尿量为0的患者日
print("\n  24h尿量为0的患者日:")
zero_urine = 0
for doc in db.bedside.find(
    {"code": "param_niaoLiang", "valid": True, "strVal": "0"},
    {"pid": 1, "time": 1}
).limit(500):
    zero_urine += 1
print(f"  strVal='0'的记录数(采样500): {zero_urine}")

# ============================================================
# D5. 体重清洗
# ============================================================
print("\n" + "=" * 80)
print("D5. 体重清洗")
print("=" * 80)

weight_vals = []
weight_raw = []
for doc in db.patient.find({"weight": {"$exists": True, "$ne": None}}, {"weight": 1, "name": 1}).limit(6000):
    w = doc.get("weight")
    if w is not None:
        try:
            fv = float(w)
            weight_vals.append(fv)
            weight_raw.append({"name": doc.get("name", ""), "raw": str(w), "float": fv})
        except:
            pass

total_pat = db.patient.count_documents({})
print(f"  总患者: {total_pat}, weight可解析: {len(weight_vals)}")

# 分布
buckets = Counter()
for v in weight_vals:
    if v < 20: buckets["<20"] += 1
    elif v <= 300: buckets["20-300"] += 1
    elif v <= 500: buckets["300-500"] += 1
    else: buckets[">500"] += 1

print(f"\n  体重分布:")
for k in ["<20", "20-300", "300-500", ">500"]:
    cnt = buckets.get(k, 0)
    pct = cnt / len(weight_vals) * 100 if weight_vals else 0
    print(f"    {k:10s}: {cnt:6d} ({pct:.1f}%)")

# <20 的例子
print(f"\n  <20kg 的例子:")
low = [r for r in weight_raw if r["float"] < 20]
for r in low[:5]:
    print(f"    name={r['name']}, raw='{r['raw']}', float={r['float']}")

# >300 的例子
print(f"\n  >300kg 的例子:")
high = [r for r in weight_raw if r["float"] > 300]
for r in high[:5]:
    print(f"    name={r['name']}, raw='{r['raw']}', float={r['float']}")

# 清洗后可用比例
clean_count = sum(1 for v in weight_vals if 20 <= v <= 300)
print(f"\n  清洗后(20-300kg)可用: {clean_count}/{len(weight_vals)} ({clean_count/len(weight_vals)*100:.1f}%)")

# ============================================================
# D6. 去甲肾上腺素盐型 + speed
# ============================================================
print("\n" + "=" * 80)
print("D6. 去甲肾上腺素盐型 + speed")
print("=" * 80)

# 药品字典
print("  configDrug 去甲肾上腺素相关:")
ne_drugs = list(db.configDrug.find({"name": {"$regex": "去甲"}}, {"name": 1, "code": 1, "spec": 1, "unit": 1}))
for d in ne_drugs:
    print(f"    code={d.get('code','')}, name={d.get('name','')}, spec='{d.get('spec','')}', unit={d.get('unit','')}")

# drugExe 里的规格
print("\n  drugExe 去甲肾上腺素规格(从drugList.name提取):")
ne_specs = Counter()
for doc in db.drugExe.find(
    {"drugList.name": {"$regex": "去甲肾上腺素"}},
    {"drugList.name": 1, "drugList.dose": 1, "drugList.unit": 1}
).limit(2000):
    for dl in doc.get("drugList", []):
        name = str(dl.get("name", ""))
        if "去甲" in name:
            ne_specs[name] += 1
            break
print(f"  全量药品名({len(ne_specs)}种):")
for name, cnt in ne_specs.most_common(20):
    print(f"    {name:55s} {cnt:5d}")

# speed 覆盖率
print("\n  speed字段覆盖率:")
vaso_codes = [d.get("code") for d in db.configDrug.find({"classification": "血管活性"}, {"code": 1}) if d.get("code")]
speed_total = 0; speed_nonempty = 0; speed_unit_counter = Counter()
speed_vals = []
for doc in db.drugExe.find(
    {"drugList.code": {"$in": vaso_codes[:50]}},
    {"hisStartTime.speed": 1, "hisStartTime.speedUnit": 1}
).limit(2000):
    speed_total += 1
    hs = doc.get("hisStartTime") or {}
    sp = hs.get("speed")
    su = hs.get("speedUnit")
    if sp is not None:
        try:
            sv = float(sp)
            if sv > 0:
                speed_nonempty += 1
                speed_vals.append(sv)
                if su: speed_unit_counter[str(su)] += 1
        except:
            pass

print(f"  总血管活性执行记录: {speed_total}")
print(f"  speed非空(>0): {speed_nonempty}/{speed_total} ({speed_nonempty/speed_total*100:.1f}%)")
print(f"  speedUnit分布: {dict(speed_unit_counter.most_common(5)) if speed_unit_counter else '全部为空'}")
if speed_vals:
    s = sorted(speed_vals); n = len(s)
    print(f"  speed数值分布: n={n}, P5={s[int(n*.05)]:.1f}, P50={s[int(n*.50)]:.1f}, P95={s[int(n*.95)]:.1f}, max={s[-1]:.1f}")
    # 判断单位
    if s[int(n*.50)] < 200:
        print(f"  推断: speed单位为 ml/h (中位数{s[int(n*.50)]:.1f}符合临床输注速率)")
    else:
        print(f"  推断: speed单位可能不是 ml/h (中位数{s[int(n*.50)]:.1f}偏大)")

print("\n" + "=" * 80)
print("D1-D6 探查完成")
