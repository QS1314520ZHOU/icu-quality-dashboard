#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICU-05 v3 字段探测脚本（只读，不改任何数据）
覆盖 A~G 全部探查项，输出到 stdout。
"""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from collections import Counter
import statistics

from db import (
    get_client, get_datacenter_db, iter_bed_dbs, BED_DB_NAMES,
    DATACENTER_CFG, EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES,
)

# ============================================================
# 工具函数
# ============================================================

def safe_str(v, maxlen=80):
    if v is None: return "None"
    s = str(v)
    return s[:maxlen] + "..." if len(s) > maxlen else s

def fmt_dt(v):
    if v is None: return "None"
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:30]

def topn(counter, n=10, label=""):
    total = sum(counter.values())
    print(f"\n  [{label}] top{n} (total={total}):")
    for val, cnt in counter.most_common(n):
        pct = cnt / total * 100 if total else 0
        print(f"    {val!r:60s}  {cnt:6d} ({pct:5.1f}%)")
    return counter

def percentile(values, p):
    if not values: return None
    values = sorted(values)
    k = (len(values) - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= len(values): return values[-1]
    return values[f] + (k - f) * (values[c] - values[f])

def stats_row(values, label=""):
    if not values:
        print(f"  [{label}] EMPTY")
        return
    print(f"  [{label}] n={len(values)}, "
          f"P5={percentile(values,5):.1f}, P50={percentile(values,50):.1f}, "
          f"P95={percentile(values,95):.1f}, min={min(values):.1f}, max={max(values):.1f}")

def get_sc_db():
    for db_name, db in iter_bed_dbs():
        return db
    return None

def get_dc_db():
    try:
        return get_datacenter_db()
    except:
        return None


def main():
    sc = get_sc_db()
    dc = get_dc_db()
    if sc is None:
        print("FATAL: no SmartCare DB"); return

    print("=" * 90)
    print("ICU-05 v3 字段探测 — 全量报告")
    print("=" * 90)

    # ============================================================
    # A. 脓毒症器官障碍 4 项
    # ============================================================
    print("\n" + "=" * 90)
    print("A. 脓毒症器官障碍 4 项")
    print("=" * 90)

    # ---- A1. 血气 P/F ratio ----
    print("\n--- A1. 血气 P/F ratio ---")
    for coll_name in ["bGATemp", "bGATemp1", "BGATemp"]:
        if coll_name not in sc.list_collection_names():
            print(f"  {coll_name}: NOT EXISTS")
            continue
        # param_bg_P/Fratio (带斜杠)
        pf_count = sc[coll_name].count_documents(
            {"bedsides": {"$elemMatch": {"code": "param_bg_P/Fratio"}}}, limit=5000)
        print(f"  {coll_name} param_bg_P/Fratio 存在: {pf_count}+ docs")

        # 检查查询是否需要转义
        try:
            sample = list(sc[coll_name].find(
                {"bedsides.code": "param_bg_P/Fratio"},
                {"eventExe": 1, "bedsides": 1, "deptCode": 1}
            ).limit(3))
            for doc in sample:
                evt = doc.get("eventExe", {})
                for b in doc.get("bedsides", []):
                    if b.get("code") == "param_bg_P/Fratio":
                        print(f"    样例: pid={evt.get('pid','')[:20]}, "
                              f"time={fmt_dt(evt.get('startTime'))}, "
                              f"fVal={b.get('fVal')}, strVal={b.get('strVal')}")
                        break
        except Exception as e:
            print(f"    查询失败(可能需要转义): {e}")

        # 非空率、取值分布
        pf_vals = []
        pf_times = []
        pid_pf = {}  # pid -> [times]
        for doc in sc[coll_name].find(
            {"bedsides.code": "param_bg_P/Fratio"},
            {"eventExe": 1, "bedsides": 1}
        ).limit(2000):
            evt = doc.get("eventExe", {})
            pid = evt.get("pid", "")
            t = evt.get("startTime")
            for b in doc.get("bedsides", []):
                if b.get("code") == "param_bg_P/Fratio":
                    v = b.get("fVal")
                    if v is not None:
                        try:
                            pf_vals.append(float(v))
                            pf_times.append(t)
                            pid_pf.setdefault(pid, []).append(t)
                        except: pass
                    break

        print(f"  P/F ratio 非空记录数: {len(pf_vals)}")
        stats_row(pf_vals, "P/F ratio 取值")
        # 采样频率
        freqs = []
        for pid, times in pid_pf.items():
            if len(times) >= 2:
                times_sorted = sorted(times)
                gaps = [(times_sorted[i+1] - times_sorted[i]).total_seconds() / 3600
                        for i in range(len(times_sorted)-1)]
                freqs.extend(gaps)
        stats_row(freqs, "P/F ratio 采样间隔(h)")

        # PaO2 / FiO2
        for code in ["param_bg_pO2", "param_bg_FiO2", "param_bg_po2"]:
            cnt = sc[coll_name].count_documents(
                {"bedsides.code": code}, limit=5000)
            if cnt > 0:
                print(f"  {coll_name} {code}: {cnt}+ docs")
                sample = list(sc[coll_name].find(
                    {"bedsides.code": code},
                    {"eventExe": 1, "bedsides": 1}
                ).limit(3))
                for doc in sample:
                    for b in doc.get("bedsides", []):
                        if b.get("code") == code:
                            print(f"    样例: fVal={b.get('fVal')}, strVal={b.get('strVal')}")
                            break

    # ---- A2. GCS ----
    print("\n--- A2. GCS ---")
    # bedside
    GCS_CODES = ["param_score_gcs_obs", "param_score_gcs", "param_gcs"]
    for code in GCS_CODES:
        cnt = sc.bedside.count_documents({"code": code, "valid": True}, limit=5000)
        if cnt > 0:
            print(f"  bedside {code}: {cnt}+ docs")
            sample = list(sc.bedside.find(
                {"code": code, "valid": True},
                {"pid": 1, "strVal": 1, "fVal": 1, "time": 1}
            ).limit(5))
            for s in sample:
                print(f"    pid={s.get('pid','')[:20]}, strVal={s.get('strVal')}, "
                      f"fVal={s.get('fVal')}, time={fmt_dt(s.get('time'))}")

    # score 表
    if "score" in sc.list_collection_names():
        score_types = Counter()
        for doc in sc.score.find({}, {"scoreType": 1}).limit(5000):
            st = doc.get("scoreType")
            if st: score_types[st] += 1
        print(f"\n  score 表 scoreType 全量分布:")
        for st, cnt in score_types.most_common(30):
            print(f"    {st:40s}  {cnt:6d}")

        # GCS 详细
        GCS_SCORE_TYPES = ["gcsScore", "gcs", "GCS"]
        for st in GCS_SCORE_TYPES:
            cnt = sc.score.count_documents({"scoreType": st}, limit=5000)
            if cnt > 0:
                print(f"\n  score scoreType={st}: {cnt}+ docs")
                sample = list(sc.score.find(
                    {"scoreType": st},
                    {"pid": 1, "total": 1, "score": 1, "value": 1,
                     "fVal": 1, "iVal": 1, "strVal": 1, "time": 1}
                ).limit(5))
                for s in sample:
                    print(f"    pid={s.get('pid','')[:20]}, total={s.get('total')}, "
                          f"score={s.get('score')}, value={s.get('value')}, "
                          f"time={fmt_dt(s.get('time'))}")

    # ---- A3. MAP ----
    print("\n--- A3. MAP / 血压 ---")
    MAP_CODES = {
        "有创MAP": ["param_ibp_m"],
        "无创MAP": ["param_nibp_m"],
        "有创SBP": ["param_ibp_s"],
        "无创SBP": ["param_nibp_s"],
        "有创DBP": ["param_ibp_d"],
        "无创DBP": ["param_nibp_d"],
    }
    for label, codes in MAP_CODES.items():
        for code in codes:
            cnt = sc.bedside.count_documents({"code": code, "valid": True}, limit=10000)
            if cnt > 0:
                print(f"  bedside {code} ({label}): {cnt}+ docs")
                sample = list(sc.bedside.find(
                    {"code": code, "valid": True}, {"strVal": 1}
                ).limit(3))
                for s in sample:
                    print(f"    strVal={s.get('strVal')}")

    # MAP 采样频率(取一个有数据的患者)
    map_sample = sc.bedside.find_one(
        {"code": "param_ibp_m", "valid": True}, {"pid": 1, "time": 1})
    if map_sample:
        pid = map_sample["pid"]
        t = map_sample["time"]
        window_start = t - timedelta(hours=24)
        docs_24h = list(sc.bedside.find(
            {"pid": pid, "code": {"$in": ["param_ibp_m", "param_nibp_m"]},
             "valid": True, "time": {"$gte": window_start, "$lte": t}},
            {"time": 1, "code": 1}
        ).sort("time", 1))
        print(f"\n  患者 {pid[:20]} 24h内 MAP 记录数: {len(docs_24h)}")
        if len(docs_24h) >= 2:
            gaps = [(docs_24h[i+1]["time"] - docs_24h[i]["time"]).total_seconds()/3600
                    for i in range(len(docs_24h)-1)]
            stats_row(gaps, "MAP 采样间隔(h)")

    # ---- A4. 药物配置表 classification ----
    print("\n--- A4. configDrug classification ---")
    class_counter = Counter()
    for doc in sc.configDrug.find({}, {"classification": 1, "name": 1, "code": 1}).limit(5000):
        c = doc.get("classification")
        if c: class_counter[c] += 1
    topn(class_counter, 20, "configDrug.classification")

    # 血管活性药物
    print("\n  --- 血管活性药物 (classification='血管活性') ---")
    vaso_drugs = list(sc.configDrug.find(
        {"classification": "血管活性"},
        {"code": 1, "name": 1}
    ).limit(50))
    print(f"  血管活性药物总数: {len(vaso_drugs)}")
    for d in vaso_drugs[:30]:
        print(f"    code={d.get('code','')}, name={d.get('name','')}")

    # drugExe status 分布
    print("\n  --- drugExe status 取值分布 ---")
    status_counter = Counter()
    for doc in sc.drugExe.find({}, {"status": 1, "statusFlag": 1, "executeStatus": 1}).limit(5000):
        for f in ["status", "statusFlag", "executeStatus"]:
            v = doc.get(f)
            if v: status_counter[f"{f}={v}"] += 1
    topn(status_counter, 20, "drugExe 执行状态")

    # ============================================================
    # B. 脓毒症休克 2 项
    # ============================================================
    print("\n" + "=" * 90)
    print("B. 脓毒症休克 2 项")
    print("=" * 90)

    # ---- B1. 乳酸 ----
    print("\n--- B1. param_bg_Lac ---")
    for coll_name in ["bGATemp", "bGATemp1"]:
        if coll_name not in sc.list_collection_names(): continue
        lac_vals = []
        lac_times = []
        pid_lac = {}
        lac_fields_seen = set()
        for doc in sc[coll_name].find(
            {"bedsides.code": "param_bg_Lac"},
            {"eventExe": 1, "bedsides": 1}
        ).limit(3000):
            evt = doc.get("eventExe", {})
            pid = evt.get("pid", "")
            t = evt.get("startTime")
            for b in doc.get("bedsides", []):
                if b.get("code") == "param_bg_Lac":
                    lac_fields_seen.update(b.keys())
                    v = b.get("fVal")
                    if v is not None:
                        try:
                            lac_vals.append(float(v))
                            lac_times.append(t)
                            pid_lac.setdefault(pid, []).append(t)
                        except: pass
                    break

        print(f"  {coll_name} Lac 非空记录: {len(lac_vals)}")
        print(f"  Lac bedsides 子文档字段: {lac_fields_seen}")
        stats_row(lac_vals, "Lac 值(mmol/L)")
        # 采样频率
        freqs = []
        for pid, times in pid_lac.items():
            if len(times) >= 2:
                ts = sorted(times)
                gaps = [(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)]
                freqs.extend(gaps)
        stats_row(freqs, "Lac 采样间隔(h)")

    # ---- B2. 血管活性药物执行时间 ----
    print("\n--- B2. 血管活性药物执行时间字段 ---")
    vaso_codes = [d.get("code") for d in vaso_drugs if d.get("code")]
    if vaso_codes:
        time_fields = {"startTime": 0, "exeTime": 0, "hisStartTime": 0, "orderTime": 0}
        sample_vaso = list(sc.drugExe.find(
            {"drugList.code": {"$in": vaso_codes[:50]}},
            {"startTime": 1, "exeTime": 1, "hisStartTime": 1, "orderTime": 1,
             "status": 1, "drugList": 1}
        ).limit(100))
        for doc in sample_vaso:
            for f in time_fields:
                if doc.get(f) is not None:
                    time_fields[f] += 1
        print(f"  血管活性药物执行记录样例: {len(sample_vaso)}")
        for f, cnt in time_fields.items():
            print(f"    {f} 非空: {cnt}/{len(sample_vaso)}")

        # hisStartTime 内部结构
        for doc in sample_vaso[:3]:
            hs = doc.get("hisStartTime")
            if isinstance(hs, dict):
                print(f"    hisStartTime 结构: {json.dumps(hs, ensure_ascii=False, default=str)[:200]}")
                break

    # ============================================================
    # C. 感染部位
    # ============================================================
    print("\n" + "=" * 90)
    print("C. 感染部位")
    print("=" * 90)

    # C1. 诊断表感染类诊断
    print("\n--- C1. diseaseDiagnosis 感染类诊断 ---")
    INFECTION_KEYWORDS = [
        "肺炎", "脓毒", "感染", "败血", "菌血", "腹膜炎", "脓肿", "化脓",
        "尿路感染", "胆管炎", "脑膜炎", "蜂窝织炎", "感染性休克", "VAP",
        "CRBSI", "CAUTI", "导管相关", "手术部位", "切口感染",
    ]
    diag_names = Counter()
    for doc in sc.diseaseDiagnosis.find(
        {"valid": {"$ne": False}},
        {"diseaseType": 1}
    ).limit(5000):
        dt = doc.get("diseaseType", "")
        if dt: diag_names[dt] += 1
    print("  diseaseType 全量(非 invalid):")
    for name, cnt in diag_names.most_common(30):
        print(f"    {name:50s}  {cnt:5d}")

    # C2. 病原学送检标本类型
    print("\n--- C2. 病原学送检标本类型 ---")
    if dc is not None:
        sample_orders = list(dc["VI_ICU_ZYYZ"].find(
            {"yaoType": {"$in": LAB_ORDER_TYPES},
             "orderName": {"$regex": "培养|涂片|药敏"}},
            {"orderName": 1}
        ).limit(200))
        order_name_counter = Counter()
        for o in sample_orders:
            name = o.get("orderName", "")
            # 尝试提取标本类型
            order_name_counter[name[:40]] += 1
        print(f"  培养/涂片/药敏类医嘱样例 top20:")
        for name, cnt in order_name_counter.most_common(20):
            print(f"    {name:50s}  {cnt:5d}")

    # C3. 是否有感染部位字段
    print("\n--- C3. 感染部位字段探测 ---")
    # diseaseDiagnosis 有没有部位字段
    sample_diag = list(sc.diseaseDiagnosis.find().limit(5))
    all_diag_fields = set()
    for d in sample_diag:
        all_diag_fields.update(d.keys())
    print(f"  diseaseDiagnosis 全部字段: {sorted(all_diag_fields)}")
    # 看 septicShock 子结构
    for d in sample_diag:
        ss = d.get("septicShock")
        if ss:
            print(f"  septicShock 子文档: {json.dumps(ss, ensure_ascii=False, default=str)[:300]}")
            break

    # ============================================================
    # D. Bundle 第二步
    # ============================================================
    print("\n" + "=" * 90)
    print("D. Bundle 第二步")
    print("=" * 90)

    # D1. VI_ZYYZ vs VI_ICU_ZYYZ
    print("\n--- D1. VI_ZYYZ vs VI_ICU_ZYYZ ---")
    if dc is not None:
        for coll_name in ["VI_ZYYZ", "VI_ICU_ZYYZ"]:
            if coll_name in dc.list_collection_names():
                cnt = dc[coll_name].count_documents({}, limit=10000)
                sample = list(dc[coll_name].find().limit(1))
                fields = sorted(sample[0].keys()) if sample else []
                print(f"  {coll_name}: {cnt}+ docs, fields={fields}")
            else:
                print(f"  {coll_name}: NOT EXISTS")

    # D2. VI_ICU_ZYYZ 完整字段 + reviewTime
    print("\n--- D2. VI_ICU_ZYYZ 完整字段清单 ---")
    if dc is not None:
        sample = list(dc["VI_ICU_ZYYZ"].find().limit(10))
        if sample:
            all_fields = sorted(sample[0].keys())
            print(f"  完整字段清单({len(all_fields)}个): {all_fields}")

            # reviewTime 非空率
            rt_count = dc["VI_ICU_ZYYZ"].count_documents(
                {"reviewTime": {"$exists": True, "$ne": None}}, limit=10000)
            print(f"  reviewTime 非空: {rt_count}+ / total(sampled)")

            # 所有时间相关字段
            TIME_FIELDS = ["orderTime", "reviewTime", "planTime", "stopTime", "cancelTime"]
            for f in TIME_FIELDS:
                cnt = dc["VI_ICU_ZYYZ"].count_documents(
                    {f: {"$exists": True, "$ne": None}}, limit=10000)
                print(f"  {f} 非空: {cnt}+ docs")

            # 样例
            for s in sample[:3]:
                print(f"  样例: {json.dumps({k: safe_str(v, 40) for k, v in s.items()}, ensure_ascii=False)}")

    # D3. 血培养记录量
    print("\n--- D3. 血培养 ---")
    if dc is not None:
        bc_count = dc["VI_ICU_ZYYZ"].count_documents(
            {"orderName": {"$regex": "血培养"}, "status": {"$in": EXECUTED_ORDER_STATUSES}},
            limit=10000)
        print(f"  VI_ICU_ZYYZ orderName含'血培养'且已执行: {bc_count}+ docs")
        # ICU-06 可复用函数
        print("  可复用函数/常量:")
        print("    - db.CULTURE_KEYWORDS_FULL (关键词列表)")
        print("    - db._keyword_regex() (构建正则)")
        print("    - db.get_icu06_data() 中的 VI_ICU_ZYYZ 查询逻辑")

    # D4. 抗生素识别
    print("\n--- D4. 抗生素识别 ---")
    abx_codes = [d.get("code") for d in sc.configDrug.find(
        {"classification": "抗生素"}, {"code": 1})]
    print(f"  configDrug classification='抗生素': {len(abx_codes)} 个 code")

    # 抗生素执行记录时间字段
    if abx_codes:
        abx_sample = list(sc.drugExe.find(
            {"drugList.code": {"$in": abx_codes[:50]}},
            {"startTime": 1, "exeTime": 1, "hisStartTime": 1, "status": 1, "drugList": 1}
        ).limit(50))
        print(f"  抗生素执行记录样例: {len(abx_sample)}")
        time_stats = {"startTime": 0, "exeTime": 0, "hisStartTime.exeTime": 0}
        for doc in abx_sample:
            if doc.get("startTime"): time_stats["startTime"] += 1
            if doc.get("exeTime"): time_stats["exeTime"] += 1
            hs = doc.get("hisStartTime")
            if isinstance(hs, dict) and hs.get("exeTime"):
                time_stats["hisStartTime.exeTime"] += 1
        for f, cnt in time_stats.items():
            print(f"    {f} 非空: {cnt}/{len(abx_sample)}")

    # D5. 窗口内抗生素/血培养多条统计
    print("\n--- D5. 窗口内多条记录统计 ---")
    # 取20个有抗生素记录的患者
    if abx_codes:
        pids_with_abx = []
        for doc in sc.drugExe.find(
            {"drugList.code": {"$in": abx_codes[:50]}, "status": "finished"},
            {"pid": 1, "startTime": 1}
        ).sort("startTime", -1).limit(200):
            pid = doc.get("pid")
            if pid and pid not in pids_with_abx:
                pids_with_abx.append(pid)
            if len(pids_with_abx) >= 20:
                break

        multi_count = 0
        time_gaps = []
        for pid in pids_with_abx:
            docs = list(sc.drugExe.find(
                {"pid": pid, "drugList.code": {"$in": abx_codes[:50]}, "status": "finished"},
                {"startTime": 1}
            ).sort("startTime", 1))
            if len(docs) > 1:
                multi_count += 1
                times = [d["startTime"] for d in docs if d.get("startTime")]
                if len(times) >= 2:
                    gap_h = (times[-1] - times[0]).total_seconds() / 3600
                    time_gaps.append(gap_h)
        print(f"  20例中有抗生素多条记录: {multi_count}/20")
        stats_row(time_gaps, "首剂-最晚剂时间差(h)")

    # ============================================================
    # E. Bundle 第三步(液体)
    # ============================================================
    print("\n" + "=" * 90)
    print("E. Bundle 第三步(液体)")
    print("=" * 90)

    # E1. 剂量字段
    print("\n--- E1. drugExe 剂量字段 ---")
    dose_units = Counter()
    dose_ml_count = 0
    dose_total = 0
    for doc in sc.drugExe.find(
        {"status": "finished"},
        {"drugList": 1}
    ).limit(1000):
        for dl in doc.get("drugList", []):
            unit = str(dl.get("unit", "")).strip()
            dose = dl.get("dose")
            if unit:
                dose_units[unit] += 1
                dose_total += 1
            if unit == "ml" and dose is not None:
                dose_ml_count += 1
    topn(dose_units, 15, "drugList.unit 分布")
    print(f"  可直接累加为ml的记录: {dose_ml_count}/{dose_total}")

    # E2. 晶体/胶体/抗生素溶媒/微量泵识别
    print("\n--- E2. 液体分类识别 ---")
    CRYSTALLOID_KW = ["氯化钠", "葡萄糖", "林格", "乳酸钠", "碳酸氢钠"]
    COLLOID_KW = ["羟乙基淀粉", "白蛋白", "血浆", "明胶", "右旋糖酐"]
    # 抽样看 drugList.name
    for doc in sc.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(5):
        for dl in doc.get("drugList", [])[:3]:
            name = str(dl.get("name", ""))
            unit = str(dl.get("unit", ""))
            dose = dl.get("dose")
            print(f"    name={name[:50]}, dose={dose}, unit={unit}")

    # ============================================================
    # F. SOFA / SOFA-2
    # ============================================================
    print("\n" + "=" * 90)
    print("F. SOFA / SOFA-2")
    print("=" * 90)

    # F1. VI_ICU_EXAM_ITEM 关键检验
    print("\n--- F1. VI_ICU_EXAM_ITEM 检验指标 ---")
    if dc is not None:
        LAB_ITEMS = {
            "血小板(PLT)": ["PLT", "plt", "Plt"],
            "总胆红素(TBIL)": ["TBIL", "tbil", "TB", "DBIL", "IBIL"],
            "肌酐(Cr)": ["sCr", "Cr", "CREA", "cr", "Scr"],
            "钾(K)": ["K", "K+", "k"],
            "pH": ["pH", "PH"],
            "HCO3": ["HCO3", "HCO3-", "HCO3std"],
            "乳酸(LAC)": ["LAC", "Lac", "lactate"],
            "WBC": ["WBC", "WBCJS"],
            "CRP": ["CRP", "sCRP"],
            "PCT": ["PCT1"],
        }
        for label, codes in LAB_ITEMS.items():
            for code in codes:
                cnt = dc["VI_ICU_EXAM_ITEM"].count_documents(
                    {"itemCode": code}, limit=5000)
                if cnt > 0:
                    # 取样看 unit
                    unit_counter = Counter()
                    result_sample = []
                    for doc in dc["VI_ICU_EXAM_ITEM"].find(
                        {"itemCode": code},
                        {"itemCode": 1, "itemName": 1, "result": 1, "unit": 1,
                         "authTime": 1, "hisPid": 1}
                    ).limit(100):
                        u = doc.get("unit", "")
                        unit_counter[u] += 1
                        result_sample.append(doc)

                    print(f"\n  {label} itemCode={code}: {cnt}+ docs")
                    topn(unit_counter, 5, f"{code} unit分布")
                    for s in result_sample[:2]:
                        print(f"    样例: itemName={s.get('itemName')}, result={s.get('result')}, "
                              f"unit={s.get('unit')}, authTime={fmt_dt(s.get('authTime'))}")
                    break  # 找到一个有效 code 就行

    # F2. 体重
    print("\n--- F2. 患者体重 ---")
    weight_count = sc.patient.count_documents(
        {"weight": {"$exists": True, "$ne": None, "$gt": 0}}, limit=10000)
    total_pat = sc.patient.count_documents({}, limit=10000)
    print(f"  patient.weight > 0: {weight_count}/{total_pat}")
    weight_vals = []
    for doc in sc.patient.find({"weight": {"$gt": 0}}, {"weight": 1}).limit(500):
        try:
            weight_vals.append(float(doc["weight"]))
        except: pass
    stats_row(weight_vals, "体重(kg)")

    # F3. 尿量
    print("\n--- F3. 尿量 ---")
    URINE_CODES = ["param_niaoLiang", "param_urine", "param_niaoLiang_hour"]
    for code in URINE_CODES:
        cnt = sc.bedside.count_documents({"code": code, "valid": True}, limit=5000)
        if cnt > 0:
            print(f"  bedside {code}: {cnt}+ docs")
            sample = list(sc.bedside.find(
                {"code": code, "valid": True},
                {"pid": 1, "strVal": 1, "time": 1}
            ).limit(5))
            for s in sample:
                print(f"    pid={s.get('pid','')[:20]}, strVal={s.get('strVal')}, "
                      f"time={fmt_dt(s.get('time'))}")

            # 尿量口径: 看是否每小时
            # 取一个患者看24h内记录
            pid_sample = sc.bedside.find_one(
                {"code": code, "valid": True}, {"pid": 1, "time": 1})
            if pid_sample:
                pid = pid_sample["pid"]
                t = pid_sample["time"]
                urine_docs = list(sc.bedside.find(
                    {"pid": pid, "code": code, "valid": True,
                     "time": {"$gte": t - timedelta(hours=24), "$lte": t}},
                    {"strVal": 1, "time": 1}
                ).sort("time", 1))
                print(f"  患者 {pid[:20]} 24h内尿量记录: {len(urine_docs)} 条")
                if len(urine_docs) >= 2:
                    gaps = [(urine_docs[i+1]["time"] - urine_docs[i]["time"]).total_seconds()/3600
                            for i in range(len(urine_docs)-1)]
                    stats_row(gaps, "尿量记录间隔(h)")

    # F4. SOFA 分项时间范围可用性
    print("\n--- F4. SOFA 分项时间范围可用性 ---")
    # 取 20 个有 bGATemp 的患者作为样本
    bga_pids = []
    for doc in sc.bGATemp.find({}, {"eventExe.pid": 1}).limit(100):
        pid = (doc.get("eventExe") or {}).get("pid")
        if pid and pid not in bga_pids:
            bga_pids.append(pid)
        if len(bga_pids) >= 20:
            break

    if bga_pids:
        sofa_components = {
            "呼吸(P/F)": {"coll": "bGATemp", "code": "param_bg_P/Fratio", "max_staleness_h": 4},
            "凝血(PLT)": {"source": "dc_exam", "codes": ["PLT"], "max_staleness_h": 12},
            "肝(TBIL)": {"source": "dc_exam", "codes": ["TBIL"], "max_staleness_h": 12},
            "循环(MAP)": {"coll": "bedside", "code": "param_ibp_m", "max_staleness_h": 1},
            "神经(GCS)": {"coll": "bedside", "code": "param_score_gcs_obs", "max_staleness_h": 8},
            "肾(Cr)": {"source": "dc_exam", "codes": ["sCr", "Cr", "CREA"], "max_staleness_h": 12},
        }

        for comp_name, cfg in sofa_components.items():
            print(f"\n  --- {comp_name} (max_staleness={cfg['max_staleness_h']}h) ---")

    # F5. PaO2/FiO2 配对
    print("\n--- F5. PaO2/FiO2 配对 ---")
    # 看 param_bg_P/Fratio 是否直接存在(已在 A1 查过)
    # 看 PaO2 和 FiO2 是否同一条 bGATemp 记录
    paired = 0
    unpaired_pao2 = 0
    unpaired_fio2 = 0
    for doc in sc.bGATemp.find({}, {"bedsides": 1}).limit(500):
        codes = set()
        for b in doc.get("bedsides", []):
            codes.add(b.get("code"))
        if "param_bg_pO2" in codes and "param_bg_FiO2" in codes:
            paired += 1
        elif "param_bg_pO2" in codes:
            unpaired_pao2 += 1
        elif "param_bg_FiO2" in codes:
            unpaired_fio2 += 1
    print(f"  500条血气中: PaO2+FiO2同条={paired}, 仅PaO2={unpaired_pao2}, 仅FiO2={unpaired_fio2}")

    # F6. 呼吸支持
    print("\n--- F6. 呼吸支持识别 ---")
    VENT_CODES = ["param_XiYangTuJing", "param_vent_mode", "param_vent_type"]
    for code in VENT_CODES:
        cnt = sc.bedside.count_documents({"code": code, "valid": True}, limit=5000)
        if cnt > 0:
            print(f"  bedside {code}: {cnt}+ docs")
            val_counter = Counter()
            for doc in sc.bedside.find(
                {"code": code, "valid": True}, {"strVal": 1}
            ).limit(500):
                v = doc.get("strVal", "")
                if v: val_counter[v] += 1
            topn(val_counter, 15, f"{code} 取值分布")

    # ECMO
    print("\n  --- ECMO ---")
    ECMO_KEYWORDS = ["ECMO", "ecmo", "体外膜肺"]
    for coll_name in ["tubeExe", "bedside"]:
        for kw in ECMO_KEYWORDS:
            cnt = sc[coll_name].count_documents(
                {"$or": [
                    {"type": {"$regex": kw, "$options": "i"}},
                    {"strVal": {"$regex": kw, "$options": "i"}},
                    {"code": {"$regex": kw, "$options": "i"}},
                ]}, limit=100)
            if cnt > 0:
                print(f"  {coll_name} 含'{kw}': {cnt}+ docs")

    # F7. RRT
    print("\n--- F7. RRT(CRRT/血透/腹透) ---")
    RRT_KEYWORDS = ["CRRT", "crrt", "血透", "血液透析", "腹透", "腹膜透析",
                    "血滤", "血液滤过", "透析", "连续肾脏替代"]
    for coll_name in ["tubeExe", "bedside"]:
        for kw in RRT_KEYWORDS:
            try:
                cnt = sc[coll_name].count_documents(
                    {"$or": [
                        {"type": {"$regex": kw}},
                        {"strVal": {"$regex": kw}},
                    ]}, limit=100)
                if cnt > 0:
                    print(f"  {coll_name} 含'{kw}': {cnt}+ docs")
            except: pass

    # F8. 镇静用药
    print("\n--- F8. 镇静用药 ---")
    SEDATIVE_KW = ["丙泊酚", "咪达唑仑", "右美托咪定", "芬太尼", "瑞芬太尼",
                   "舒芬太尼", "氯胺酮", "劳拉西泮", "地西泮"]
    sed_regex = "|".join(SEDATIVE_KW)
    sed_count = sc.drugExe.count_documents(
        {"drugList.name": {"$regex": sed_regex}}, limit=5000)
    print(f"  drugExe 含镇静药: {sed_count}+ docs")

    # F9. 升压药剂量换算
    print("\n--- F9. 升压药剂量与换算 ---")
    VASO_KW = ["去甲肾上腺素", "肾上腺素", "多巴胺", "多巴酚丁胺", "去甲"]
    vaso_regex = "|".join(VASO_KW)
    vaso_sample = list(sc.drugExe.find(
        {"drugList.name": {"$regex": vaso_regex}},
        {"drugList": 1, "startTime": 1, "drugActionList": 1, "weight": 1, "liquidAmount": 1,
         "recommendSpeed": 1, "recommendSpeedUnit": 1}
    ).limit(20))
    print(f"  升压药执行记录样例: {len(vaso_sample)}")
    for doc in vaso_sample[:5]:
        print(f"\n    startTime={fmt_dt(doc.get('startTime'))}")
        print(f"    weight={doc.get('weight')}")
        print(f"    liquidAmount={doc.get('liquidAmount')} {doc.get('liquidAmountUnit','')}")
        print(f"    recommendSpeed={doc.get('recommendSpeed')} {doc.get('recommendSpeedUnit','')}")
        for dl in doc.get("drugList", [])[:2]:
            print(f"    drug: name={dl.get('name','')[:40]}, dose={dl.get('dose')}, "
                  f"unit={dl.get('unit')}, spec={dl.get('spec','')[:30]}")
        for al in (doc.get("drugActionList") or [])[:2]:
            print(f"    action: {json.dumps(al, ensure_ascii=False, default=str)[:150]}")

    # F10. 连续输注持续时长
    print("\n--- F10. 连续输注持续时长 ---")
    # 看 drugExe 有没有 endTime
    end_time_count = sc.drugExe.count_documents(
        {"endTime": {"$exists": True, "$ne": None}}, limit=5000)
    total_drug = sc.drugExe.count_documents({}, limit=10000)
    print(f"  drugExe.endTime 非空: {end_time_count}/{total_drug}")

    # drugActionList 结构(用于判断持续输注)
    for doc in vaso_sample[:3]:
        actions = doc.get("drugActionList") or []
        if actions:
            print(f"  drugActionList 样例:")
            for a in actions[:3]:
                print(f"    {json.dumps(a, ensure_ascii=False, default=str)[:200]}")
            break

    # F11. SmartCare 自带 SOFA
    print("\n--- F11. SmartCare 自带 SOFA 评分 ---")
    SOFA_SCORE_TYPES = ["sofa", "SOFA", "sofaScore", "sofa_score", "sofa-2", "SOFA2"]
    for st in SOFA_SCORE_TYPES:
        cnt = sc.score.count_documents({"scoreType": st}, limit=1000)
        if cnt > 0:
            print(f"  score scoreType={st}: {cnt}+ docs")
            sample = list(sc.score.find(
                {"scoreType": st},
                {"pid": 1, "total": 1, "time": 1, "scoreType": 1}
            ).limit(5))
            for s in sample:
                print(f"    pid={s.get('pid','')[:20]}, total={s.get('total')}, "
                      f"time={fmt_dt(s.get('time'))}")

    # 列出所有 sofa 相关 scoreType
    sofa_types = Counter()
    for doc in sc.score.find({}, {"scoreType": 1}).limit(10000):
        st = doc.get("scoreType", "")
        if "sofa" in st.lower() or "SOFA" in st:
            sofa_types[st] += 1
    if sofa_types:
        print(f"  SOFA相关 scoreType: {dict(sofa_types)}")
    else:
        print("  未找到 SOFA 相关 scoreType")

    # ============================================================
    # G. 现有实现盘点
    # ============================================================
    print("\n" + "=" * 90)
    print("G. 现有实现盘点")
    print("=" * 90)

    # G1. infectionShockV2 完整字段
    print("\n--- G1. infectionShockV2 完整字段与填写率 ---")
    total_shock = sc.infectionShockV2.count_documents({})
    print(f"  总文档数: {total_shock}")

    # 逐文档打印完整结构
    for doc in sc.infectionShockV2.find().limit(5):
        did = doc.get("diseaseId", "")
        g1 = doc.get("group1H") or {}
        g3 = doc.get("group3H") or {}
        g6 = doc.get("group6H") or {}
        print(f"\n  diseaseId={did}")
        print(f"    group1H keys={sorted(g1.keys()) if g1 else 'EMPTY'}")
        if g1: print(f"    group1H = {json.dumps(g1, ensure_ascii=False, default=str)[:400]}")
        print(f"    group3H keys={sorted(g3.keys()) if g3 else 'EMPTY'}")
        if g3: print(f"    group3H = {json.dumps(g3, ensure_ascii=False, default=str)[:400]}")
        print(f"    group6H keys={sorted(g6.keys()) if g6 else 'EMPTY'}")
        if g6: print(f"    group6H = {json.dumps(g6, ensure_ascii=False, default=str)[:400]}")

    # 逐字段填写率
    ALL_SUB_FIELDS = set()
    for doc in sc.infectionShockV2.find():
        for gk in ["group1H", "group3H", "group6H"]:
            g = doc.get(gk) or {}
            for k in g:
                ALL_SUB_FIELDS.add(f"{gk}.{k}")

    print(f"\n  所有子字段: {sorted(ALL_SUB_FIELDS)}")
    for field in sorted(ALL_SUB_FIELDS):
        gk, sk = field.split(".", 1)
        cnt = sc.infectionShockV2.count_documents(
            {f"{gk}.{sk}": {"$exists": True, "$ne": None}})
        print(f"    {field}: {cnt}/{total_shock} ({cnt/total_shock*100:.0f}%)" if total_shock else "")

    # G2. ai_analyzer.extract_sofa_qsofa
    print("\n--- G2. ai_analyzer.extract_sofa_qsofa 返回结构 ---")
    print("  函数定义在 ai_analyzer.py:900")
    print("  返回字段:")
    return_fields = [
        "pid", "his_pid", "weight",
        "sofa_baseline", "sofa_current", "sofa_breakdown", "sofa_items",
        "sofa_is_lower_bound", "missing_domains", "measured",
        "rr", "on_ventilator", "sbp", "gcs", "qsofa",
        "map", "map_time", "vasopressors", "lactate", "lactate_time",
        "t0", "t0_basis", "infection_evidence", "fluid_resuscitation",
    ]
    for f in return_fields:
        print(f"    - {f}")
    print("  qSOFA 被引用位置: ai_analyzer._build_septic_shock_prompt(), _rule_confirm_septic_shock()")
    print("  SOFA 计算方式: 6域评分(resp/coag/liver/cns/renal/cardio), 缺失域不计分")
    print("  T0 计算: compute_sofa_t0() — 首次SOFA急升≥2的时间")

    print("\n" + "=" * 90)
    print("探测完成")
    print("=" * 90)


if __name__ == "__main__":
    main()
