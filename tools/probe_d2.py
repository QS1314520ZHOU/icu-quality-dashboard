#!/usr/bin/env python3
"""D2-D6 (D1 已完成)"""
import sys, os, io, json, re, random
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from statistics import median

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from db import iter_bed_dbs, get_datacenter_db, O2_ROUTE_INVASIVE, O2_ROUTE_NON_INVASIVE

def sc():
    for _, db in iter_bed_dbs(): return db
def dc():
    try: return get_datacenter_db()
    except: return None

db = sc()

def fmt_dt(v):
    if v is None: return ""
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:25]

def percentile(vals, p):
    if not vals: return None
    s = sorted(vals); n = len(s)
    k = (n - 1) * p / 100; f = int(k); c = f + 1
    return s[-1] if c >= n else s[f] + (k - f) * (s[c] - s[f])

# ============================================================
# D2. 录入间隔 + 覆盖率
# ============================================================
print("=" * 80)
print("D2. param_XiYangTuJing 与 param_vent_peep 录入间隔 + 覆盖率")
print("=" * 80)

# 用采样方式：取20个有P/F的患者，看他们各自的XiYangTuJing/PEEP间隔
bga_pids = []
for doc in db.bGATemp.find(
    {"bedsides.code": "param_bg_P/Fratio"},
    {"eventExe.pid": 1}
).limit(200):
    pid = (doc.get("eventExe") or {}).get("pid")
    if pid and pid not in bga_pids:
        bga_pids.append(pid)
    if len(bga_pids) >= 20:
        break

print(f"  样本患者: {len(bga_pids)}")

for code_label, code in [("param_XiYangTuJing", "param_XiYangTuJing"),
                          ("param_vent_peep", "param_vent_peep")]:
    print(f"\n  --- {code_label} ---")
    cnt = db.bedside.count_documents({"code": code, "valid": True})
    print(f"  总条数: {cnt}")

    # 采样间隔
    all_gaps = []
    total_recs = 0
    for pid in bga_pids[:10]:
        docs = list(db.bedside.find(
            {"pid": pid, "code": code, "valid": True},
            {"time": 1}
        ).sort("time", 1).limit(200))
        total_recs += len(docs)
        for i in range(len(docs) - 1):
            gap_h = (docs[i+1]["time"] - docs[i]["time"]).total_seconds() / 3600
            if 0 < gap_h < 48:
                all_gaps.append(gap_h)

    if all_gaps:
        print(f"  采样记录数: {total_recs}, 间隔数: {len(all_gaps)}")
        print(f"  间隔(h): 中位数={median(all_gaps):.2f}, "
              f"P75={percentile(all_gaps, 75):.2f}, "
              f"P90={percentile(all_gaps, 90):.2f}, "
              f"P95={percentile(all_gaps, 95):.2f}")
    else:
        print(f"  ⚠️ 采样患者中无此code记录")

# 覆盖率
print(f"\n  --- 覆盖率分析 ---")
# 抽 500 条 P/F
pf_samples = []
for doc in db.bGATemp.find(
    {"bedsides.code": "param_bg_P/Fratio"},
    {"eventExe.pid": 1, "eventExe.startTime": 1}
).max_time_ms(60000):
    evt = doc.get("eventExe", {})
    pid = evt.get("pid", ""); t = evt.get("startTime")
    if pid and t:
        pf_samples.append({"pid": pid, "time": t})
    if len(pf_samples) >= 500:
        break

print(f"  P/F 样本: {len(pf_samples)}")

windows = [(60, "60min"), (480, "8h"), (1440, "24h"), (None, "LOCF")]

for code_label, code in [("XiYangTuJing", "param_XiYangTuJing"),
                          ("PEEP", "param_vent_peep")]:
    print(f"\n  {code_label} 覆盖率:")
    counts = [0] * 4
    for pf in pf_samples:
        pid = pf["pid"]; pf_time = pf["time"]
        for i, (w, _) in enumerate(windows):
            if w is not None:
                win_start = pf_time - timedelta(minutes=w)
                doc = db.bedside.find_one(
                    {"pid": pid, "code": code, "valid": True,
                     "time": {"$gte": win_start, "$lte": pf_time}},
                    {"_id": 1}, sort=[("time", -1)])
            else:
                doc = db.bedside.find_one(
                    {"pid": pid, "code": code, "valid": True,
                     "time": {"$lte": pf_time}},
                    {"_id": 1}, sort=[("time", -1)])
            if doc:
                counts[i] += 1

    print(f"    {'窗口':10s} {'命中':>6s} {'覆盖率':>8s}")
    for (_, label), cnt in zip(windows, counts):
        pct = cnt / len(pf_samples) * 100 if pf_samples else 0
        print(f"    {label:10s} {cnt:6d} {pct:7.1f}%")

    missed_60 = len(pf_samples) - counts[0]
    missed_locf = len(pf_samples) - counts[3]
    print(f"    60min漏掉: {missed_60}条, LOCF仍漏: {missed_locf}条")

