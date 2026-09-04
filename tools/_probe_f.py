#!/usr/bin/env python3
"""F部分: SOFA / SOFA-2 相关探测"""
import sys, os, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from collections import Counter
from db import get_datacenter_db, iter_bed_dbs

def sc():
    for _, db in iter_bed_dbs(): return db
def pcts(vals, label=""):
    if not vals:
        print(f"  [{label}] EMPTY"); return
    s = sorted(vals)
    n = len(s)
    print(f"  [{label}] n={n}, min={s[0]:.2f}, P5={s[int(n*.05)]:.2f}, P50={s[int(n*.50)]:.2f}, P95={s[int(n*.95)]:.2f}, max={s[-1]:.2f}")
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
# F1. VI_ICU_EXAM_ITEM 关键检验
# ============================================================
print("=== F1. VI_ICU_EXAM_ITEM 关键检验 ===")
LAB_ITEMS = [
    ("PLT", "血小板"), ("TBIL", "总胆红素"), ("sCr", "肌酐"), ("Cr", "肌酐备选"),
    ("CREA", "肌酐备选2"), ("K", "钾"), ("pH", "pH"), ("HCO3", "HCO3"),
    ("LAC", "乳酸"), ("WBCJS", "白细胞"), ("PCT1", "降钙素原"),
]
for code, label in LAB_ITEMS:
    cnt = dc["VI_ICU_EXAM_ITEM"].count_documents({"itemCode": code})
    if cnt > 0:
        unit_counter = Counter()
        result_vals = []
        for doc in dc["VI_ICU_EXAM_ITEM"].find(
            {"itemCode": code}, {"itemCode": 1, "itemName": 1, "result": 1, "unit": 1, "authTime": 1}
        ).limit(100):
            u = doc.get("unit", "")
            unit_counter[u] += 1
            r = doc.get("result")
            if r is not None:
                try: result_vals.append(float(r))
                except: pass
        print(f"\n  {label}({code}): {cnt} docs")
        topn(unit_counter, 5, f"{code} unit")
        if result_vals:
            pcts(result_vals, f"{code} result")
        s = dc["VI_ICU_EXAM_ITEM"].find_one({"itemCode": code})
        if s:
            print(f"    itemName={s.get('itemName')}, sample: result={s.get('result')}, unit={s.get('unit')}, authTime={fmt_dt(s.get('authTime'))}")

# 单位变体详细统计
print("\n  --- 单位变体详细 ---")
for code, label in [("TBIL","胆红素"), ("sCr","肌酐")]:
    unit_counter = Counter()
    no_unit = 0
    for doc in dc["VI_ICU_EXAM_ITEM"].find({"itemCode": code}, {"unit": 1}).limit(1000):
        u = doc.get("unit")
        if u is None or str(u).strip() == "":
            no_unit += 1
        else:
            unit_counter[str(u).strip()] += 1
    total = sum(unit_counter.values()) + no_unit
    print(f"  {label}({code}): unit为空={no_unit}/{total}")
    for u, cnt in unit_counter.most_common(10):
        print(f"    '{u}': {cnt}")

# ============================================================
# F2. 体重
# ============================================================
print("\n=== F2. 体重 ===")
weight_count = database.patient.count_documents({"weight": {"$exists": True, "$ne": None, "$gt": 0}})
total_pat = database.patient.count_documents({})
print(f"  patient.weight > 0: {weight_count}/{total_pat} ({weight_count/total_pat*100:.1f}%)" if total_pat else "")

# 体重分布
weight_vals = []
for doc in database.patient.find({"weight": {"$gt": 0}}, {"weight": 1}).limit(300):
    try: weight_vals.append(float(doc["weight"]))
    except: pass
pcts(weight_vals, "体重(kg)")

# ============================================================
# F3. 尿量
# ============================================================
print("\n=== F3. 尿量 ===")
URINE_CODES = ["param_niaoLiang", "param_urine", "param_niaoLiang_hour"]
for code in URINE_CODES:
    cnt = database.bedside.count_documents({"code": code, "valid": True})
    if cnt > 0:
        print(f"\n  bedside {code}: {cnt} docs")
        sample = database.bedside.find_one({"code": code, "valid": True}, {"pid": 1, "strVal": 1, "time": 1})
        if sample:
            pid = sample["pid"]
            t0 = sample["time"]
            docs = list(database.bedside.find(
                {"pid": pid, "code": code, "valid": True,
                 "time": {"$gte": t0 - timedelta(hours=24), "$lte": t0}},
                {"time": 1, "strVal": 1}
            ).sort("time", 1))
            print(f"  pid={pid[:20]} 24h内={len(docs)}条")
            if len(docs) >= 2:
                gaps = [(docs[i+1]["time"] - docs[i]["time"]).total_seconds()/3600
                        for i in range(len(docs)-1)]
                pcts(gaps, f"{code} 间隔(h)")
            # 值分布
            vals = []
            for d in docs:
                try: vals.append(float(d.get("strVal", "")))
                except: pass
            if vals: pcts(vals, f"{code} 单条值(ml)")

