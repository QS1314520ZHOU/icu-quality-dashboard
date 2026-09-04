#!/usr/bin/env python3
"""ICU-05 v3 精简探查 — 按小批次跑"""
import sys, os, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from collections import Counter
from db import get_client, get_datacenter_db, iter_bed_dbs, EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES

def sc():
    for _, db in iter_bed_dbs(): return db
def dc():
    try: return get_datacenter_db()
    except: return None
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

database = sc()
dcenter = dc()
BGA = "bGATemp"

# ============================================================
# A1. P/F ratio
# ============================================================
print("\n=== A1. P/F ratio ===")
pf_count = database[BGA].count_documents({"bedsides.code":"param_bg_P/Fratio"})
print(f"  param_bg_P/Fratio 存在: {pf_count} docs")

pf_vals, pf_times, pid_pf = [], [], {}
for doc in database[BGA].find({"bedsides.code":"param_bg_P/Fratio"},{"eventExe":1,"bedsides":1}).limit(500):
    evt = doc.get("eventExe",{})
    pid = evt.get("pid",""); t = evt.get("startTime")
    for b in doc.get("bedsides",[]):
        if b.get("code") == "param_bg_P/Fratio":
            v = b.get("fVal")
            if v is not None:
                try:
                    pf_vals.append(float(v)); pf_times.append(t)
                    pid_pf.setdefault(pid,[]).append(t)
                except: pass
            break
print(f"  非空记录(采样500): {len(pf_vals)}")
pcts(pf_vals, "P/F ratio 值")
freqs = []
for pid, times in pid_pf.items():
    if len(times)>=2:
        ts = sorted([t for t in times if t])
        gaps=[(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)]
        freqs.extend(gaps)
pcts(freqs, "采样间隔(h)")

# PaO2 / FiO2
print("\n  PaO2/FiO2 备选:")
for code in ["param_bg_pO2","param_bg_FiO2","param_bg_po2"]:
    cnt = database[BGA].count_documents({"bedsides.code": code})
    if cnt > 0:
        print(f"  {code}: {cnt} docs")
        sample = database[BGA].find_one({"bedsides.code": code})
        for b in (sample or {}).get("bedsides",[]):
            if b.get("code") == code:
                print(f"    样例: fVal={b.get('fVal')}, strVal={b.get('strVal')}")
                break

# ============================================================
# A2. GCS
# ============================================================
print("\n=== A2. GCS ===")
for code in ["param_score_gcs_obs","param_score_gcs","param_gcs"]:
    cnt = database.bedside.count_documents({"code":code,"valid":True})
    if cnt > 0:
        print(f"  bedside {code}: {cnt} docs")
        s = list(database.bedside.find({"code":code,"valid":True},{"pid":1,"strVal":1,"fVal":1,"time":1}).limit(3))
        for x in s: print(f"    pid={x.get('pid','')[:20]}, strVal={x.get('strVal')}, fVal={x.get('fVal')}, time={x.get('time')}")

# score
st_counter = Counter()
for doc in database.score.find({},{"scoreType":1}).limit(10000):
    st = doc.get("scoreType","")
    if st: st_counter[st] += 1
print(f"\n  score.scoreType 分布(top30):")
for st, cnt in st_counter.most_common(30):
    print(f"    {st:40s} {cnt:6d}")

for st in ["gcsScore","gcs","GCS"]:
    cnt = database.score.count_documents({"scoreType":st})
    if cnt > 0:
        print(f"\n  scoreType={st}: {cnt} docs")
        s = list(database.score.find({"scoreType":st},{"pid":1,"total":1,"score":1,"value":1,"time":1}).limit(3))
        for x in s: print(f"    total={x.get('total')}, score={x.get('score')}, value={x.get('value')}, time={x.get('time')}")

# ============================================================
# A3. MAP
# ============================================================
print("\n=== A3. MAP ===")
MAP_CODES = {"有创MAP":"param_ibp_m","无创MAP":"param_nibp_m","有创SBP":"param_ibp_s","无创SBP":"param_nibp_s","有创DBP":"param_ibp_d","无创DBP":"param_nibp_d"}
for label, code in MAP_CODES.items():
    cnt = database.bedside.count_documents({"code":code,"valid":True})
    if cnt > 0:
        print(f"  {code} ({label}): {cnt} docs")
        s = list(database.bedside.find({"code":code,"valid":True},{"strVal":1}).limit(3))
        for x in s: print(f"    strVal={x.get('strVal')}")

# ============================================================
# A4. configDrug classification
# ============================================================
print("\n=== A4. configDrug classification ===")
class_counter = Counter()
for doc in database.configDrug.find({},{"classification":1,"name":1,"code":1}).limit(5000):
    c = doc.get("classification")
    if c: class_counter[c] += 1
topn(class_counter, 20, "classification")

vaso_drugs = list(database.configDrug.find({"classification":"血管活性"},{"code":1,"name":1}).limit(50))
print(f"\n  血管活性药物: {len(vaso_drugs)} 个")
for d in vaso_drugs[:30]:
    print(f"    code={d.get('code','')}, name={d.get('name','')}")