# ============================================================
# D3. ECMO 记录结构
# ============================================================
print("\n" + "=" * 80)
print("D3. ECMO 记录结构")
print("=" * 80)

ecmo_names = db.tubeExe.distinct("name", {"$or": [
    {"type": {"$regex": "ECMO", "$options": "i"}},
    {"name": {"$regex": "ECMO", "$options": "i"}},
    {"strVal": {"$regex": "ECMO", "$options": "i"}},
]})
print(f"  distinct名称({len(ecmo_names)}): {ecmo_names}")

# VV/VA 区分
print(f"\n  VV/VA区分:")
for doc in db.tubeExe.find(
    {"$or": [
        {"type": {"$regex": "ECMO", "$options": "i"}},
        {"name": {"$regex": "ECMO", "$options": "i"}}
    ]},
    {"name": 1, "type": 1, "strVal": 1, "notes": 1, "startTime": 1, "endTime": 1,
     "createdTime": 1, "editTime": 1}
).limit(20):
    all_text = f"{doc.get('name','')} {doc.get('type','')} {doc.get('strVal','')} {doc.get('notes','')}"
    vv = "VV" if "VV" in all_text.upper() else "VA" if "VA" in all_text.upper() else "未知"
    print(f"  name='{doc.get('name','')}', type='{doc.get('type','')}', "
          f"strVal='{doc.get('strVal','')}', notes='{str(doc.get('notes',''))[:50]}' → {vv}")
    print(f"    startTime={fmt_dt(doc.get('startTime'))}, endTime={fmt_dt(doc.get('endTime'))}, "
          f"createdTime={fmt_dt(doc.get('createdTime'))}")

# 结束时间缺失率
ecmo_total = db.tubeExe.count_documents({"$or": [
    {"type": {"$regex": "ECMO", "$options": "i"}},
    {"name": {"$regex": "ECMO", "$options": "i"}}
]})
ecmo_end = db.tubeExe.count_documents({"$or": [
    {"type": {"$regex": "ECMO", "$options": "i"}},
    {"name": {"$regex": "ECMO", "$options": "i"}}
], "endTime": {"$exists": True, "$ne": None}})
print(f"\n  ECMO总记录: {ecmo_total}, endTime非空: {ecmo_end}, 缺失: {ecmo_total - ecmo_end}")

# ============================================================
# D4. 尿量细粒度
# ============================================================
print("\n" + "=" * 80)
print("D4. 尿量细粒度")
print("=" * 80)

# bedside 含"尿"的code
print("  bedside 含'尿'的code:")
尿_codes = db.bedside.distinct("code", {"code": {"$regex": "尿|niao|urine", "$options": "i"}, "valid": True})
for code in sorted(尿_codes):
    cnt = db.bedside.count_documents({"code": code, "valid": True})
    print(f"    {code}: {cnt}")

# nurseRecordDuty
print("\n  nurseRecordDuty:")
if "nurseRecordDuty" in db.list_collection_names():
    nrd_cnt = db.nurseRecordDuty.count_documents({})
    print(f"    总数: {nrd_cnt}")
    sample = list(db.nurseRecordDuty.find().limit(1))
    if sample:
        print(f"    字段: {sorted(sample[0].keys())}")
    # 出入量
    io_docs = list(db.nurseRecordDuty.find(
        {"$or": [{"items.name": {"$regex": "尿|出|入"}}, {"name": {"$regex": "尿|出|入"}}]}
    ).limit(3))
    for doc in io_docs:
        print(f"    样例: {json.dumps({k: str(v)[:60] for k, v in doc.items()}, ensure_ascii=False, default=str)[:300]}")

# 24h尿量为0
print("\n  尿量=0记录:")
zero_cnt = db.bedside.count_documents({"code": "param_niaoLiang", "valid": True, "strVal": "0"})
print(f"  strVal='0': {zero_cnt}")

# 尿量采样间隔更精确
print("\n  param_niaoLiang 采样间隔(10例患者):")
pids = []
for doc in db.bedside.find({"code": "param_niaoLiang", "valid": True}, {"pid": 1}).limit(200):
    pid = doc.get("pid")
    if pid and pid not in pids: pids.append(pid)
    if len(pids) >= 10: break

