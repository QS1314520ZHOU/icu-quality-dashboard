#!/usr/bin/env python3
"""A部分: 脓毒症器官障碍4项 + B脓毒症休克2项 + C感染部位"""
import sys, os, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from collections import Counter
import statistics
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

print("="*80)
print("ICU-05 v3 探测 Part A: 脓毒症器官障碍 + 休克 + 感染部位")
print("="*80)

# ============================================================
# A1. P/F ratio
# ============================================================
print("\n--- A1. P/F ratio ---")
BGA = "bGATemp"
if BGA in database.list_collection_names():
    # 转义查询
    pf_count = database[BGA].count_documents({"bedsides.code": "param_bg_P/Fratio"})
    print(f"  param_bg_P/Fratio 存在: {pf_count} docs")

    pf_vals = []
    pf_times = []
    pid_pf = {}
    for doc in database[BGA].find({"bedsides.code": "param_bg_P/Fratio"}, {"eventExe":1,"bedsides":1}).limit(3000):
        evt = doc.get("eventExe", {})
        pid = evt.get("pid","")
        t = evt.get("startTime")
        for b in doc.get("bedsides", []):
            if b.get("code") == "param_bg_P/Fratio":
                v = b.get("fVal")
                if v is not None:
                    try:
                        pf_vals.append(float(v))
                        pf_times.append(t)
                        pid_pf.setdefault(pid,[]).append(t)
                    except: pass
                break
    print(f"  非空记录: {len(pf_vals)}")
    pcts(pf_vals, "P/F ratio 值")

    # 采样频率
    freqs = []
    for pid, times in pid_pf.items():
        if len(times) >= 2:
            ts = sorted([t for t in times if t])
            gaps = [(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)]
            freqs.extend(gaps)
    pcts(freqs, "P/F ratio 采样间隔(h)")

    # PaO2 / FiO2
    print("\n  PaO2/FiO2 备选:")
    for code in ["param_bg_pO2","param_bg_FiO2"]:
        cnt = database[BGA].count_documents({"bedsides.code": code})
        print(f"  {code}: {cnt} docs")
        if cnt > 0:
            sample = database[BGA].find_one({"bedsides.code": code})
            for b in (sample or {}).get("bedsides",[]):
                if b.get("code") == code:
                    print(f"    样例: fVal={b.get('fVal')}, strVal={b.get('strVal')}")
                    break

# ============================================================
# A2. GCS
# ============================================================
print("\n--- A2. GCS ---")
# bedside
for code in ["param_score_gcs_obs","param_score_gcs","param_gcs"]:
    cnt = database.bedside.count_documents({"code": code, "valid": True})
    if cnt > 0:
        print(f"  bedside {code}: {cnt} docs")
        sample = list(database.bedside.find({"code":code,"valid":True},{"pid":1,"strVal":1,"fVal":1,"time":1}).limit(3))
        for s in sample:
            print(f"    pid={s.get('pid','')[:20]}, strVal={s.get('strVal')}, fVal={s.get('fVal')}, time={s.get('time')}")

# score
if "score" in database.list_collection_names():
    st_counter = Counter()
    for doc in database.score.find({}, {"scoreType":1}).limit(10000):
        st = doc.get("scoreType","")
        if st: st_counter[st] += 1
    print(f"\n  score.scoreType 全量分布 (top 30):")
    for st, cnt in st_counter.most_common(30):
        print(f"    {st:40s} {cnt:6d}")

    # GCS score_type
    for st in ["gcsScore","gcs","GCS","GCS评分"]:
        cnt = database.score.count_documents({"scoreType": st})
        if cnt > 0:
            print(f"\n  scoreType={st}: {cnt} docs")
            sample = list(database.score.find({"scoreType":st},{"pid":1,"total":1,"score":1,"value":1,"fVal":1,"iVal":1,"time":1}).limit(3))
            for s in sample:
                print(f"    pid={s.get('pid','')[:20]}, total={s.get('total')}, score={s.get('score')}, value={s.get('value')}, time={s.get('time')}")