# ============================================================
# F4. SOFA 分项时间范围可用性（抽样20例）
# ============================================================
print("\n=== F4. SOFA 分项时间范围可用性 ===")
bga_pids = []
for doc in database.bGATemp.find({}, {"eventExe.pid": 1}).limit(50):
    pid = (doc.get("eventExe") or {}).get("pid")
    if pid and pid not in bga_pids:
        bga_pids.append(pid)
    if len(bga_pids) >= 20: break
print(f"  样本患者: {len(bga_pids)}")

# 简化的SOFA分项探测
SOFA_ITEMS = {
    "P/F ratio": ("bGATemp", "param_bg_P/Fratio", 4),
    "PLT": ("dc_exam", "PLT", 12),
    "TBIL": ("dc_exam", "TBIL", 12),
    "MAP(ibp)": ("bedside", "param_ibp_m", 1),
    "MAP(nibp)": ("bedside", "param_nibp_m", 1),
    "GCS": ("bedside", "param_score_gcs_obs", 8),
    "Cr": ("dc_exam", "sCr", 12),
}

for comp, (src, code, max_h) in SOFA_ITEMS.items():
    found = 0
    total_checked = 0
    for pid in bga_pids[:10]:
        total_checked += 1
        if src == "bGATemp":
            doc = database.bGATemp.find_one(
                {"eventExe.pid": pid, "bedsides.code": code},
                sort=[("eventExe.startTime", -1)])
            if doc: found += 1
        elif src == "bedside":
            doc = database.bedside.find_one(
                {"pid": pid, "code": code, "valid": True},
                sort=[("time", -1)])
            if doc: found += 1
        elif src == "dc_exam":
            # hisPid vs pid mapping needed
            pass
    print(f"  {comp}(max_staleness={max_h}h): {found}/{total_checked} 有记录")

# ============================================================
# F5. PaO2/FiO2 配对
# ============================================================
print("\n=== F5. PaO2/FiO2 配对 ===")
paired = 0; only_pao2 = 0; only_fio2 = 0; has_pf = 0
for doc in database.bGATemp.find({}, {"bedsides.code": 1}).limit(500):
    codes = set()
    for b in doc.get("bedsides", []):
        codes.add(b.get("code"))
    if "param_bg_P/Fratio" in codes:
        has_pf += 1
    if ("param_bg_pO2" in codes or "param_bg_po2" in codes) and "param_bg_FiO2" in codes:
        paired += 1
    elif "param_bg_pO2" in codes or "param_bg_po2" in codes:
        only_pao2 += 1
    elif "param_bg_FiO2" in codes:
        only_fio2 += 1
print(f"  500条血气: 直接有P/F={has_pf}, PaO2+FiO2可算={paired}, 仅PaO2={only_pao2}, 仅FiO2={only_fio2}")

# ============================================================
# F6. 呼吸支持
# ============================================================
print("\n=== F6. 呼吸支持 ===")
VENT_CODES = {
    "param_XiYangTuJing": "吸氧途径",
    "param_vent_mode": "通气模式",
    "param_vent_type": "通气类型",
}
for code, label in VENT_CODES.items():
    cnt = database.bedside.count_documents({"code": code, "valid": True})
    if cnt > 0:
        val_counter = Counter()
        for doc in database.bedside.find({"code": code, "valid": True}, {"strVal": 1}).limit(200):
            v = doc.get("strVal", "")
            if v: val_counter[v] += 1
        print(f"\n  {label}({code}): {cnt} docs")
        topn(val_counter, 10, f"{code}")

# ECMO
print("\n  ECMO:")
for kw in ["ECMO", "ecmo", "体外膜肺"]:
    for coll in ["tubeExe", "bedside"]:
        try:
            cnt = database[coll].count_documents(
                {"$or": [{"type": {"$regex": kw, "$options": "i"}},
                         {"strVal": {"$regex": kw, "$options": "i"}}]}, limit=100)
            if cnt > 0: print(f"    {coll} 含'{kw}': {cnt}")
        except: pass

# ============================================================
# F7. RRT
# ============================================================
print("\n=== F7. RRT ===")
for kw in ["CRRT", "血透", "血液透析", "腹透", "腹膜透析", "血滤", "血液滤过", "透析"]:
    try:
        cnt = database.tubeExe.count_documents(
            {"$or": [{"type": {"$regex": kw}}, {"strVal": {"$regex": kw}}, {"name": {"$regex": kw}}]}, limit=100)
        if cnt > 0:
            print(f"  tubeExe 含'{kw}': {cnt}")
            s = database.tubeExe.find_one(
                {"$or": [{"type": {"$regex": kw}}, {"strVal": {"$regex": kw}}, {"name": {"$regex": kw}}]})
            if s:
                print(f"    样例: type={s.get('type')}, name={s.get('name')}, strVal={str(s.get('strVal',''))[:50]}")
    except: pass

