#!/usr/bin/env python3
"""
ICU-05 数据链路审计脚本
========================
审计 2026-01 至 2026-09 的 ICU-05 (感染性/脓毒性休克 1h/3h/6h Bundle) 完整数据链路。
按月输出漏斗指标和患者级 CSV，定位"1-9月累计分母仅3人"的根因。

用法:
    cd icu-quality-backend
    python ../tools/audit_icu05_2026_01_09.py [--dept all] [--output-dir ../audit_output]

输出:
    audit_output/
      funnel_2026_01_09.csv      — 逐月漏斗表
      patients_2026_01_09.csv    — 患者级明细
      summary.txt                — 审计摘要
"""
import sys
import os
import csv
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

# 确保能导入 backend 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "icu-quality-backend"))

from db import (
    get_client, get_datacenter_client, BED_DB_NAMES, iter_bed_dbs,
    get_bundle_data, get_bundle_data_v2,
    build_exclusion_key, SEPSIS_DIAG_KEYWORDS,
)
from config.candidate_rules import CANDIDATE_ENGINE_MODE, CANDIDATE_RULE_VERSION


def parse_args():
    parser = argparse.ArgumentParser(description="ICU-05 审计脚本")
    parser.add_argument("--dept", default="all", help="科室筛选 (all 或 deptCode)")
    parser.add_argument("--output-dir", default=str(Path(__file__).parent.parent / "audit_output"),
                        help="输出目录")
    parser.add_argument("--months", default="2026-01:2026-09",
                        help="审计月份范围 (YYYY-MM:YYYY-MM)")
    return parser.parse_args()


def resolve_dept_codes(dept: str) -> list:
    """解析科室参数为 deptCode 列表"""
    if dept and dept != "all":
        return [dept]
    codes = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            docs = list(db.department.find({}, {"code": 1, "_id": 0}))
            if docs:
                codes = [d["code"] for d in docs]
                break
        except Exception:
            continue
    return codes if codes else ["JJL000282", "JJL000283", "0801"]


def month_range(start_ym: str, end_ym: str) -> list:
    """生成月份列表"""
    sy, sm = map(int, start_ym.split("-"))
    ey, em = map(int, end_ym.split("-"))
    months = []
    y, m = sy, sm
    while (y < ey) or (y == ey and m <= em):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months