# ============================================================
# A3. MAP
# ============================================================
print("\n--- A3. MAP / 血压 ---")
MAP_CODES = {
    "有创MAP":"param_ibp_m", "无创MAP":"param_nibp_m",
    "有创SBP":"param_ibp_s", "无创SBP":"param_nibp_s",
    "有创DBP":"param_ibp_d", "无创DBP":"param_nibp_d",
}
for label, code in MAP_CODES.items():
    cnt = database.bedside.count_documents({"code": code, "valid": True})
    if cnt > 0:
        print(f"  {code} ({label}): {cnt} docs")
        sample = list(database.bedside.find({"code":code,"valid":True},{"strVal":1}).limit(3))
        for s in sample:
            print(f"    strVal={s.get('strVal')}")

# MAP 采样频率 (有创)
sample_map = database.bedside.find_one({"code":"param_ibp_m","valid":True},{"pid":1,"time":1})
if sample_map:
    pid = sample_map["pid"]
    t0 = sample_map["time"]
    docs = list(database.bedside.find(
        {"pid":pid,"code":{"$in":["param_ibp_m","param_nibp_m"]},"valid":True,
         "time":{"$gte":t0-timedelta(hours=24),"$lte":t0}},
        {"time":1}
    ).sort("time",1))
    print(f"\n  有创MAP采样: 患者{pid[:20]} 24h内={len(docs)}条")
    if len(docs)>=2:
        gaps=[(docs[i+1]["time"]-docs[i]["time"]).total_seconds()/3600 for i in range(len(docs)-1)]
        pcts(gaps, "MAP间隔(h)")

# MAP 非空率
ibp_m = database.bedside.count_documents({"code":"param_ibp_m","valid":True})
nibp_m = database.bedside.count_documents({"code":"param_nibp_m","valid":True})
print(f"\n  有创MAP: {ibp_m}, 无创MAP: {nibp_m}")

# ============================================================
# A4. 药物配置表 classification
# ============================================================
print("\n--- A4. configDrug classification ---")
class_counter = Counter()
for doc in database.configDrug.find({}, {"classification":1,"name":1,"code":1}).limit(5000):
    c = doc.get("classification")
    if c: class_counter[c] += 1
topn(class_counter, 20, "classification 分布")

# 血管活性药物
vaso_drugs = list(database.configDrug.find({"classification":"血管活性"},{"code":1,"name":1}).limit(50))
print(f"\n  classification='血管活性' 药物: {len(vaso_drugs)} 个")
for d in vaso_drugs[:30]:
    print(f"    code={d.get('code','')}, name={d.get('name','')}")

# drugExe 执行状态
print("\n  drugExe 执行状态字段探测:")
sample_doc = database.drugExe.find_one()
if sample_doc:
    print(f"  drugExe 字段: {sorted(sample_doc.keys())}")

status_counter = Counter()
for doc in database.drugExe.find({}, {"status":1,"statusFlag":1,"executeStatus":1}).limit(3000):
    for f in ["status","statusFlag","executeStatus"]:
        v = doc.get(f)
        if v: status_counter[f"{f}={v}"] += 1
topn(status_counter, 15, "执行状态分布")

# ============================================================
# B1. 乳酸 Lac
# ============================================================
print("\n--- B1. param_bg_Lac ---")
lac_vals = []
lac_times = []
pid_lac = {}
for doc in database[BGA].find({"bedsides.code":"param_bg_Lac"},{"eventExe":1,"bedsides":1}).limit(3000):
    evt = doc.get("eventExe",{})
    pid = evt.get("pid","")
    t = evt.get("startTime")
    for b in doc.get("bedsides",[]):
        if b.get("code") == "param_bg_Lac":
            lac_fields = list(b.keys())
            v = b.get("fVal")
            if v is not None:
                try:
                    lac_vals.append(float(v))
                    lac_times.append(t)
                    pid_lac.setdefault(pid,[]).append(t)
                except: pass
            break
print(f"  Lac 非空记录: {len(lac_vals)}")
print(f"  Lac bedsides 子文档字段: {lac_fields}")
pcts(lac_vals, "Lac值(mmol/L)")
freqs = []
for pid, times in pid_lac.items():
    if len(times)>=2:
        ts = sorted([t for t in times if t])
        gaps=[(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)]
        freqs.extend(gaps)
