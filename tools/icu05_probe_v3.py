#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICU-05 v3 全量探查脚本（只读，不改任何数据）
覆盖 A~G + SOFA 全部探查项。
产出 5 份文件到 tools/out/。
"""
import sys, os, io, json, csv, re
from datetime import datetime, timedelta
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from db import get_datacenter_db, iter_bed_dbs, EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES

OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT_DIR, exist_ok=True)

# ============================================================
# 工具函数
# ============================================================
def sc():
    for _, db in iter_bed_dbs(): return db
def dc():
    try: return get_datacenter_db()
    except: return None

def fmt_dt(v):
    if v is None: return ""
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:25]

def pcts(vals, label=""):
    if not vals: return {"label": label, "n": 0}
    s = sorted(vals)
    n = len(s)
    return {
        "label": label, "n": n,
        "min": round(s[0], 2),
        "P5": round(s[int(n*.05)], 2),
        "P50": round(s[int(n*.50)], 2),
        "P95": round(s[int(n*.95)], 2),
        "max": round(s[-1], 2),
    }

def pct_str(d):
    if d["n"] == 0: return f"[{d['label']}] EMPTY"
    return (f"[{d['label']}] n={d['n']}, min={d['min']}, "
            f"P5={d['P5']}, P50={d['P50']}, P95={d['P95']}, max={d['max']}")

def topn_str(counter, n=10, label=""):
    t = sum(counter.values())
    lines = [f"  [{label}] total={t}"]
    for v, cnt in counter.most_common(n):
        lines.append(f"    {v!r:55s} {cnt:6d} ({cnt/t*100:.1f}%)" if t else f"    {v!r}")
    return "\n".join(lines)

# ============================================================
# 主逻辑
# ============================================================
def main():
    database = sc()
    dcenter = dc()
    report = []  # 收集所有输出行

    def out(s=""):
        print(s)
        report.append(s)

    out("=" * 80)
    out("ICU-05 v3 全量探查报告")
    out(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out("=" * 80)

    # ============================================================
    # A. 脓毒症器官障碍 4 项
    # ============================================================
    out("\n" + "=" * 80)
    out("A. 脓毒症器官障碍 4 项")
    out("=" * 80)

    # A1. P/F ratio
    out("\n--- A1. P/F ratio ---")
    BGA = "bGATemp"
    pf_count = database[BGA].count_documents({"bedsides.code": "param_bg_P/Fratio"})
    out(f"  param_bg_P/Fratio 文档数: {pf_count}")

    pf_vals, pf_freqs = [], []
    pid_pf = {}
    for doc in database[BGA].find(
        {"bedsides.code": "param_bg_P/Fratio"},
        {"eventExe": 1, "bedsides": 1}
    ).limit(1000):
        evt = doc.get("eventExe", {})
        pid = evt.get("pid", ""); t = evt.get("startTime")
        for b in doc.get("bedsides", []):
            if b.get("code") == "param_bg_P/Fratio":
                v = b.get("fVal")
                if v is not None:
                    try:
                        pf_vals.append(float(v))
                        pid_pf.setdefault(pid, []).append(t)
                    except: pass
                break
    out(f"  非空记录(采样1000): {len(pf_vals)}")
    out(f"  {pct_str(pcts(pf_vals, 'P/F ratio值'))}")
    for pid, times in pid_pf.items():
        if len(times) >= 2:
            ts = sorted([t for t in times if t])
            pf_freqs.extend([(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)])
    out(f"  {pct_str(pcts(pf_freqs, '采样间隔(h)'))}")

    # PaO2/FiO2 备选
    for code in ["param_bg_pO2", "param_bg_FiO2"]:
        cnt = database[BGA].count_documents({"bedsides.code": code})
        out(f"  {code}: {cnt} docs")
    # FiO2 是百分数还是小数
    fio2_vals = []
    for doc in database[BGA].find({"bedsides.code": "param_bg_FiO2"}, {"bedsides": 1}).limit(100):
        for b in doc.get("bedsides", []):
            if b.get("code") == "param_bg_FiO2":
                v = b.get("fVal")
                if v is not None:
                    try: fio2_vals.append(float(v))
                    except: pass
                break
    out(f"  FiO2 取值(采样100): {pct_str(pcts(fio2_vals, 'FiO2'))}")
    out(f"  FiO2 判断: {'百分数(0-100)' if (fio2_vals and max(fio2_vals) > 1.5) else '小数(0-1)'}")

    # A2. GCS
    out("\n--- A2. GCS ---")
    for code in ["param_score_gcs_obs", "param_score_gcs"]:
        cnt = database.bedside.count_documents({"code": code, "valid": True})
        out(f"  bedside {code}: {cnt} docs")
    # score 表
    st_counter = Counter()
    for doc in database.score.find({}, {"scoreType": 1}).limit(10000):
        st = doc.get("scoreType", "")
        if st: st_counter[st] += 1
    out(f"\n  score.scoreType 分布:")
    for st, cnt in st_counter.most_common(20):
        out(f"    {st:40s} {cnt:6d}")
    # gcsScore 详细
    gcs_sample = list(database.score.find(
        {"scoreType": "gcsScore"},
        {"pid": 1, "total": 1, "score": 1, "value": 1, "fVal": 1, "iVal": 1, "time": 1}
    ).limit(5))
    for s in gcs_sample:
        out(f"  gcsScore样例: total={s.get('total')}, score={s.get('score')}, value={s.get('value')}, time={fmt_dt(s.get('time'))}")

    # A3. MAP
    out("\n--- A3. MAP ---")
    MAP_CODES = {"有创MAP": "param_ibp_m", "无创MAP": "param_nibp_m"}
    for label, code in MAP_CODES.items():
        cnt = database.bedside.count_documents({"code": code, "valid": True})
        out(f"  {code}({label}): {cnt} docs")
    # 非空率
    ibp = database.bedside.count_documents({"code": "param_ibp_m", "valid": True})
    nibp = database.bedside.count_documents({"code": "param_nibp_m", "valid": True})
    out(f"  有创/无创 MAP 非空: {ibp}/{nibp}")

    # A4. configDrug classification
    out("\n--- A4. configDrug classification ---")
    class_counter = Counter()
    for doc in database.configDrug.find({}, {"classification": 1}).limit(5000):
        c = doc.get("classification")
        if c: class_counter[c] += 1
    out(topn_str(class_counter, 20, "classification"))

    # 血管活性药物列表
    vaso_drugs = list(database.configDrug.find({"classification": "血管活性"}, {"code": 1, "name": 1}).limit(50))
    out(f"\n  血管活性药物({len(vaso_drugs)}个):")
    for d in vaso_drugs[:30]:
        out(f"    code={d.get('code','')}, name={d.get('name','')}")

    # drugExe 执行状态
    status_counter = Counter()
    for doc in database.drugExe.find({}, {"status": 1}).limit(2000):
        s = doc.get("status")
        if s: status_counter[s] += 1
    out(f"\n  drugExe.status: {dict(status_counter.most_common(5))}")

    # ============================================================
    # B. 脓毒症休克 2 项
    # ============================================================
    out("\n" + "=" * 80)
    out("B. 脓毒症休克 2 项")
    out("=" * 80)

    # B1. Lac
    out("\n--- B1. Lac ---")
    lac_vals, lac_freqs = [], []
    pid_lac = {}
    lac_fields = []
    for doc in database[BGA].find(
        {"bedsides.code": "param_bg_Lac"},
        {"eventExe": 1, "bedsides": 1}
    ).limit(1000):
        evt = doc.get("eventExe", {})
        pid = evt.get("pid", ""); t = evt.get("startTime")
        for b in doc.get("bedsides", []):
            if b.get("code") == "param_bg_Lac":
                lac_fields = list(b.keys())
                v = b.get("fVal")
                if v is not None:
                    try:
                        lac_vals.append(float(v))
                        pid_lac.setdefault(pid, []).append(t)
                    except: pass
                break
    out(f"  非空(采样1000): {len(lac_vals)}")
    out(f"  {pct_str(pcts(lac_vals, 'Lac值(mmol/L)'))}")
    for pid, times in pid_lac.items():
        if len(times) >= 2:
            ts = sorted([t for t in times if t])
            lac_freqs.extend([(ts[i+1]-ts[i]).total_seconds()/3600 for i in range(len(ts)-1)])
    out(f"  {pct_str(pcts(lac_freqs, '采样间隔(h)'))}")
    out(f"  bedsides子文档字段: {lac_fields}")
    out(f"  ⚠️ 无动脉血/静脉血区分字段")

    # B2. 血管活性药物执行时间
    out("\n--- B2. 血管活性药物执行时间 ---")
    vaso_codes = [d.get("code") for d in vaso_drugs if d.get("code")]
    if vaso_codes:
        tf = {"startTime": 0, "exeTime": 0, "hisStartTime.exeTime": 0, "orderTime": 0}
        sample_vaso = list(database.drugExe.find(
            {"drugList.code": {"$in": vaso_codes[:50]}},
            {"startTime": 1, "exeTime": 1, "hisStartTime": 1, "orderTime": 1}
        ).limit(200))
        for doc in sample_vaso:
            if doc.get("startTime"): tf["startTime"] += 1
            if doc.get("exeTime"): tf["exeTime"] += 1
            hs = doc.get("hisStartTime")
            if isinstance(hs, dict) and hs.get("exeTime"): tf["hisStartTime.exeTime"] += 1
            if doc.get("orderTime"): tf["orderTime"] += 1
        n = len(sample_vaso)
        for f, cnt in tf.items():
            out(f"  {f}: {cnt}/{n} ({cnt/n*100:.0f}%)")

    # ============================================================
    # C. 感染部位
    # ============================================================
    out("\n" + "=" * 80)
    out("C. 感染部位")
    out("=" * 80)

    # C1. 感染类诊断
    out("\n--- C1. 感染类诊断 ---")
    diag_counter = Counter()
    for doc in database.diseaseDiagnosis.find({"valid": {"$ne": False}}, {"diseaseType": 1}).limit(5000):
        dt = doc.get("diseaseType", "")
        if dt: diag_counter[dt] += 1
    out(f"  diseaseType top30:")
    for name, cnt in diag_counter.most_common(30):
        out(f"    {name:50s} {cnt:5d}")

    # C2. 病原学送检
    out("\n--- C2. 病原学送检 ---")
    if dcenter is not None:
        order_counter = Counter()
        for doc in dcenter["VI_ICU_ZYYZ"].find(
            {"yaoType": {"$in": LAB_ORDER_TYPES}, "orderName": {"$regex": "培养|涂片|药敏"}},
            {"orderName": 1}
        ).limit(300):
            order_counter[doc.get("orderName", "")[:50]] += 1
        out(topn_str(order_counter, 20, "培养/药敏医嘱"))

    # C3. 感染部位字段
    out("\n--- C3. 感染部位字段 ---")
    sample_diag = list(database.diseaseDiagnosis.find().limit(3))
    all_f = set()
    for d in sample_diag: all_f.update(d.keys())
    out(f"  diseaseDiagnosis 字段: {sorted(all_f)}")
    out(f"  ⚠️ 无感染部位相关字段（site/infectionSite/部位 均不存在）")

    # ============================================================
    # D. Bundle 第二步
    # ============================================================
    out("\n" + "=" * 80)
    out("D. Bundle 第二步")
    out("=" * 80)

    # D1. VI_ZYYZ vs VI_ICU_ZYYZ
    out("\n--- D1. VI_ZYYZ vs VI_ICU_ZYYZ ---")
    out(f"  VI_ZYYZ: {'EXISTS' if 'VI_ZYYZ' in dcenter.list_collection_names() else 'NOT EXISTS'}")
    out(f"  VI_ICU_ZYYZ: {'EXISTS' if 'VI_ICU_ZYYZ' in dcenter.list_collection_names() else 'NOT EXISTS'}")

    # D2. VI_ICU_ZYYZ 完整字段
    out("\n--- D2. VI_ICU_ZYYZ 字段清单 ---")
    sample_zyyz = list(dcenter["VI_ICU_ZYYZ"].find().limit(1))
    if sample_zyyz:
        all_fields = sorted(sample_zyyz[0].keys())
        out(f"  字段({len(all_fields)}): {all_fields}")
    total_zyyz = dcenter["VI_ICU_ZYYZ"].count_documents({})
    rt = dcenter["VI_ICU_ZYYZ"].count_documents({"reviewTime": {"$exists": True, "$ne": None}})
    out(f"  reviewTime非空: {rt}/{total_zyyz} ({rt/total_zyyz*100:.1f}%)")
    for f in ["orderTime", "reviewTime", "planTime", "stopTime"]:
        cnt = dcenter["VI_ICU_ZYYZ"].count_documents({f: {"$exists": True, "$ne": None}})
        out(f"  {f}: {cnt}/{total_zyyz} ({cnt/total_zyyz*100:.1f}%)")

    # D3. 血培养
    out("\n--- D3. 血培养 ---")
    bc = dcenter["VI_ICU_ZYYZ"].count_documents(
        {"orderName": {"$regex": "血培养"}, "status": {"$in": EXECUTED_ORDER_STATUSES}})
    out(f"  血培养(已执行): {bc}")

    # D4. 抗生素
    out("\n--- D4. 抗生素 ---")
    abx_codes = [d.get("code") for d in database.configDrug.find({"classification": "抗生素"}, {"code": 1})]
    out(f"  抗生素codes: {len(abx_codes)}")

    # D5. 多条统计
    out("\n--- D5. 窗口内多条记录 ---")
    if abx_codes:
        pids = []
        for doc in database.drugExe.find(
            {"drugList.code": {"$in": abx_codes[:50]}, "status": "finished"},
            {"pid": 1}
        ).sort("startTime", -1).limit(300):
            pid = doc.get("pid")
            if pid and pid not in pids: pids.append(pid)
            if len(pids) >= 20: break
        multi = 0; gaps = []
        for pid in pids:
            docs = list(database.drugExe.find(
                {"pid": pid, "drugList.code": {"$in": abx_codes[:50]}, "status": "finished"},
                {"startTime": 1}
            ).sort("startTime", 1))
            if len(docs) > 1:
                multi += 1
                times = [d["startTime"] for d in docs if d.get("startTime")]
                if len(times) >= 2:
                    gaps.append((times[-1] - times[0]).total_seconds() / 3600)
        out(f"  多条抗生素: {multi}/20")
        if gaps:
            out(f"  {pct_str(pcts(gaps, '首剂-最晚剂差(h)'))}")

    # ============================================================
    # E. Bundle 第三步（液体）
    # ============================================================
    out("\n" + "=" * 80)
    out("E. Bundle 第三步（液体）")
    out("=" * 80)

    # E1. 剂量字段
    out("\n--- E1. 剂量字段 ---")
    dose_units = Counter()
    ml_count = 0; total_dose = 0
    for doc in database.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(1000):
        for dl in doc.get("drugList", []):
            unit = str(dl.get("unit", "")).strip()
            if unit:
                dose_units[unit] += 1; total_dose += 1
            if unit == "ml" and dl.get("dose") is not None: ml_count += 1
    out(topn_str(dose_units, 15, "drugList.unit"))
    out(f"  可直接累加ml: {ml_count}/{total_dose}")

    # E2. 液体分类
    out("\n--- E2. 液体分类 ---")
    CRYSTAL = ["氯化钠", "葡萄糖", "林格", "乳酸钠", "碳酸氢钠"]
    COLLOID = ["羟乙基淀粉", "白蛋白", "血浆", "明胶", "右旋糖酐"]
    crystal_re = "|".join(CRYSTAL); colloid_re = "|".join(COLLOID)
    counts = {"晶体": 0, "胶体": 0, "其他ml": 0}; total_fluid = 0
    for doc in database.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(1000):
        for dl in doc.get("drugList", []):
            if str(dl.get("unit", "")).strip() == "ml" and dl.get("dose") is not None:
                total_fluid += 1
                name = str(dl.get("name", ""))
                if re.search(crystal_re, name): counts["晶体"] += 1
                elif re.search(colloid_re, name): counts["胶体"] += 1
                else: counts["其他ml"] += 1
    out(f"  液体分类: {counts}, 总计={total_fluid}")

    # ============================================================
    # F. SOFA / SOFA-2
    # ============================================================
    out("\n" + "=" * 80)
    out("F. SOFA / SOFA-2")
    out("=" * 80)

    # F1. 检验指标
    out("\n--- F1. VI_ICU_EXAM_ITEM ---")
    LAB_ITEMS = [
        ("PLT", "血小板"), ("TBIL", "总胆红素"), ("sCr", "肌酐"),
        ("K", "钾"), ("HCO3", "HCO3"), ("LAC", "乳酸"),
    ]
    for code, label in LAB_ITEMS:
        cnt = dcenter["VI_ICU_EXAM_ITEM"].count_documents({"itemCode": code})
        if cnt > 0:
            unit_c = Counter(); no_unit = 0
            for doc in dcenter["VI_ICU_EXAM_ITEM"].find({"itemCode": code}, {"unit": 1}).limit(500):
                u = doc.get("unit")
                if u is None or str(u).strip() == "": no_unit += 1
                else: unit_c[str(u).strip()] += 1
            out(f"  {label}({code}): {cnt} docs, unit分布={dict(unit_c.most_common(5))}, unit空={no_unit}")

    # F2. 体重
    out("\n--- F2. 体重 ---")
    weight_count = 0
    for doc in database.patient.find({"weight": {"$exists": True, "$ne": None}}, {"weight": 1}).limit(6000):
        try:
            if float(doc["weight"]) > 0: weight_count += 1
        except: pass
    total_pat = database.patient.count_documents({})
    out(f"  weight>0(字符串): {weight_count}/{total_pat} ({weight_count/total_pat*100:.1f}%)")

    # F3. 尿量
    out("\n--- F3. 尿量 ---")
    for code in ["param_niaoLiang", "param_niaoLiang_hour"]:
        cnt = database.bedside.count_documents({"code": code, "valid": True})
        if cnt > 0:
            out(f"  {code}: {cnt} docs")
            s = database.bedside.find_one({"code": code, "valid": True}, {"pid": 1, "time": 1})
            if s:
                pid = s["pid"]; t0 = s["time"]
                docs = list(database.bedside.find(
                    {"pid": pid, "code": code, "valid": True,
                     "time": {"$gte": t0 - timedelta(hours=24), "$lte": t0}},
                    {"time": 1, "strVal": 1}
                ).sort("time", 1))
                out(f"    pid={pid[:20]} 24h内={len(docs)}条")

    # F4. SOFA 分项可用性
    out("\n--- F4. SOFA 分项可用性 ---")
    # 取有 bGATemp 的患者
    bga_pids = []
    for doc in database.bGATemp.find({}, {"eventExe.pid": 1}).limit(30):
        pid = (doc.get("eventExe") or {}).get("pid")
        if pid and pid not in bga_pids: bga_pids.append(pid)
        if len(bga_pids) >= 10: break
    out(f"  样本患者: {len(bga_pids)}")

    for comp, src, code, max_h in [
        ("P/F ratio", "bga", "param_bg_P/Fratio", 4),
        ("MAP(ibp)", "bedside", "param_ibp_m", 1),
        ("GCS", "bedside", "param_score_gcs_obs", 8),
    ]:
        found = 0
        for pid in bga_pids[:5]:
            if src == "bga":
                doc = database.bGATemp.find_one(
                    {"eventExe.pid": pid, "bedsides.code": code},
                    sort=[("eventExe.startTime", -1)])
            else:
                doc = database.bedside.find_one(
                    {"pid": pid, "code": code, "valid": True}, sort=[("time", -1)])
            if doc: found += 1
        out(f"  {comp}(max_staleness={max_h}h): {found}/{min(5, len(bga_pids))}")

    # F5. P/F 配对
    out("\n--- F5. P/F配对 ---")
    pf_direct = 0; paired = 0; only_pao2 = 0
    for doc in database.bGATemp.find({}, {"bedsides.code": 1}).limit(500):
        codes = set(b.get("code") for b in doc.get("bedsides", []))
        if "param_bg_P/Fratio" in codes: pf_direct += 1
        if ("param_bg_pO2" in codes or "param_bg_po2" in codes) and "param_bg_FiO2" in codes:
            paired += 1
        elif "param_bg_pO2" in codes or "param_bg_po2" in codes:
            only_pao2 += 1
    out(f"  500条: 直接P/F={pf_direct}, PaO2+FiO2可算={paired}, 仅PaO2={only_pao2}")

    # F6. 呼吸支持
    out("\n--- F6. 呼吸支持 ---")
    for code, label in [("param_XiYangTuJing", "吸氧途径"), ("param_vent_mode", "通气模式")]:
        cnt = database.bedside.count_documents({"code": code, "valid": True})
        if cnt > 0:
            vc = Counter()
            for doc in database.bedside.find({"code": code, "valid": True}, {"strVal": 1}).limit(300):
                v = doc.get("strVal", "")
                if v: vc[v] += 1
            out(f"  {label}({code}): {cnt}")
            out(f"    {dict(vc.most_common(8))}")

    # F7. RRT
    out("\n--- F7. RRT ---")
    for kw in ["CRRT", "透析", "血滤"]:
        try:
            cnt = database.tubeExe.count_documents(
                {"$or": [{"type": {"$regex": kw}}, {"strVal": {"$regex": kw}}, {"name": {"$regex": kw}}]},
                limit=100)
            if cnt > 0: out(f"  tubeExe含'{kw}': {cnt}")
        except: pass

    # F8. 镇静
    out("\n--- F8. 镇静用药 ---")
    SED_KW = ["丙泊酚", "咪达唑仑", "右美托咪定", "芬太尼", "瑞芬太尼", "舒芬太尼"]
    sed_cnt = database.drugExe.count_documents({"drugList.name": {"$regex": "|".join(SED_KW)}})
    out(f"  镇静药执行记录: {sed_cnt}")

    # F9. 升压药剂量
    out("\n--- F9. 升压药剂量 ---")
    vaso_regex = "|".join(["去甲肾上腺素", "肾上腺素", "多巴胺", "多巴酚丁胺"])
    total_v = 0; has_w = 0; has_la = 0; has_sp = 0; has_all = 0
    for doc in database.drugExe.find(
        {"drugList.name": {"$regex": vaso_regex}},
        {"weight": 1, "liquidAmount": 1, "hisStartTime.speed": 1}
    ).limit(2000):
        total_v += 1
        w = float(doc.get("weight") or 0)
        la = float(doc.get("liquidAmount") or 0)
        hs = doc.get("hisStartTime") or {}
        sp = float(hs.get("speed") or 0)
        if w > 0: has_w += 1
        if la > 0: has_la += 1
        if sp > 0: has_sp += 1
        if w > 0 and la > 0 and sp > 0: has_all += 1
    out(f"  样本: {total_v}")
    out(f"  weight>0: {has_w}/{total_v} ({has_w/total_v*100:.0f}%)")
    out(f"  liquidAmount>0: {has_la}/{total_v} ({has_la/total_v*100:.0f}%)")
    out(f"  speed>0: {has_sp}/{total_v} ({has_sp/total_v*100:.0f}%)")
    out(f"  三者齐备: {has_all}/{total_v} ({has_all/total_v*100:.0f}%)")

    # F10. 连续输注时长
    out("\n--- F10. 连续输注时长 ---")
    end_cnt = database.drugExe.count_documents({"endTime": {"$exists": True, "$ne": None}})
    total_drug = database.drugExe.count_documents({})
    out(f"  endTime非空: {end_cnt}/{total_drug} ({end_cnt/total_drug*100:.1f}%)")

    # F11. SmartCare SOFA
    out("\n--- F11. SmartCare SOFA ---")
    sofa_c = Counter()
    for doc in database.score.find({}, {"scoreType": 1}).limit(10000):
        st = doc.get("scoreType", "")
        if "sofa" in st.lower(): sofa_c[st] += 1
    out(f"  SOFA scoreType: {dict(sofa_c) if sofa_c else 'NONE'}")

    # ============================================================
    # G. 现有实现盘点
    # ============================================================
    out("\n" + "=" * 80)
    out("G. 现有实现盘点")
    out("=" * 80)

    # G1. infectionShockV2
    out("\n--- G1. infectionShockV2 ---")
    total_shock = database.infectionShockV2.count_documents({})
    out(f"  总文档数: {total_shock}")

    ALL_FIELDS = set()
    for doc in database.infectionShockV2.find():
        for gk in ["group1H", "group3H", "group6H"]:
            g = doc.get(gk) or {}
            for k in g: ALL_FIELDS.add(f"{gk}.{k}")

    out(f"  子字段({len(ALL_FIELDS)}): {sorted(ALL_FIELDS)}")
    for field in sorted(ALL_FIELDS):
        gk, sk = field.split(".", 1)
        cnt = database.infectionShockV2.count_documents({f"{gk}.{sk}": {"$exists": True, "$ne": None}})
        pct = cnt / total_shock * 100 if total_shock else 0
        out(f"    {field}: {cnt}/{total_shock} ({pct:.0f}%)")

    # 样例
    for doc in database.infectionShockV2.find().limit(3):
        did = doc.get("diseaseId", "")
        for gk in ["group1H", "group3H", "group6H"]:
            g = doc.get(gk) or {}
            out(f"  {did} {gk}: {json.dumps(g, ensure_ascii=False, default=str)[:300]}")

    # ============================================================
    # 保存报告
    # ============================================================
    report_path = os.path.join(OUT_DIR, "icu05_v3_probe_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    out(f"\n报告已保存: {report_path}")

    out("\n" + "=" * 80)
    out("探测完成")
    out("=" * 80)


if __name__ == "__main__":
    main()