def audit_month(dept_codes: list, period: str) -> dict:
    """
    审计单月 ICU-05 数据链路。
    返回漏斗各层计数和患者明细。
    """
    import calendar
    year, month = map(int, period.split("-"))
    start_date = f"{year}-{month:02d}-01"
    end_day = calendar.monthrange(year, month)[1]
    end_date = f"{year}-{month:02d}-{end_day:02d}"
    start_dt = datetime(year, month, 1)
    end_dt = datetime(year, month, end_day, 23, 59, 59)

    result = {
        "period": period,
        "icu_events": 0,
        "icu_unique_patients": 0,
        "infection_diag_count": 0,
        "sepsis_diag_count": 0,
        "septic_shock_diag_count": 0,
        "infectionShockV2_count": 0,
        "linked_icu_events": 0,
        "cross_db_link_fail": 0,
        "raw_den_candidates": 0,
        "k1_true": 0,
        "k2_true": 0,
        "k1_and_k2": 0,
        "candidate_high_probability": 0,
        "candidate_probable": 0,
        "candidate_pending_review": 0,
        "candidate_not_candidate": 0,
        "lactate_missing": 0,
        "vasopressor_missing": 0,
        "sofa_missing": 0,
        "t0_missing": 0,
        "exclusion_key_missing": 0,
        "duplicate_events": 0,
        "manual_excluded": 0,
        "final_den_1h": 0,
        "final_den_3h": 0,
        "final_den_6h": 0,
        "num_1h": 0,
        "num_3h": 0,
        "num_6h": 0,
    }
    patients = []

    # ---- Layer 0: ICU 入科事件 ----
    icu_pids = set()
    icu_mrns = set()
    for db_name, db in iter_bed_dbs():
        try:
            pat_docs = list(db.patient.find(
                {
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                    "icuAdmissionTime": {"$lte": end_dt},
                    "$or": [
                        {"icuDischargeTime": {"$gte": start_dt}},
                        {"icuDischargeTime": None},
                        {"icuDischargeTime": {"$exists": False}},
                    ],
                },
                {"_id": 1, "mrn": 1, "hisPid": 1, "name": 1, "icuAdmissionTime": 1},
            ))
            for p in pat_docs:
                icu_pids.add(str(p["_id"]))
                mrn = p.get("mrn") or p.get("hisPid") or ""
                if mrn:
                    icu_mrns.add(str(mrn))
            break
        except Exception:
            continue
    result["icu_events"] = len(icu_pids)
    result["icu_unique_patients"] = len(icu_mrns)

    # ---- Layer 1: diseaseDiagnosis 关键词匹配 ----
    all_diag_patients = []
    sepsis_keywords_lower = ["脓毒", "败血", "感染性休克", "脓毒性休克", "septic", "sepsis"]
    septic_shock_keywords = ["脓毒性休克", "感染性休克", "脓毒症休克", "败血症休克", "septic shock"]

    for db_name, db in iter_bed_dbs():
        try:
            # 所有感染相关诊断
            all_infection_diag = list(db.diseaseDiagnosis.find(
                {
                    "diseaseType": {"$regex": SEPSIS_DIAG_KEYWORDS, "$options": "i"},
                    "valid": {"$ne": False},
                    "diagnosisTime": {"$gte": start_dt, "$lte": end_dt},
                },
                {"pid": 1, "patientName": 1, "mrn": 1, "diagnosisTime": 1, "diseaseType": 1, "_id": 1},
            ))

            for d in all_infection_diag:
                dt_text = (d.get("diseaseType") or "").lower()
                is_sepsis = any(kw in dt_text for kw in sepsis_keywords_lower)
                is_shock = any(kw in dt_text for kw in septic_shock_keywords)

                pat_rec = {
                    "patient_id": d.get("pid", ""),
                    "name": d.get("patientName", ""),
                    "mrn": d.get("mrn", ""),
                    "diagnosis_text": d.get("diseaseType", ""),
                    "diagnosis_time": d.get("diagnosisTime"),
                    "disease_id": str(d.get("_id", "")),
                    "is_sepsis": is_sepsis,
                    "is_septic_shock": is_shock,
                    "source": "diseaseDiagnosis",
                    "period": period,
                }
                all_diag_patients.append(pat_rec)

            break
        except Exception:
            continue

    result["infection_diag_count"] = len(all_diag_patients)
    result["sepsis_diag_count"] = sum(1 for p in all_diag_patients if p["is_sepsis"])
    result["septic_shock_diag_count"] = sum(1 for p in all_diag_patients if p["is_septic_shock"])

    # ---- Layer 2: infectionShockV2 ----
    isv2_count = 0
    for db_name, db in iter_bed_dbs():
        try:
            isv2_count = db.infectionShockV2.count_documents({
                "createTime": {"$gte": start_dt, "$lte": end_dt},
            })
            break
        except Exception:
            continue
    result["infectionShockV2_count"] = isv2_count

    # ---- Layer 3: 调用 get_bundle_data_v2 获取完整判定 ----
    bundle_data = get_bundle_data_v2(dept_codes, start_date, end_date)
    den_patients = bundle_data.get("den_patients", [])
    result["raw_den_candidates"] = len(den_patients)

    # 统计各层
    linked = 0
    link_fail = 0
    k1_true = 0
    k2_true = 0
    k1_and_k2 = 0
    lactate_missing = 0
    vaso_missing = 0
    sofa_missing = 0
    t0_missing = 0
    ek_missing = 0
    cand_high = 0
    cand_probable = 0
    cand_pending = 0
    cand_not = 0

    for pat in den_patients:
        v3 = pat.get("v3") or {}
        sc_pid = pat.get("sc_pid")
        if sc_pid:
            linked += 1
        else:
            link_fail += 1

        # K1/K2
        k1 = v3.get("k1")
        k2 = v3.get("k2")
        if k1 is True:
            k1_true += 1
        if k2 is True:
            k2_true += 1
        if k1 is True and k2 is True:
            k1_and_k2 += 1

        # 缺失统计
        if v3.get("lactate_initial") is None:
            lactate_missing += 1
        if not pat.get("has_vasopressor") and v3.get("vasopressor_status") != "active":
            vaso_missing += 1
        sofa = v3.get("sofa") or {}
        sofa2 = sofa.get("sofa2") or {}
        if sofa2.get("sofa2_score") is None:
            sofa_missing += 1
        if not pat.get("t0"):
            t0_missing += 1
        if not pat.get("exclusion_key"):
            ek_missing += 1

        # 候选引擎
        cs = pat.get("candidate_status") or v3.get("candidate_status") or "not_candidate"
        if cs == "high_probability":
            cand_high += 1
        elif cs == "probable":
            cand_probable += 1
        elif cs == "pending_review":
            cand_pending += 1
        else:
            cand_not += 1

        # 患者明细
        patients.append({
            "period": period,
            "patient_id": pat.get("_id", ""),
            "his_patient_id": pat.get("mrn", ""),
            "admission_id": pat.get("sc_pid", ""),
            "icu_event_id": pat.get("dc_pid", ""),
            "dept_code": pat.get("deptCode", ""),
            "icu_admit_time": str(pat.get("icuAdmissionTime", ""))[:16],
            "shock_t0": str(pat.get("t0", ""))[:16],
            "diagnosis_text": pat.get("diagnose", ""),
            "diagnosis_time": str(pat.get("diagnosisTime", ""))[:16],
            "infectionShockV2_id": pat.get("diseaseId", ""),
            "k1": k1,
            "k2": k2,
            "candidate_status": cs,
            "clinical_confirmation_status": pat.get("clinical_confirmation_status", ""),
            "lactate_value": v3.get("lactate_initial"),
            "lactate_time": str(v3.get("lactate_initial_time", ""))[:16],
            "vasopressor_status": v3.get("vasopressor_status", ""),
            "vasopressor_start_time": str(v3.get("vaso_start_time", ""))[:16],
            "map_min": v3.get("map_min"),
            "sofa2_score": sofa2.get("sofa2_score"),
            "exclusion_key": pat.get("exclusion_key", ""),
            "excluded": "",
            "excluded_reason": "",
            "bundle_1h": (v3.get("bundle_1h") or {}).get("finish"),
            "bundle_3h": (v3.get("bundle_3h") or {}).get("finish"),
            "bundle_6h": None,  # 6h 当前未实现
            "not_in_denominator_reason": pat.get("event_mapping_status", ""),
        })

    result["linked_icu_events"] = linked
    result["cross_db_link_fail"] = link_fail
    result["k1_true"] = k1_true
    result["k2_true"] = k2_true
    result["k1_and_k2"] = k1_and_k2
    result["candidate_high_probability"] = cand_high
    result["candidate_probable"] = cand_probable
    result["candidate_pending_review"] = cand_pending
    result["candidate_not_candidate"] = cand_not
    result["lactate_missing"] = lactate_missing
    result["vasopressor_missing"] = vaso_missing
    result["sofa_missing"] = sofa_missing
    result["t0_missing"] = t0_missing
    result["exclusion_key_missing"] = ek_missing

    # ---- Layer 4: 人工排除 ----
    exclusion_count = 0
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db["icu_indicator_exclusion"]
            for code in ("ICU-05-1h", "ICU-05-3h", "ICU-05-6h"):
                exc_docs = list(coll.find(
                    {"period": period, "code": code, "excluded": True},
                    {"exclusion_key": 1},
                ))
                exclusion_count += len(exc_docs)
            break
        except Exception:
            continue
    result["manual_excluded"] = exclusion_count

    # ---- Layer 5: 正式分母/分子 ----
    # 旧口径 K1 AND K2
    official_den = [p for p in den_patients
                    if (p.get("v3") or {}).get("k1") is True
                    and (p.get("v3") or {}).get("k2") is True]
    official_den_keys = {p.get("exclusion_key") for p in official_den if p.get("exclusion_key")}

    h1_patients = [p for p in bundle_data.get("h1_patients", [])
                   if p.get("exclusion_key") in official_den_keys]
    h3_patients = [p for p in bundle_data.get("h3_patients", [])
                   if p.get("exclusion_key") in official_den_keys]

    result["final_den_1h"] = len(official_den)
    result["final_den_3h"] = len(official_den)
    result["final_den_6h"] = 0  # 6h 当前硬编码为0
    result["num_1h"] = len(h1_patients)
    result["num_3h"] = len(h3_patients)
    result["num_6h"] = 0

    return result, patients


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dept_codes = resolve_dept_codes(args.dept)
    months = month_range(*args.months.split(":"))

    print(f"ICU-05 审计: {months[0]} ~ {months[-1]}, dept={args.dept}")
    print(f"科室代码: {dept_codes}")
    print(f"CANDIDATE_ENGINE_MODE: {CANDIDATE_ENGINE_MODE}")
    print(f"CANDIDATE_RULE_VERSION: {CANDIDATE_RULE_VERSION}")
    print("=" * 80)

    all_funnel = []
    all_patients = []

    for period in months:
        print(f"\n审计 {period}...")
        try:
            funnel, patients = audit_month(dept_codes, period)
            all_funnel.append(funnel)
            all_patients.extend(patients)

            # 打印漏斗
            print(f"  ICU入科事件: {funnel['icu_events']}")
            print(f"  ICU唯一患者: {funnel['icu_unique_patients']}")
            print(f"  感染相关诊断: {funnel['infection_diag_count']}")
            print(f"  脓毒症诊断: {funnel['sepsis_diag_count']}")
            print(f"  脓毒性休克诊断: {funnel['septic_shock_diag_count']}")
            print(f"  infectionShockV2: {funnel['infectionShockV2_count']}")
            print(f"  原始分母候选: {funnel['raw_den_candidates']}")
            print(f"  K1=true: {funnel['k1_true']}, K2=true: {funnel['k2_true']}, K1∧K2: {funnel['k1_and_k2']}")
            print(f"  候选引擎: high={funnel['candidate_high_probability']}, "
                  f"probable={funnel['candidate_probable']}, "
                  f"pending={funnel['candidate_pending_review']}, "
                  f"not={funnel['candidate_not_candidate']}")
            print(f"  最终分母(1h/3h/6h): {funnel['final_den_1h']}/{funnel['final_den_3h']}/{funnel['final_den_6h']}")
            print(f"  分子(1h/3h/6h): {funnel['num_1h']}/{funnel['num_3h']}/{funnel['num_6h']}")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    # ---- 输出漏斗 CSV ----
    funnel_path = output_dir / "funnel_2026_01_09.csv"
    if all_funnel:
        with open(funnel_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=all_funnel[0].keys())
            writer.writeheader()
            writer.writerows(all_funnel)
        print(f"\n漏斗表已写入: {funnel_path}")

    # ---- 输出患者级 CSV ----
    patients_path = output_dir / "patients_2026_01_09.csv"
    if all_patients:
        with open(patients_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=all_patients[0].keys())
            writer.writeheader()
            writer.writerows(all_patients)
        print(f"患者明细已写入: {patients_path}")

    # ---- 输出审计摘要 ----
    summary_path = output_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("ICU-05 审计摘要\n")
        f.write("=" * 80 + "\n")
        f.write(f"审计范围: {months[0]} ~ {months[-1]}\n")
        f.write(f"科室: {args.dept}\n")
        f.write(f"CANDIDATE_ENGINE_MODE: {CANDIDATE_ENGINE_MODE}\n")
        f.write(f"CANDIDATE_RULE_VERSION: {CANDIDATE_RULE_VERSION}\n\n")

        if all_funnel:
            total = {k: 0 for k in all_funnel[0] if isinstance(all_funnel[0][k], (int, float))}
            for row in all_funnel:
                for k in total:
                    total[k] += row.get(k, 0)

            f.write("累计统计:\n")
            f.write(f"  ICU入科事件(各月累计): {total['icu_events']}\n")
            f.write(f"  感染相关诊断: {total['infection_diag_count']}\n")
            f.write(f"  脓毒症诊断: {total['sepsis_diag_count']}\n")
            f.write(f"  脓毒性休克诊断: {total['septic_shock_diag_count']}\n")
            f.write(f"  原始分母候选: {total['raw_den_candidates']}\n")
            f.write(f"  K1∧K2: {total['k1_and_k2']}\n")
            f.write(f"  最终分母(1h): {total['final_den_1h']}\n")
            f.write(f"  分子(1h): {total['num_1h']}\n")
            f.write(f"  乳酸缺失: {total['lactate_missing']}\n")
            f.write(f"  升压药缺失: {total['vasopressor_missing']}\n")
            f.write(f"  SOFA缺失: {total['sofa_missing']}\n")
            f.write(f"  T0缺失: {total['t0_missing']}\n")

            f.write("\n逐层损失分析:\n")
            f.write(f"  Layer 0 (ICU入科): {total['icu_events']} 事件\n")
            f.write(f"  Layer 1 (感染诊断): {total['infection_diag_count']} 人\n")
            f.write(f"  Layer 2 (原始候选): {total['raw_den_candidates']} 人\n")
            f.write(f"  Layer 3 (K1∧K2): {total['k1_and_k2']} 人\n")
            f.write(f"  Layer 4 (最终分母): {total['final_den_1h']} 人\n")
            f.write(f"  Layer 5 (分子1h): {total['num_1h']} 人\n")

    print(f"审计摘要已写入: {summary_path}")
    print("\n审计完成。")


if __name__ == "__main__":
    main()
