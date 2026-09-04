#!/usr/bin/env python3
"""
ICU-05 字段探测脚本（只读，不改任何数据）
对 SmartCare / DataCenter 的关键字段进行采样探测，输出探测报告。
"""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from datetime import datetime, timedelta
from pymongo import MongoClient
from collections import Counter
import json

# ---- 加载 db.py 的连接 ----
from db import (
    get_client, get_datacenter_db, iter_bed_dbs, BED_DB_NAMES,
    get_datacenter_client, DATACENTER_CFG, SMARTCARE_CFG,
    EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES,
)

def safe_str(v, max_len=80):
    if v is None:
        return "None"
    s = str(v)
    return s[:max_len] + "..." if len(s) > max_len else s

def fmt_dt(v):
    if v is None:
        return "None"
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:30]

def probe_top10(cursor_or_list, field_name, label=""):
    """取 top10 取值分布"""
    vals = []
    for doc in (cursor_or_list if isinstance(cursor_or_list, list) else cursor_or_list):
        v = doc.get(field_name)
        if v is not None:
            vals.append(safe_str(v, 60))
    counter = Counter(vals)
    total = len(vals)
    print(f"\n  [{label}] {field_name} top10 (total={total}):")
    for val, cnt in counter.most_common(10):
        pct = cnt / total * 100 if total else 0
        print(f"    {val!r:50s}  {cnt:5d} ({pct:5.1f}%)")
    non_null = sum(1 for v in vals if v != "None")
    print(f"  non-null rate: {non_null}/{total} = {non_null/total*100:.1f}%" if total else "  EMPTY")
    return counter

def probe_sample(cursor_or_list, fields, n=3, label=""):
    """取样例 n 条"""
    items = cursor_or_list if isinstance(cursor_or_list, list) else list(cursor_or_list)
    print(f"\n  [{label}] 样例 {min(n, len(items))} 条:")
    for doc in items[:n]:
        row = {}
        for f in fields:
            v = doc.get(f)
            if isinstance(v, datetime):
                row[f] = fmt_dt(v)
            elif isinstance(v, dict):
                row[f] = json.dumps(v, ensure_ascii=False, default=str)[:100]
            elif isinstance(v, list):
                row[f] = f"[list len={len(v)}]"
            else:
                row[f] = safe_str(v, 60)
        print(f"    {json.dumps(row, ensure_ascii=False)}")


# ============================================================
# 主探测流程
# ============================================================

