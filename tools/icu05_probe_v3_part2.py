#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICU-05 v3 探测 Part 2: E(液), F(SOFA), G(ai_analyzer) — 轻量版
"""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from collections import Counter
from db import (
    get_client, get_datacenter_db, iter_bed_dbs, BED_DB_NAMES,
    DATACENTER_CFG, EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES,
)

def fmt_dt(v):
    if v is None: return "None"
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:30]

def stats_row(values, label=""):
    if not values:
        print(f"  [{label}] EMPTY"); return
    s = sorted(values)
    n = len(s)
    p5 = s[int(n*0.05)] if n > 1 else s[0]
    p50 = s[int(n*0.50)]
    p95 = s[int(n*0.95)] if n > 1 else s[0]
    print(f"  [{label}] n={n}, P5={p5:.1f}, P50={p50:.1f}, P95={p95:.1f}, min={s[0]:.1f}, max={s[-1]:.1f}")

def topn(counter, n=10, label=""):
    total = sum(counter.values())
    print(f"\n  [{label}] top{n} (total={total}):")
    for val, cnt in counter.most_common(n):
        pct = cnt / total * 100 if total else 0
        print(f"    {val!r:50s}  {cnt:6d} ({pct:5.1f}%)")

def get_sc_db():
    for db_name, db in iter_bed_dbs():
        return db
    return None

def main():
    sc = get_sc_db()
    dc = None
    try:
        dc = get_datacenter_db()
    except: pass

    print("=" * 80)
    print("ICU-05 v3 探测 Part 2")
    print("=" * 80)

    # ============================================================
    # E2. 晶体/胶体分类
    # ============================================================
    print("\n--- E2. 液体分类: 晶体/胶体/抗生素 ---")
    CRYSTALLOID_KW = ["氯化钠", "葡萄糖", "林格", "乳酸钠", "碳酸氢钠"]
    COLLOID_KW = ["羟乙基淀粉", "白蛋白", "血浆", "明胶", "右旋糖酐"]
    ABX_KW = ["头孢", "青霉素", "美罗培南", "亚胺培南", "左氧氟沙星",
              "阿奇霉素", "万古霉素", "利奈唑胺", "甲硝唑", "氟康唑"]

    crystal_re = "|".join(CRYSTALLOID_KW)
    colloid_re = "|".join(COLLOID_KW)
    abx_re = "|".join(ABX_KW)

    counts = {"晶体": 0, "胶体": 0, "抗生素": 0, "其他": 0}
    total_fluid = 0
    for doc in sc.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(500):
        for dl in doc.get("drugList", []):
            name = str(dl.get("name", ""))
            unit = str(dl.get("unit", ""))
            dose = dl.get("dose")
            if unit == "ml" and dose is not None:
                total_fluid += 1
                import re
                if re.search(crystal_re, name):
                    counts["晶体"] += 1
                elif re.search(colloid_re, name):
                    counts["胶体"] += 1
                elif re.search(abx_re, name):
                    counts["抗生素"] += 1
                else:
                    counts["其他"] += 1
    print(f"  液体类药物(ml)分类: {counts}, 总计={total_fluid}")

    # ============================================================
    # E3. 晶体液剂量分布
    # ============================================================
    print("\n--- E3. 晶体液剂量分布 ---")
    crystal_doses = []
    for doc in sc.drugExe.find({"status": "finished"}, {"drugList": 1}).limit(500):
        for dl in doc.get("drugList", []):
            name = str(dl.get("name", ""))
            unit = str(dl.get("unit", ""))
            dose = dl.get("dose")
            if unit == "ml" and dose is not None:
                import re
                if re.search(crystal_re, name):
                    try: crystal_doses.append(float(dose))
                    except: pass
    stats_row(crystal_doses, "晶体液单次剂量(ml)")

    # ============================================================
    # F1. VI_ICU_EXAM_ITEM — 轻量只查几个关键指标
    # ============================================================
    print("\n--- F1. VI_ICU_EXAM_ITEM 关键检验 (轻量) ---")
    if dc is not None:
        LAB_ITEMS = [
            ("PLT", "血小板"),
            ("TBIL", "总胆红素"),
            ("sCr", "肌酐"),
            ("Cr", "肌酐(备选)"),
            ("CREA", "肌酐(备选2)"),
            ("LAC", "乳酸(检验)"),
            ("WBCJS", "白细胞"),
            ("PCT1", "降钙素原"),
        ]
        for code, label in LAB_ITEMS:
            try:
                cnt = dc["VI_ICU_EXAM_ITEM"].count_documents(
                    {"itemCode": code}, limit=500)
                if cnt > 0:
                    # 取1条看结构
                    sample = dc["VI_ICU_EXAM_ITEM"].find_one({"itemCode": code})
                    fields = sorted(sample.keys()) if sample else []
                    print(f"  {label}({code}): {cnt}+, fields={fields}")
                    if sample:
                        print(f"    itemName={sample.get('itemName')}, result={sample.get('result')}, "
                              f"unit={sample.get('unit')}, authTime={fmt_dt(sample.get('authTime'))}")
                else:
                    print(f"  {label}({code}): 0 docs")
            except Exception as e:
                print(f"  {label}({code}): ERROR {e}")

    # ============================================================
    # F2. 体重
    # ============================================================
    print("\n--- F2. 体重 ---")
    weight_vals = []
    for doc in sc.patient.find({"weight": {"$gt": 0}}, {"weight": 1}).limit(300):
        try: weight_vals.append(float(doc["weight"]))
        except: pass
    stats_row(weight_vals, "体重(kg)")
    total_pat = sc.patient.count_documents({}, limit=10000)
    print(f"  patient总数: {total_pat}, weight>0: {len(weight_vals)}")

    # ============================================================
    # F3. 尿量
    # ============================================================
    print("\n--- F3. 尿量 ---")
    URINE_CODES = ["param_niaoLiang", "param_urine", "param_niaoLiang_hour"]
    for code in URINE_CODES:
        cnt = sc.bedside.count_documents({"code": code, "valid": True}, limit=5000)
        if cnt > 0:
            # 取一个患者看间隔
            sample = sc.bedside.find_one({"code": code, "valid": True}, {"pid": 1, "time": 1})
            if sample:
                pid = sample["pid"]
                t = sample["time"]
                docs = list(sc.bedside.find(
                    {"pid": pid, "code": code, "valid": True,
                     "time": {"$gte": t - timedelta(hours=24), "$lte": t}},
                    {"time": 1, "strVal": 1}
                ).sort("time", 1))
                print(f"  {code}: {cnt}+, pid={pid[:20]} 24h内={len(docs)}条")
                if len(docs) >= 2:
                    gaps = [(docs[i+1]["time"] - docs[i]["time"]).total_seconds()/3600
                            for i in range(len(docs)-1)]
                    stats_row(gaps, f"{code} 间隔(h)")
                # 值分布
                vals = []
                for d in docs:
                    try: vals.append(float(d.get("strVal", "")))
                    except: pass
                if vals:
                    stats_row(vals, f"{code} 单条值(ml)")

    # ============================================================
    # F4. SOFA 分项过期率
    # ============================================================
    print("\n--- F4. SOFA 分项过期率 (抽样10例) ---")
    # 取10个有bGATemp的患者
    bga_pids = []
    for doc in sc.bGATemp.find({}, {"eventExe.pid": 1}).limit(50):
        pid = (doc.get("eventExe") or {}).get("pid")
        if pid and pid not in bga_pids:
            bga_pids.append(pid)
        if len(bga_pids) >= 10:
            break

    STALENESS = {
        "P/F ratio": ("bGATemp", "param_bg_P/Fratio", 4),
        "MAP": ("bedside", "param_ibp_m", 1),
        "GCS": ("bedside", "param_score_gcs_obs", 8),
    }

    for comp, (src, code, max_h) in STALENESS.items():
        stale = 0
        fresh = 0
        for pid in bga_pids:
            if src == "bGATemp":
                doc = sc.bGATemp.find_one(
                    {"eventExe.pid": pid, "bedsides.code": code},
                    sort=[("eventExe.startTime", -1)])
                if doc:
                    t = (doc.get("eventExe") or {}).get("startTime")
                    if t:
                        # 用最近时间 vs 最早时间的差值判断是否有新鲜数据
                        earliest = sc.bGATemp.find_one(
                            {"eventExe.pid": pid, "bedsides.code": code},
                            sort=[("eventExe.startTime", 1)])
                        if earliest:
                            t0 = (earliest.get("eventExe") or {}).get("startTime")
                            if t0 and (t - t0).total_seconds() / 3600 > max_h:
                                stale += 1
                            else:
                                fresh += 1
            elif src == "bedside":
                doc = sc.bedside.find_one(
                    {"pid": pid, "code": code, "valid": True},
                    sort=[("time", -1)])
                if doc:
                    t = doc.get("time")
                    if t:
                        earliest = sc.bedside.find_one(
                            {"pid": pid, "code": code, "valid": True},
                            sort=[("time", 1)])
                        if earliest:
                            t0 = earliest.get("time")
                            if t0 and (t - t0).total_seconds() / 3600 > max_h:
                                stale += 1
                            else:
                                fresh += 1
        print(f"  {comp} (max_staleness={max_h}h): stale={stale}, fresh={fresh}")

    # ============================================================
    # F5. P/F ratio 配对
    # ============================================================
    print("\n--- F5. P/F ratio: 是否直接存在 vs 需PaO2+FiO2计算 ---")
    # 已在 Part 1 确认 param_bg_P/Fratio 存在且有 1934 条非空记录
    # 这里看 PaO2 和 FiO2 是否同一条 bGATemp 记录
    paired = 0
    only_pao2 = 0
    only_fio2 = 0
    neither = 0
    for doc in sc.bGATemp.find({}, {"bedsides.code": 1}).limit(500):
        codes = set()
        for b in doc.get("bedsides", []):
            codes.add(b.get("code"))
        has_pao2 = "param_bg_pO2" in codes or "param_bg_po2" in codes
        has_fio2 = "param_bg_FiO2" in codes
        has_pf = "param_bg_P/Fratio" in codes
        if has_pf:
            paired += 1
        elif has_pao2 and has_fio2:
            paired += 1
        elif has_pao2:
            only_pao2 += 1
        elif has_fio2:
            only_fio2 += 1
    print(f"  500条血气: 直接有P/F或可算={paired}, 仅PaO2={only_pao2}, 仅FiO2={only_fio2}")

    # ============================================================
    # F6. 呼吸支持
    # ============================================================
    print("\n--- F6. 呼吸支持 ---")
    VENT_CODES = {
        "param_XiYangTuJing": "吸氧途径",
        "param_vent_mode": "通气模式",
        "param_vent_type": "通气类型",
        "param_o2_flow": "氧流量",
        "param_fio2_set": "设定FiO2",
    }
    for code, label in VENT_CODES.items():
        cnt = sc.bedside.count_documents({"code": code, "valid": True}, limit=5000)
        if cnt > 0:
            val_counter = Counter()
            for doc in sc.bedside.find(
                {"code": code, "valid": True}, {"strVal": 1}
            ).limit(200):
                v = doc.get("strVal", "")
                if v: val_counter[v] += 1
            print(f"\n  {label}({code}): {cnt}+ docs")
            topn(val_counter, 10, f"{code} 取值")

    # ============================================================
    # F7. RRT
    # ============================================================
    print("\n--- F7. RRT ---")
    RRT_KW = ["CRRT", "血透", "血液透析", "腹透", "腹膜透析", "血滤", "血液滤过", "透析"]
    for kw in RRT_KW:
        try:
            cnt = sc.tubeExe.count_documents(
                {"$or": [
                    {"type": {"$regex": kw}},
                    {"strVal": {"$regex": kw}},
                    {"name": {"$regex": kw}},
                ]}, limit=100)
            if cnt > 0:
                print(f"  tubeExe 含'{kw}': {cnt}+")
                sample = sc.tubeExe.find_one(
                    {"$or": [
                        {"type": {"$regex": kw}},
                        {"strVal": {"$regex": kw}},
                        {"name": {"$regex": kw}},
                    ]})
                if sample:
                    print(f"    样例: type={sample.get('type')}, name={sample.get('name')}, "
                          f"strVal={sample.get('strVal','')[:50]}")
        except: pass

    # bedside 中的 RRT
    for kw in ["CRRT", "crrt"]:
        cnt = sc.bedside.count_documents(
            {"$or": [
                {"code": {"$regex": kw, "$options": "i"}},
                {"strVal": {"$regex": kw, "$options": "i"}},
                {"name": {"$regex": kw, "$options": "i"}},
            ]}, limit=100)
        if cnt > 0:
            print(f"  bedside 含'{kw}': {cnt}+")

    # drugExe 中的 RRT 药物
    RRT_DRUG_KW = ["肝素(透析)", "枸橼酸"]
    for kw in RRT_DRUG_KW:
        cnt = sc.drugExe.count_documents(
            {"drugList.name": {"$regex": kw}}, limit=100)
        if cnt > 0:
            print(f"  drugExe 含'{kw}': {cnt}+")

    # ============================================================
    # F8. 镇静用药
    # ============================================================
    print("\n--- F8. 镇静用药 ---")
    SEDATIVE_KW = ["丙泊酚", "咪达唑仑", "右美托咪定", "芬太尼", "瑞芬太尼",
                   "舒芬太尼", "氯胺酮", "劳拉西泮", "地西泮"]
    sed_regex = "|".join(SEDATIVE_KW)
    sed_count = sc.drugExe.count_documents(
        {"drugList.name": {"$regex": sed_regex}}, limit=5000)
    print(f"  drugExe 含镇静药: {sed_count}+ docs")

    # 看样例
    sed_sample = list(sc.drugExe.find(
        {"drugList.name": {"$regex": sed_regex}},
        {"drugList.name": 1, "drugList.dose": 1, "drugList.unit": 1}
    ).limit(5))
    for doc in sed_sample:
        for dl in doc.get("drugList", []):
            name = str(dl.get("name", ""))
            import re
            if re.search(sed_regex, name):
                print(f"    {name[:50]}, dose={dl.get('dose')}, unit={dl.get('unit')}")
                break

    # ============================================================
    # F9. 升压药剂量换算字段
    # ============================================================
    print("\n--- F9. 升压药剂量换算字段 ---")
    VASO_KW = ["去甲肾上腺素", "肾上腺素", "多巴胺", "多巴酚丁胺"]
    vaso_regex = "|".join(VASO_KW)
    vaso_sample = list(sc.drugExe.find(
        {"drugList.name": {"$regex": vaso_regex}},
        {"drugList": 1, "startTime": 1, "drugActionList": 1, "weight": 1,
         "liquidAmount": 1, "liquidAmountUnit": 1,
         "recommendSpeed": 1, "recommendSpeedUnit": 1,
         "spec": 1, "liquidName": 1, "liquidSpec": 1}
    ).limit(10))
    print(f"  升压药执行记录样例: {len(vaso_sample)}")
    for doc in vaso_sample[:3]:
        print(f"\n  startTime={fmt_dt(doc.get('startTime'))}")
        print(f"    weight={doc.get('weight')}")
        print(f"    liquidAmount={doc.get('liquidAmount')} {doc.get('liquidAmountUnit','')}")
        print(f"    recommendSpeed={doc.get('recommendSpeed')} {doc.get('recommendSpeedUnit','')}")
        print(f"    liquidName={doc.get('liquidName')}")
        print(f"    liquidSpec={doc.get('liquidSpec')}")
        for dl in doc.get("drugList", [])[:2]:
            print(f"    drug: name={dl.get('name','')[:50]}, dose={dl.get('dose')}, "
                  f"unit={dl.get('unit')}, spec={dl.get('spec','')[:30]}")
        for al in (doc.get("drugActionList") or [])[:2]:
            print(f"    action: {json.dumps(al, ensure_ascii=False, default=str)[:200]}")

    # ============================================================
    # F10. 连续输注持续时长
    # ============================================================
    print("\n--- F10. 连续输注: endTime / hisStartTime.endTime ---")
    end_time_count = sc.drugExe.count_documents(
        {"endTime": {"$exists": True, "$ne": None}}, limit=5000)
    total_drug = sc.drugExe.count_documents({}, limit=10000)
    print(f"  drugExe.endTime 非空: {end_time_count}/{total_drug}")

    # hisStartTime.endTime
    hs_end_count = 0
    for doc in sc.drugExe.find(
        {"status": "finished"},
        {"hisStartTime": 1}
    ).limit(500):
        hs = doc.get("hisStartTime")
        if isinstance(hs, dict) and hs.get("endTime"):
            hs_end_count += 1
    print(f"  hisStartTime.endTime 非空: {hs_end_count}/500(sampled)")

    # hisStartTime.speed 相关
    for doc in vaso_sample[:3]:
        hs = doc.get("hisStartTime")
        if isinstance(hs, dict):
            print(f"  hisStartTime 详情: speed={hs.get('speed')}, speedUnit={hs.get('speedUnit')}, "
                  f"endTime={fmt_dt(hs.get('endTime'))}")

    # ============================================================
    # F11. SmartCare 自带 SOFA 评分
    # ============================================================
    print("\n--- F11. SmartCare 自带 SOFA 评分 ---")
    sofa_types = Counter()
    for doc in sc.score.find({}, {"scoreType": 1}).limit(10000):
        st = doc.get("scoreType", "")
        if "sofa" in st.lower():
            sofa_types[st] += 1
    if sofa_types:
        print(f"  SOFA相关 scoreType: {dict(sofa_types)}")
    else:
        print("  未找到 SOFA 相关 scoreType")

    # ============================================================
    # G1. infectionShockV2 完整结构
    # ============================================================
    print("\n--- G1. infectionShockV2 完整结构 ---")
    total_shock = sc.infectionShockV2.count_documents({})
    print(f"  总文档数: {total_shock}")

    for doc in sc.infectionShockV2.find().limit(3):
        did = doc.get("diseaseId", "")
        print(f"\n  diseaseId={did}")
        for gk in ["group1H", "group3H", "group6H"]:
            g = doc.get(gk) or {}
            print(f"    {gk}: {json.dumps(g, ensure_ascii=False, default=str)[:500]}")

    # 逐字段填写率
    ALL_FIELDS = set()
    for doc in sc.infectionShockV2.find():
        for gk in ["group1H", "group3H", "group6H"]:
            g = doc.get(gk) or {}
            for k in g:
                ALL_FIELDS.add(f"{gk}.{k}")

    print(f"\n  所有子字段: {sorted(ALL_FIELDS)}")
    for field in sorted(ALL_FIELDS):
        gk, sk = field.split(".", 1)
        cnt = sc.infectionShockV2.count_documents(
            {f"{gk}.{sk}": {"$exists": True, "$ne": None}})
        print(f"    {field}: {cnt}/{total_shock} ({cnt/total_shock*100:.0f}%)" if total_shock else "")

    # ============================================================
    # G2. ai_analyzer.extract_sofa_qsofa 返回结构
    # ============================================================
    print("\n--- G2. ai_analyzer.extract_sofa_qsofa 返回结构 ---")
    print("  函数位置: ai_analyzer.py:900")
    print("  返回字段: sofa_baseline, sofa_current, sofa_breakdown, sofa_items,")
    print("           sofa_is_lower_bound, missing_domains, measured,")
    print("           rr, on_ventilator, sbp, gcs, qsofa, map, map_time,")
    print("           vasopressors, lactate, lactate_time, t0, t0_basis,")
    print("           infection_evidence, fluid_resuscitation, pid, his_pid, weight")
    print("  qSOFA 引用位置: _build_septic_shock_prompt(), _rule_confirm_septic_shock()")
    print("  SOFA 计算: 6域评分(resp/coag/liver/cns/renal/cardio), 缺失域不计分")
    print("  T0 计算: compute_sofa_t0() — 首次SOFA急升>=2的时间")

    # ============================================================
    # 额外: infectionShockV2 group 子字段详细统计
    # ============================================================
    print("\n--- G1补充. infectionShockV2 各group关键字段填写率 ---")
    KEY_FIELDS = {
        "group1H": ["baStandard", "finish", "antExeTime", "boost", "lacVal", "lacStandard", "lacGte4"],
        "group3H": ["baStandard", "finish", "antExeTime", "boost", "lacVal", "lacStandard", "lacGte4",
                     "antiList", "lacTime", "bloodCultureTime"],
        "group6H": ["baStandard", "finish", "antExeTime", "boost", "lacVal", "lacStandard", "lacGte4",
                     "map6h", "cvp6h", "lacAfter", "fluidBalance"],
    }
    for gk, fields in KEY_FIELDS.items():
        print(f"\n  {gk}:")
        for sk in fields:
            cnt = sc.infectionShockV2.count_documents(
                {f"{gk}.{sk}": {"$exists": True, "$ne": None}})
            val_counter = Counter()
            for doc in sc.infectionShockV2.find(
                {f"{gk}.{sk}": {"$exists": True}},
                {f"{gk}.{sk}": 1}
            ):
                v = (doc.get(gk) or {}).get(sk)
                val_counter[str(v)[:30]] += 1
            print(f"    {sk}: {cnt}/{total_shock}, 取值分布={dict(val_counter.most_common(5))}")

    print("\n" + "=" * 80)
    print("Part 2 探测完成")
    print("=" * 80)

if __name__ == "__main__":
    main()