all_gaps = []
for pid in pids:
    docs = list(db.bedside.find(
        {"pid": pid, "code": "param_niaoLiang", "valid": True},
        {"time": 1, "strVal": 1}
    ).sort("time", 1).limit(100))
    if len(docs) >= 2:
        for i in range(len(docs) - 1):
            gap_h = (docs[i+1]["time"] - docs[i]["time"]).total_seconds() / 3600
            if 0 < gap_h < 24:
                all_gaps.append(gap_h)

if all_gaps:
    s = sorted(all_gaps); n = len(s)
    print(f"  间隔数: {n}, 中位数={median(s):.2f}h, P75={percentile(s,75):.2f}h, "
          f"P90={percentile(s,90):.2f}h, P95={percentile(s,95):.2f}h")
    # 分桶
    buckets = Counter()
    for g in all_gaps:
        if g <= 1: buckets["≤1h"] += 1
        elif g <= 2: buckets["1-2h"] += 1
        elif g <= 4: buckets["2-4h"] += 1
        elif g <= 8: buckets["4-8h"] += 1
        elif g <= 12: buckets["8-12h"] += 1
        else: buckets[">12h"] += 1
    print(f"  分桶: {dict(sorted(buckets.items()))}")

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
        except: pass

total_pat = db.patient.count_documents({})
print(f"  总患者: {total_pat}, weight可解析: {len(weight_vals)}")

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

print(f"\n  <20kg 的例子:")
for r in [r for r in weight_raw if r["float"] < 20][:5]:
    print(f"    name={r['name']}, raw='{r['raw']}', float={r['float']}")

print(f"\n  >300kg 的例子:")
for r in [r for r in weight_raw if r["float"] > 300][:5]:
    print(f"    name={r['name']}, raw='{r['raw']}', float={r['float']}")

clean = sum(1 for v in weight_vals if 20 <= v <= 300)
print(f"\n  清洗后(20-300kg): {clean}/{len(weight_vals)} ({clean/len(weight_vals)*100:.1f}%)")

# ============================================================
# D6. 去甲肾上腺素盐型 + speed
# ============================================================
print("\n" + "=" * 80)
print("D6. 去甲肾上腺素盐型 + speed")
print("=" * 80)

# configDrug
print("  configDrug 去甲肾上腺素:")
for doc in db.configDrug.find({"name": {"$regex": "去甲"}}, {"name": 1, "code": 1, "spec": 1, "unit": 1}):
    print(f"    code={doc.get('code','')}, name={doc.get('name','')}, spec='{doc.get('spec','')}', unit={doc.get('unit','')}")

# drugExe 药品名
print("\n  drugExe 去甲肾上腺素药品名:")
ne_specs = Counter()
for doc in db.drugExe.find(
    {"drugList.name": {"$regex": "去甲肾上腺素"}},
    {"drugList.name": 1}
).limit(2000):
    for dl in doc.get("drugList", []):
        if "去甲" in str(dl.get("name", "")):
            ne_specs[str(dl.get("name", ""))] += 1
            break
for name, cnt in ne_specs.most_common(15):
    print(f"    {name:55s} {cnt:5d}")

# speed
print("\n  speed覆盖率(血管活性药):")
vaso_codes = [d.get("code") for d in db.configDrug.find({"classification": "血管活性"}, {"code": 1}) if d.get("code")]
speed_total = 0; speed_ok = 0; speed_unit = Counter(); speed_vals = []
for doc in db.drugExe.find(
    {"drugList.code": {"$in": vaso_codes[:50]}},
    {"hisStartTime": 1}
).limit(2000):
    speed_total += 1
    hs = doc.get("hisStartTime") or {}
    sp = hs.get("speed")
    su = hs.get("speedUnit")
    if sp is not None:
        try:
            sv = float(sp)
            if sv > 0:
                speed_ok += 1; speed_vals.append(sv)
                if su: speed_unit[str(su)] += 1
        except: pass
print(f"  总: {speed_total}, speed>0: {speed_ok} ({speed_ok/speed_total*100:.1f}%)")
print(f"  speedUnit: {dict(speed_unit.most_common(5)) if speed_unit else '全部为空'}")
if speed_vals:
    s = sorted(speed_vals); n = len(s)
    print(f"  speed值: n={n}, P5={s[int(n*.05)]:.1f}, P50={s[int(n*.50)]:.1f}, P95={s[int(n*.95)]:.1f}, max={s[-1]:.1f}")
    if s[int(n*.50)] < 200:
        print(f"  推断单位: ml/h (中位数{s[int(n*.50)]:.1f}符合临床输注速率)")

print("\n" + "=" * 80)
print("D2-D6 完成")