def main():
    print("=" * 80)
    print("ICU-05 字段探测")
    print("=" * 80)

    # ---- 连接 ----
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            db.command("ping")
            print(f"\n[OK] SmartCare DB: {db_name}")
        except Exception as e:
            print(f"\n[FAIL] SmartCare DB {db_name}: {e}")

    try:
        dc_db = get_datacenter_db()
        dc_db.command("ping")
        dc_name = DATACENTER_CFG.auth_db or "DataCenter"
        print(f"[OK] DataCenter DB: {dc_name}")
    except Exception as e:
        print(f"[FAIL] DataCenter: {e}")
        dc_db = None

    # 获取第一个可用的 SmartCare db
    sc_db = None
    for db_name, db in iter_bed_dbs():
        sc_db = db
        print(f"\n使用 SmartCare DB: {db_name}")
        break
    if sc_db is None:
        print("FATAL: no SmartCare DB available")
        return

    # ============================================================
    # 1. SmartCare patient 表
    # ============================================================
    print("\n" + "=" * 80)
    print("1. SmartCare patient 表")
    print("=" * 80)

    # 先看字段
    sample_pats = list(sc_db.patient.find().limit(5))
    if sample_pats:
        print(f"\n  patient 集合字段列表: {sorted(sample_pats[0].keys())}")
    else:
        print("  patient 集合为空!")

    # 关键字段探测
    KEY_PAT_FIELDS = [
        "icuAdmissionTime", "mrn", "hisPid", "deptCode", "status",
        "name", "hisBed", "admissionType", "dischargedType",
        "icuDischargeTime", "dischargeTime",
        "clinicalDiagnosis", "weight",
        "patientId", "inHospitalNo",
    ]
    for f in KEY_PAT_FIELDS:
        docs = list(sc_db.patient.find(
            {f: {"$exists": True, "$ne": None}},
            {f: 1}
        ).limit(200))
        probe_top10(docs, f, label="patient")

    # 入科类型 (admissionType) 全部取值
    print("\n  --- admissionType 全部取值分布 ---")
    all_adm_types = list(sc_db.patient.find(
        {"admissionType": {"$exists": True, "$ne": None}},
        {"admissionType": 1}
    ).limit(5000))
    probe_top10(all_adm_types, "admissionType", label="patient admissionType (全量)")

    # icuAdmissionTime 类型检查
    print("\n  --- icuAdmissionTime 类型检查 ---")
    for doc in list(sc_db.patient.find({"icuAdmissionTime": {"$exists": True}}).limit(5)):
        t = doc.get("icuAdmissionTime")
        print(f"    type={type(t).__name__}, value={fmt_dt(t)}")

    probe_sample(sample_pats, KEY_PAT_FIELDS, n=3, label="patient样例")

    # ============================================================
    # 2. DataCenter VI_ICU_ZYYZ
    # ============================================================
    print("\n" + "=" * 80)
    print("2. DataCenter VI_ICU_ZYYZ")
    print("=" * 80)

    if dc_db is not None:
        try:
            zyyz_count = dc_db["VI_ICU_ZYYZ"].count_documents({}, limit=1000)
            print(f"  VI_ICU_ZYYZ 总文档数(前1000): {zyyz_count}")
        except Exception as e:
            print(f"  count error: {e}")

        sample_zyyz = list(dc_db["VI_ICU_ZYYZ"].find().limit(5))
        if sample_zyyz:
            print(f"  VI_ICU_ZYYZ 字段列表: {sorted(sample_zyyz[0].keys())}")
            ZYYZ_FIELDS = [
                "pid", "orderTime", "orderName", "status", "yaoType",
                "drugName", "drugCode", "startTime", "execTime", "endTime",
                "mrn", "deptCode", "classification",
            ]
            # 看哪些字段存在
            for f in ZYYZ_FIELDS:
                exists = sum(1 for d in sample_zyyz if f in d and d.get(f) is not None)
                print(f"    {f}: exists in {exists}/{len(sample_zyyz)} docs")
            probe_sample(sample_zyyz, ZYYZ_FIELDS, n=3, label="VI_ICU_ZYYZ")

            # orderTime 类型检查
            print("\n  --- VI_ICU_ZYYZ.orderTime 类型检查 ---")
            for doc in sample_zyyz:
                t = doc.get("orderTime")
                print(f"    type={type(t).__name__}, value={fmt_dt(t)}")

            # 探查是否有执行时间字段
            print("\n  --- VI_ICU_ZYYZ 时间字段探测 ---")
            TIME_CANDIDATES = [
                "orderTime", "startTime", "execTime", "endTime",
                "executeTime", "execute_time", "hisStartTime",
                "exeTime", "performTime", "reportTime",
            ]
            for f in TIME_CANDIDATES:
                cnt = dc_db["VI_ICU_ZYYZ"].count_documents(
                    {f: {"$exists": True, "$ne": None}}, limit=100
                )
                if cnt > 0:
                    print(f"    {f}: {cnt}+ docs exist")

            # status 取值分布
            probe_top10(
                list(dc_db["VI_ICU_ZYYZ"].find({}, {"status": 1}).limit(1000)),
                "status", label="VI_ICU_ZYYZ"
            )
            # yaoType 分布
            probe_top10(
                list(dc_db["VI_ICU_ZYYZ"].find({}, {"yaoType": 1}).limit(1000)),
                "yaoType", label="VI_ICU_ZYYZ"
            )
        else:
            print("  VI_ICU_ZYYZ 为空!")
    else:
        print("  DataCenter 不可用，跳过")

    # ============================================================
    # 3. DataCenter VI_ICU_ZYBR (桥接)
    # ============================================================
    print("\n" + "=" * 80)
    print("3. DataCenter VI_ICU_ZYBR (SmartCare <-> DataCenter 桥接)")
    print("=" * 80)

    if dc_db is not None:
        try:
            zybr_count = dc_db["VI_ICU_ZYBR"].count_documents({}, limit=1000)
            print(f"  VI_ICU_ZYBR 总文档数(前1000): {zybr_count}")
        except Exception as e:
            print(f"  count error: {e}")

        sample_zybr = list(dc_db["VI_ICU_ZYBR"].find().limit(5))
        if sample_zybr:
            print(f"  VI_ICU_ZYBR 字段列表: {sorted(sample_zybr[0].keys())}")
            ZYBR_FIELDS = ["pid", "mrn", "deptCode", "name", "admitTime", "dischargeTime"]
            probe_sample(sample_zybr, ZYBR_FIELDS, n=3, label="VI_ICU_ZYBR")

        # 桥接测试：随机取 SmartCare patient 的 hisPid/mrn，在 VI_ICU_ZYBR 中找
        print("\n  --- 桥接可用率测试 (SmartCare.mrn → VI_ICU_ZYBR.mrn) ---")
        sc_mrns = []
        for p in sc_db.patient.find(
            {"status": {"$ne": "invalid"}},
            {"mrn": 1, "hisPid": 1}
        ).limit(50):
            mrn = p.get("mrn") or p.get("hisPid")
            if mrn:
                sc_mrns.append(str(mrn))

        if sc_mrns and dc_db is not None:
            dc_matches = list(dc_db["VI_ICU_ZYBR"].find(
                {"mrn": {"$in": sc_mrns}},
                {"mrn": 1, "pid": 1}
            ))
            dc_mrns = {d.get("mrn") for d in dc_matches}
            matched = sum(1 for m in sc_mrns if m in dc_mrns)
            print(f"  SmartCare 取 {len(sc_mrns)} 例 mrn, DataCenter 匹配 {matched} 例")
            print(f"  桥接率: {matched/len(sc_mrns)*100:.1f}%")
        else:
            print("  无法测试桥接(无 mrn 或 DataCenter 不可用)")

    # ============================================================
    # 4. diseaseDiagnosis 表
    # ============================================================
    print("\n" + "=" * 80)
    print("4. diseaseDiagnosis 表")
    print("=" * 80)

    sample_diag = list(sc_db.diseaseDiagnosis.find().limit(5))
    if sample_diag:
        print(f"  diseaseDiagnosis 字段列表: {sorted(sample_diag[0].keys())}")
        DIAG_FIELDS = [
            "pid", "patientName", "mrn", "diseaseType", "propertyType",
            "diagnosisTime", "valid", "notes", "brainInjury",
            "lastEditUserId",
        ]
        probe_sample(sample_diag, DIAG_FIELDS, n=3, label="diseaseDiagnosis")

        # diseaseType 全量分布
        print("\n  --- diseaseType 全量分布 ---")
        all_diag_types = list(sc_db.diseaseDiagnosis.find(
            {"diseaseType": {"$exists": True, "$ne": None}},
            {"diseaseType": 1}
        ).limit(10000))
        probe_top10(all_diag_types, "diseaseType", label="diseaseType全量")

        # propertyType 分布
        print("\n  --- propertyType 全量分布 ---")
        all_prop_types = list(sc_db.diseaseDiagnosis.find(
            {"propertyType": {"$exists": True, "$ne": None}},
            {"propertyType": 1}
        ).limit(10000))
        probe_top10(all_prop_types, "propertyType", label="propertyType全量")
    else:
        print("  diseaseDiagnosis 为空!")

    # "入院诊断"/"入科诊断" 在哪
    print("\n  --- 诊断字段探测(patient表中的诊断) ---")
    DIAG_PAT_FIELDS = [
        "clinicalDiagnosis", "admissionDiagnosis", "dischargedDiagnosis",
        "diagnosis", "diagnosisHistoryList", "clinicalDiagnosisCodeList",
        "dischargedDiagnosisIcd",
    ]
    for f in DIAG_PAT_FIELDS:
        cnt = sc_db.patient.count_documents(
            {f: {"$exists": True, "$ne": None, "$ne": ""}}, limit=100
        )
        print(f"  patient.{f}: {cnt}+ docs have value")

    # ============================================================
    # 5. MAP / 血压
    # ============================================================
    print("\n" + "=" * 80)
    print("5. MAP / 血压")
    print("=" * 80)

    MAP_CODES = ["param_ibp_m", "param_nibp_m", "param_MAP"]
    SBP_CODES = ["param_ibp_s", "param_nibp_s"]
    DBP_CODES = ["param_ibp_d", "param_nibp_d"]

    for code_set, label in [(MAP_CODES, "MAP"), (SBP_CODES, "SBP"), (DBP_CODES, "DBP")]:
        for code in code_set:
            cnt = sc_db.bedside.count_documents(
                {"code": code, "valid": True}, limit=100
            )
            if cnt > 0:
                print(f"  bedside code={code}: {cnt}+ docs")
                sample = list(sc_db.bedside.find(
                    {"code": code, "valid": True},
                    {"strVal": 1, "time": 1, "pid": 1}
                ).limit(3))
                for s in sample:
                    print(f"    pid={s.get('pid','')[:20]}, strVal={s.get('strVal')}, time={fmt_dt(s.get('time'))}")

    # 采样频率
    print("\n  --- MAP 采样频率估算 ---")
    # 取一个有 MAP 数据的患者，看 1h 内有多少条
    map_sample = sc_db.bedside.find_one(
        {"code": {"$in": MAP_CODES}, "valid": True},
        {"pid": 1, "time": 1}
    )
    if map_sample:
        pid = map_sample.get("pid")
        t = map_sample.get("time")
        if t:
            window_start = t - timedelta(hours=2)
            map_count = sc_db.bedside.count_documents(
                {"pid": pid, "code": {"$in": MAP_CODES}, "valid": True,
                 "time": {"$gte": window_start, "$lte": t}},
                limit=500
            )
            print(f"  患者 {pid[:20]} 在 {fmt_dt(t)} 前2h内 MAP 条数: {map_count}")

    # ============================================================
    # 6. 乳酸
    # ============================================================
    print("\n" + "=" * 80)
    print("6. 乳酸")
    print("=" * 80)

    # 来源 A: bedside (bGATemp)
    LAC_BEDSIDE_CODES = ["param_bg_Lac", "param_lactate"]
    for code in LAC_BEDSIDE_CODES:
        cnt = sc_db.bedside.count_documents({"code": code}, limit=100)
        if cnt > 0:
            print(f"  bedside code={code}: {cnt}+ docs")

    # 来源 B: bGATemp (嵌套在 bedsides 中)
    for coll_name in ["bGATemp", "bGATemp1", "BGATemp"]:
        if coll_name in sc_db.list_collection_names():
            sample_bga = list(sc_db[coll_name].find().limit(3))
            if sample_bga:
                print(f"\n  {coll_name} 字段: {sorted(sample_bga[0].keys())}")
                # 看 bedsides 里的 code
                for doc in sample_bga[:2]:
                    bds = doc.get("bedsides") or []
                    codes = [b.get("code") for b in bds]
                    lac_items = [b for b in bds if "Lac" in str(b.get("code", "")) or "lac" in str(b.get("code", "")).lower()]
                    print(f"    bedsides codes: {codes[:10]}")
                    if lac_items:
                        print(f"    乳酸项: {lac_items}")

    # 来源 C: DataCenter VI_ICU_EXAM_ITEM
    if dc_db is not None:
        print("\n  --- DataCenter 乳酸检验 ---")
        LAC_LAB_CODES = ["Lac", "LAC", "lactate", "乳酸"]
        for code in LAC_LAB_CODES:
            cnt = dc_db["VI_ICU_EXAM_ITEM"].count_documents(
                {"itemCode": code}, limit=100
            )
            if cnt > 0:
                print(f"  VI_ICU_EXAM_ITEM itemCode={code}: {cnt}+ docs")
                sample = list(dc_db["VI_ICU_EXAM_ITEM"].find(
                    {"itemCode": code},
                    {"itemCode": 1, "itemName": 1, "itemValue": 1, "result": 1, "unit": 1, "authTime": 1, "hisPid": 1}
                ).limit(3))
                for s in sample:
                    print(f"    {json.dumps({k: safe_str(v, 40) for k, v in s.items()}, ensure_ascii=False)}")

    # ============================================================
    # 7. 液体
    # ============================================================
    print("\n" + "=" * 80)
    print("7. 液体/输注量")
    print("=" * 80)

    # 出入量记录 (bedside)
    FLUID_CODES = ["param_niaoLiang", "param_ruLiang", "param_chuLiang",
                   "param_shuRuLiang", "param_shuChuLiang"]
    for code in FLUID_CODES:
        cnt = sc_db.bedside.count_documents({"code": code}, limit=100)
        if cnt > 0:
            print(f"  bedside code={code}: {cnt}+ docs")
            s = sc_db.bedside.find_one({"code": code}, {"strVal": 1, "time": 1, "pid": 1})
            if s:
                print(f"    样例: strVal={s.get('strVal')}, time={fmt_dt(s.get('time'))}")

    # drugExe 中的输液相关
    print("\n  --- drugExe 输液执行记录 ---")
    INFUSION_KEYWORDS = ["氯化钠", "葡萄糖", "林格", "乳酸钠", "羟乙基淀粉",
                         "白蛋白", "血浆", "液体", "补液", "输液"]
    infusion_kw_regex = "|".join(INFUSION_KEYWORDS)
    sample_inf = list(sc_db.drugExe.find(
        {"drugList.name": {"$regex": infusion_kw_regex, "$options": "i"}},
        {"pid": 1, "startTime": 1, "drugList.name": 1, "drugList.dose": 1,
         "drugList.unit": 1, "drugList.code": 1, "status": 1}
    ).limit(5))
    if sample_inf:
        print(f"  液体相关 drugExe 样例 ({len(sample_inf)} 条):")
        for s in sample_inf:
            print(f"    pid={s.get('pid','')[:20]}, start={fmt_dt(s.get('startTime'))}, "
                  f"status={s.get('status')}")
            for dl in (s.get("drugList") or [])[:3]:
                print(f"      drug: name={dl.get('name','')[:40]}, dose={dl.get('dose')}, unit={dl.get('unit')}, code={dl.get('code','')[:20]}")
    else:
        print("  drugExe 中无液体样例(用关键词搜索)")

    # ============================================================
    # 8. 抗生素 / drugExe
    # ============================================================
    print("\n" + "=" * 80)
    print("8. 抗生素 / drugExe")
    print("=" * 80)

    sample_drug = list(sc_db.drugExe.find().limit(3))
    if sample_drug:
        print(f"  drugExe 字段: {sorted(sample_drug[0].keys())}")
        DRUG_FIELDS = [
            "pid", "startTime", "exeTime", "hisStartTime",
            "status", "statusFlag", "executeStatus",
            "drugList", "drugName", "orderName",
        ]
        # 时间字段类型
        print("\n  --- drugExe 时间字段类型 ---")
        for f in ["startTime", "exeTime", "hisStartTime"]:
            for doc in sample_drug:
                v = doc.get(f)
                if v is not None:
                    print(f"    {f}: type={type(v).__name__}, value={safe_str(v, 40)}")
                    break

        probe_sample(sample_drug, DRUG_FIELDS, n=2, label="drugExe")

    # configDrug.classification 分布
    print("\n  --- configDrug.classification 分布 ---")
    sample_config_drug = list(sc_db.configDrug.find(
        {"classification": {"$exists": True, "$ne": None}},
        {"classification": 1, "code": 1, "name": 1}
    ).limit(2000))
    probe_top10(sample_config_drug, "classification", label="configDrug")

    # 有 classification='抗生素' 的数量
    abx_count = sc_db.configDrug.count_documents({"classification": "抗生素"}, limit=10000)
    print(f"\n  configDrug classification='抗生素': {abx_count} 条")

    # ============================================================
    # 9. 血培养 / ICU-06 病原学送检
    # ============================================================
    print("\n" + "=" * 80)
    print("9. 血培养 / ICU-06 病原学送检逻辑")
    print("=" * 80)

    print("  ICU-06 现有识别逻辑:")
    print("  - 源A: DataCenter.VI_ICU_ZYYZ, yaoType∈{'检验'}, orderName 匹配 CULTURE_KEYWORDS_FULL")
    print("  - 关键词: " + ", ".join([
        "血培养", "痰培养", "尿培养", "细菌培养", "真菌培养",
        "分泌物培养", "引流液培养", "胸水培养", "腹水培养", "脑脊液培养",
        "导管培养", "涂片", "革兰染色", "抗酸染色", "G试验", "GM试验", "药敏",
        "内毒素", "隐球菌", "曲霉", "半乳甘露聚糖", "结核",
        "核酸", "微生物", "细菌",
    ]))
    print("  - 可复用函数: db.py 中的 CULTURE_KEYWORDS_FULL 列表 + _keyword_regex()")
    print("  - 血培养可直接从 VI_ICU_ZYYZ.orderName 包含'血培养'来识别")

    # 在 DataCenter 中搜索血培养
    if dc_db is not None:
        blood_culture_cnt = dc_db["VI_ICU_ZYYZ"].count_documents(
            {"orderName": {"$regex": "血培养"}}, limit=1000
        )
        print(f"\n  VI_ICU_ZYYZ orderName含'血培养': {blood_culture_cnt}+ 条")
        if blood_culture_cnt > 0:
            sample_bc = list(dc_db["VI_ICU_ZYYZ"].find(
                {"orderName": {"$regex": "血培养"}},
                {"pid": 1, "orderTime": 1, "orderName": 1, "status": 1, "yaoType": 1}
            ).limit(5))
            probe_sample(sample_bc, ["pid", "orderTime", "orderName", "status", "yaoType"], n=3, label="血培养")

    # ============================================================
    # 10. infectionShockV2 结构
    # ============================================================
    print("\n" + "=" * 80)
    print("10. infectionShockV2 结构")
    print("=" * 80)

    sample_shock = list(sc_db.infectionShockV2.find().limit(5))
    if sample_shock:
        print(f"  infectionShockV2 字段: {sorted(sample_shock[0].keys())}")
        SHOCK_FIELDS = ["diseaseId", "group1H", "group3H", "group6H"]
        probe_sample(sample_shock, SHOCK_FIELDS, n=3, label="infectionShockV2")

        # 深入看 group1H/group3H/group6H 的完整结构
        print("\n  --- group1H 完整结构 ---")
        for doc in sample_shock[:2]:
            g1 = doc.get("group1H") or {}
            g3 = doc.get("group3H") or {}
            g6 = doc.get("group6H") or {}
            print(f"  group1H keys: {sorted(g1.keys()) if g1 else 'EMPTY'}")
            print(f"    values: {json.dumps(g1, ensure_ascii=False, default=str)[:300]}")
            print(f"  group3H keys: {sorted(g3.keys()) if g3 else 'EMPTY'}")
            print(f"    values: {json.dumps(g3, ensure_ascii=False, default=str)[:300]}")
            print(f"  group6H keys: {sorted(g6.keys()) if g6 else 'EMPTY'}")
            print(f"    values: {json.dumps(g6, ensure_ascii=False, default=str)[:300]}")
            print()

        # 各字段填写率
        total_shock = sc_db.infectionShockV2.count_documents({})
        print(f"  infectionShockV2 总文档数: {total_shock}")
        for field in ["group1H", "group3H", "group6H"]:
            non_empty = sc_db.infectionShockV2.count_documents(
                {field: {"$exists": True, "$ne": None, "$ne": {}}}
            )
            print(f"  {field} 非空: {non_empty}/{total_shock} = {non_empty/total_shock*100:.1f}%" if total_shock else "")

        # baStandard / finish 填写率
        for h in ["group1H", "group3H", "group6H"]:
            for sub in ["baStandard", "finish"]:
                cnt = sc_db.infectionShockV2.count_documents(
                    {f"{h}.{sub}": {"$exists": True, "$ne": None}}
                )
                print(f"  {h}.{sub} 存在: {cnt}/{total_shock}" if total_shock else "")
    else:
        print("  infectionShockV2 为空!")

    # ============================================================
    # 汇总
    # ============================================================
    print("\n" + "=" * 80)
    print("探测完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