pcts(freqs, "Lac采样间隔(h)")

# ============================================================
# B2. 血管活性药物执行时间
# ============================================================
print("\n--- B2. 血管活性药物执行时间 ---")
vaso_codes = [d.get("code") for d in vaso_drugs if d.get("code")]
if vaso_codes:
    time_fields = {"startTime":0,"exeTime":0,"hisStartTime":0,"orderTime":0}
    sample_vaso = list(database.drugExe.find(
        {"drugList.code":{"$in":vaso_codes[:50]}},
        {"startTime":1,"exeTime":1,"hisStartTime":1,"orderTime":1,"status":1,"drugList":1}
    ).limit(100))
    for doc in sample_vaso:
        for f in time_fields:
            if doc.get(f) is not None: time_fields[f] += 1
    print(f"  样本量: {len(sample_vaso)}")
    for f, cnt in time_fields.items():
        print(f"    {f} 非空: {cnt}/{len(sample_vaso)}")

    # hisStartTime 内部结构
    for doc in sample_vaso[:3]:
        hs = doc.get("hisStartTime")
        if isinstance(hs, dict):
            print(f"    hisStartTime 结构: {json.dumps(hs, ensure_ascii=False, default=str)[:300]}")
            break

# ============================================================
# C1. 诊断表感染类诊断
# ============================================================
print("\n--- C1. diseaseDiagnosis 感染类诊断 ---")
diag_counter = Counter()
for doc in database.diseaseDiagnosis.find({"valid":{"$ne":False}},{"diseaseType":1}).limit(5000):
    dt = doc.get("diseaseType","")
    if dt: diag_counter[dt] += 1
print(f"  diseaseType 全量分布(top 30):")
for name, cnt in diag_counter.most_common(30):
    print(f"    {name:50s} {cnt:5d}")

# 感染关键词匹配
INFECTION_KW = ["肺炎","脓毒","感染","败血","菌血","腹膜炎","脓肿","化脓",
    "尿路感染","胆管炎","脑膜炎","蜂窝织炎","VAP","CRBSI","CAUTI",
    "导管相关","手术部位","切口感染","腹腔感染","肺部感染"]
infect_count = 0
total_diag = 0
for name, cnt in diag_counter.items():
    total_diag += cnt
    if any(kw in name for kw in INFECTION_KW):
        infect_count += cnt
print(f"\n  含感染关键词的诊断记录: {infect_count}/{total_diag} ({infect_count/total_diag*100:.1f}%)" if total_diag else "")

# ============================================================
# C2. 病原学送检标本类型
# ============================================================
print("\n--- C2. 病原学送检标本类型 ---")
if dcenter is not None:
    sample_orders = list(dcenter["VI_ICU_ZYYZ"].find(
        {"yaoType":{"$in":LAB_ORDER_TYPES},"orderName":{"$regex":"培养|涂片|药敏"}},
        {"orderName":1}
    ).limit(300))
    order_counter = Counter()
    for o in sample_orders:
        name = o.get("orderName","")[:50]
        order_counter[name] += 1
    topn(order_counter, 30, "培养/涂片/药敏 医嘱名")

# ============================================================
# C3. 感染部位字段
# ============================================================
print("\n--- C3. 感染部位字段探测 ---")
sample_diag = list(database.diseaseDiagnosis.find().limit(3))
all_fields = set()
for d in sample_diag: all_fields.update(d.keys())
print(f"  diseaseDiagnosis 字段: {sorted(all_fields)}")
for d in sample_diag:
    ss = d.get("septicShock")
    if ss:
        print(f"  septicShock 子文档: {json.dumps(ss, ensure_ascii=False, default=str)[:300]}")
        break

# 看有没有 infectionSite / site / 部位 相关字段
for d in sample_diag:
    for k in d.keys():
        if "site" in k.lower() or "部位" in k or "infection" in k.lower():
            print(f"  疑似部位字段: {k} = {d.get(k)}")

print("\n"+"="*80)
print("Part A 完成")