# drugExe status
print("\n  drugExe 字段样例:")
sd = database.drugExe.find_one()
if sd:
    print(f"  keys: {sorted(sd.keys())[:20]}")

status_counter = Counter()
for doc in database.drugExe.find({},{"status":1,"statusFlag":1,"executeStatus":1}).limit(1000):
    for f in ["status","statusFlag","executeStatus"]:
        v = doc.get(f)
        if v: status_counter[f"{f}={v}"] += 1
topn(status_counter, 15, "执行状态")

# ============================================================
# B1. Lac
# ============================================================
print("\n=== B1. Lac ===")
lac_vals, pid_lac = [], {}
lac_fields = []
for doc in database[BGA].find({"bedsides.code":"param_bg_Lac"},{"eventExe":1,"bedsides":1}).limit(500):
    evt = doc.get("eventExe",{})
    pid = evt.get("pid",""); t = evt.get("startTime")
    for b in doc.get("bedsides",[]):
        if b.get("code") == "param_bg_Lac":
            lac_fields = list(b.keys())
            v = b.get("fVal")
            if v is not None:
                try:
                    lac_vals.append(float(v))
                    pid_lac.setdefault(pid,[]).append(t)
                except: pass
            break
print(f"  Lac 非空(采样500): {len(lac_vals)}")
print(f"  bedsides字段: {lac_fields}")
pcts(lac_vals, "Lac值(mmol/L)")
freqs = []
for pid, times in pid_lac.items():
    if len(times)>=2:
        ts = sorted([t for t in times if t])
        gaps=[(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)]
        freqs.extend(gaps)
pcts(freqs, "Lac采样间隔(h)")

# 动脉 vs 静脉区分
print("\n  动脉血/静脉血区分:")
for doc in database[BGA].find({"bedsides.code":"param_bg_Lac"},{"bedsides":1,"eventExe":1}).limit(5):
    for b in doc.get("bedsides",[]):
        if b.get("code") == "param_bg_Lac":
            print(f"    子文档完整: {json.dumps(b, ensure_ascii=False, default=str)[:200]}")
            break

# ============================================================
# B2. 血管活性药物执行时间
# ============================================================
print("\n=== B2. 血管活性药物执行时间 ===")
vaso_codes = [d.get("code") for d in vaso_drugs if d.get("code")]
if vaso_codes:
    sample_vaso = list(database.drugExe.find(
        {"drugList.code":{"$in":vaso_codes[:30]}},
        {"startTime":1,"exeTime":1,"hisStartTime":1,"orderTime":1,"status":1,"drugList":1}
    ).limit(50))
    print(f"  样本: {len(sample_vaso)}")
    tf = {"startTime":0,"exeTime":0,"hisStartTime":0,"orderTime":0}
    for doc in sample_vaso:
        for f in tf:
            if doc.get(f) is not None: tf[f] += 1
    for f,cnt in tf.items(): print(f"    {f} 非空: {cnt}/{len(sample_vaso)}")

    for doc in sample_vaso[:3]:
        hs = doc.get("hisStartTime")
        if isinstance(hs,dict):
            print(f"    hisStartTime: {json.dumps(hs, ensure_ascii=False, default=str)[:300]}")
            break

# ============================================================
# C1. 感染类诊断
# ============================================================
print("\n=== C1. 感染类诊断 ===")
diag_counter = Counter()
for doc in database.diseaseDiagnosis.find({"valid":{"$ne":False}},{"diseaseType":1}).limit(5000):
    dt = doc.get("diseaseType","")
    if dt: diag_counter[dt] += 1
print(f"  diseaseType top30:")
for name, cnt in diag_counter.most_common(30):
    print(f"    {name:50s} {cnt:5d}")

# ============================================================
# C2. 病原学送检
# ============================================================
print("\n=== C2. 病原学送检 ===")
if dcenter is not None:
    order_counter = Counter()
    for doc in dcenter["VI_ICU_ZYYZ"].find(
        {"yaoType":{"$in":LAB_ORDER_TYPES},"orderName":{"$regex":"培养|涂片|药敏"}},
        {"orderName":1}
    ).limit(300):
        name = doc.get("orderName","")[:50]
        order_counter[name] += 1
    topn(order_counter, 30, "培养/药敏医嘱")

# ============================================================
# C3. 感染部位字段
# ============================================================
print("\n=== C3. 感染部位字段 ===")
sample_diag = list(database.diseaseDiagnosis.find().limit(3))
all_f = set()
for d in sample_diag: all_f.update(d.keys())
print(f"  diseaseDiagnosis 字段: {sorted(all_f)}")
for d in sample_diag:
    ss = d.get("septicShock")
    if ss: print(f"  septicShock: {json.dumps(ss, ensure_ascii=False, default=str)[:300]}"); break
    for k in d.keys():
        if "site" in k.lower() or "部位" in k or "infection" in k.lower():
            print(f"  疑似部位字段: {k}={d.get(k)}")

print("\n"+"="*80)
print("A~C 探测完成")