# ============================================================
# F8. 镇静用药
# ============================================================
print("\n=== F8. 镇静用药 ===")
SEDATIVE_KW = ["丙泊酚", "咪达唑仑", "右美托咪定", "芬太尼", "瑞芬太尼", "舒芬太尼", "氯胺酮"]
sed_regex = "|".join(SEDATIVE_KW)
sed_count = database.drugExe.count_documents({"drugList.name": {"$regex": sed_regex}})
print(f"  镇静药执行记录: {sed_count}")

sed_sample = list(database.drugExe.find(
    {"drugList.name": {"$regex": sed_regex}},
    {"drugList.name": 1, "drugList.dose": 1, "drugList.unit": 1, "startTime": 1, "endTime": 1,
     "hisStartTime": 1}
).limit(5))
for doc in sed_sample:
    for dl in doc.get("drugList", []):
        name = str(dl.get("name", ""))
        if re.search(sed_regex, name):
            hs = doc.get("hisStartTime") or {}
            print(f"  {name[:40]}, dose={dl.get('dose')}, unit={dl.get('unit')}, "
                  f"startTime={fmt_dt(doc.get('startTime'))}, endTime={fmt_dt(doc.get('endTime'))}, "
                  f"hisEndTime={fmt_dt(hs.get('endTime'))}")
            break

# ============================================================
# F9. 升压药剂量
# ============================================================
print("\n=== F9. 升压药剂量 ===")
VASO_KW = ["去甲肾上腺素", "肾上腺素", "多巴胺", "多巴酚丁胺"]
vaso_regex = "|".join(VASO_KW)
vaso_sample = list(database.drugExe.find(
    {"drugList.name": {"$regex": vaso_regex}},
    {"drugList": 1, "startTime": 1, "drugActionList": 1, "weight": 1,
     "liquidAmount": 1, "liquidAmountUnit": 1, "recommendSpeed": 1, "recommendSpeedUnit": 1,
     "liquidName": 1, "liquidSpec": 1, "hisStartTime": 1}
).limit(10))
print(f"  升压药样例: {len(vaso_sample)}")
for doc in vaso_sample[:3]:
    print(f"\n  startTime={fmt_dt(doc.get('startTime'))}")
    print(f"    weight={doc.get('weight')}")
    print(f"    liquidAmount={doc.get('liquidAmount')} {doc.get('liquidAmountUnit','')}")
    print(f"    recommendSpeed={doc.get('recommendSpeed')} {doc.get('recommendSpeedUnit','')}")
    print(f"    liquidName={doc.get('liquidName')}, liquidSpec={doc.get('liquidSpec')}")
    for dl in doc.get("drugList", [])[:2]:
        print(f"    drug: name={dl.get('name','')[:50]}, dose={dl.get('dose')}, unit={dl.get('unit')}, spec={dl.get('spec','')[:30]}")
    hs = doc.get("hisStartTime") or {}
    print(f"    hisStartTime: speed={hs.get('speed')}, speedUnit={hs.get('speedUnit')}, endTime={fmt_dt(hs.get('endTime'))}")

# ============================================================
# F10. 连续输注持续时长
# ============================================================
print("\n=== F10. 连续输注时长 ===")
end_time_count = database.drugExe.count_documents({"endTime": {"$exists": True, "$ne": None}})
total_drug = database.drugExe.count_documents({})
print(f"  drugExe.endTime 非空: {end_time_count}/{total_drug} ({end_time_count/total_drug*100:.1f}%)" if total_drug else "")

hs_end_count = 0
for doc in database.drugExe.find({"status": "finished"}, {"hisStartTime": 1}).limit(500):
    hs = doc.get("hisStartTime")
    if isinstance(hs, dict) and hs.get("endTime"):
        hs_end_count += 1
print(f"  hisStartTime.endTime 非空: {hs_end_count}/500")

# ============================================================
# F11. SmartCare 自带 SOFA
# ============================================================
print("\n=== F11. SmartCare SOFA ===")
sofa_counter = Counter()
for doc in database.score.find({}, {"scoreType": 1}).limit(10000):
    st = doc.get("scoreType", "")
    if "sofa" in st.lower():
        sofa_counter[st] += 1
if sofa_counter:
    print(f"  SOFA scoreType: {dict(sofa_counter)}")
    for st in sofa_counter:
        s = database.score.find_one({"scoreType": st})
        if s:
            print(f"    {st}: total={s.get('total')}, time={fmt_dt(s.get('time'))}, fields={sorted(s.keys())}")
else:
    print("  未找到 SOFA 相关 scoreType")

print("\n"+"="*80)
print("F 探测完成")
