# summary.py — ICU 质控月度预聚合引擎
"""
预聚合调度：遍历 科室 × 月份 × 指标 → 调用 db 取数函数 → upsert 汇总表。

设计原则：
  1. 只调用现有 get_icuXX_data 函数，不重写取数逻辑
  2. 汇总表只存聚合数字（分子/分母/比值），不存患者明细
  3. 单指标失败不中断整体
  4. 幂等 upsert，可重复执行
"""
import time
import logging

logger = logging.getLogger("summary")
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional
from pymongo import MongoClient, ASCENDING
from db import (
    get_client, get_datacenter_client, BED_DB_NAMES, iter_bed_dbs,
    get_open_bed_count, get_occupied_bed_days, get_staff_count,
    get_icu04_apache_data, get_bundle_data, get_bundle_data_v2, get_icu06_data, get_icu09_data, get_icu10_data,
    get_icu11_data, get_icu12_data, get_icu13_data, get_icu14_data, get_icu15_data,
    get_icu16_data, get_icu17_data, get_icu18_data, get_icu19_data, get_cauti_data,
    get_dvt_prevention_patients, get_icu08_data,
    get_patient_census, get_patient_census_detail,
)

# ============================================================
# 1. 指标 → 取数函数 映射表
# ============================================================

def _compute_icu01(dept_codes, start, end):
    """ICU-01: ICU床位使用率"""
    days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
    num = sum(get_occupied_bed_days(dc, start, end) for dc in dept_codes)
    total_beds = sum(get_open_bed_count(dc, start, end) for dc in dept_codes)
    if total_beds == 0:
        for db_name in BED_DB_NAMES:
            try:
                db = get_client(db_name)[db_name]
                total_beds = sum(db.configBed.count_documents({"deptCode": dc}) for dc in dept_codes)
                if total_beds > 0: break
            except Exception: continue
    den = total_beds * days
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu02(dept_codes, start, end):
    """ICU-02: 医师床位比"""
    docs = sum(get_staff_count(dc, "doctor") for dc in dept_codes)
    beds = sum(get_open_bed_count(dc, start, end) for dc in dept_codes)
    if beds == 0: beds = 20
    val = round(docs / beds, 2) if beds > 0 else 0
    return {"num": docs, "den": beds, "val": val, "val_type": "ratio"}


def _compute_icu03(dept_codes, start, end):
    """ICU-03: 护士床位比"""
    nurses = sum(get_staff_count(dc, "nurse") for dc in dept_codes)
    beds = sum(get_open_bed_count(dc, start, end) for dc in dept_codes)
    if beds == 0: beds = 20
    val = round(nurses / beds, 2) if beds > 0 else 0
    return {"num": nurses, "den": beds, "val": val, "val_type": "ratio"}


def _compute_icu04(dept_codes, start, end):
    """ICU-04: APACHE≥15收治率"""
    d = get_icu04_apache_data(dept_codes, start, end)
    num = min(d["num_count"], d["den_count"])
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu05(dept_codes, start, end, hour):
    """ICU-05: Bundle完成率 (1h/3h/6h) — 使用 V2 双集合查询 + 高召回候选引擎

    Shadow 模式关键规则:
      - official_num/official_den/official_val 使用旧口径 (K1 AND K2)
      - candidate_shadow_num/candidate_shadow_den 使用候选引擎结果
      - 新候选不改变正式 num/den/val
      - 新候选完成 Bundle 时能进入影子分子
    """
    from scoring.candidate_engine import compute_candidate_statistics
    from config.candidate_rules import CANDIDATE_ENGINE_MODE

    # 6h 固定返回 rule_pending/null (规则待主任确认)
    if hour == "6h":
        return {
            "num": None, "den": None, "val": None, "val_type": "percent",
            "data_available": False, "status": "rule_pending",
        }

    d = get_bundle_data_v2(dept_codes, start, end)
    period = start[:7]  # "YYYY-MM"
    hour_key = f"h{hour[0]}_patients"

    # Step 1: 候选信息已在 get_bundle_data_v2 → judge_bundle_v3_for_patient 中唯一计算
    # 此处直接复用 v3["candidate_info"]，不重复调用 extract_candidate
    all_den_candidates = d.get("den_patients", [])

    for pat in all_den_candidates:
        v3 = pat.get("v3", {})
        candidate_info = v3.get("candidate_info") or pat.get("candidate_info") or {}
        pat["candidate_info"] = candidate_info
        pat["is_septic_shock_candidate"] = candidate_info.get("is_septic_shock_candidate", False)
        pat["candidate_status"] = candidate_info.get("candidate_status", "not_candidate")
        pat["clinical_confirmation_status"] = candidate_info.get("clinical_confirmation_status", "insufficient")

    # Step 2: 候选统计
    cand_summary = compute_candidate_statistics(all_den_candidates)

    # Step 3: Shadow 模式 — 正式分母使用旧口径
    # 旧口径: K1 AND K2
    official_den_patients = [
        p for p in all_den_candidates
        if p.get("v3", {}).get("k1") == True and p.get("v3", {}).get("k2") == True
    ]

    # 新口径候选分母 (影子)
    candidate_den_patients = [
        p for p in all_den_candidates
        if p.get("candidate_status") != "not_candidate"
    ]

    if CANDIDATE_ENGINE_MODE == "shadow":
        # shadow 模式: 正式分母使用旧口径
        qualified_den = official_den_patients
    else:
        # active 模式: 正式分母使用候选引擎结果
        qualified_den = candidate_den_patients

    # Step 4: 分子必须是合格分母的子集
    den_exclusion_keys = {p.get("exclusion_key") for p in qualified_den if p.get("exclusion_key")}
    num_candidates = d.get(hour_key, [])
    qualified_num = [
        p for p in num_candidates
        if p.get("exclusion_key") in den_exclusion_keys
    ]

    # Step 5: 应用人工排除
    ex = apply_exclusions(f"ICU-05-{hour}", dept_codes, period, qualified_num, qualified_den)
    num = len(ex["num_items"])
    den = len(ex["den_items"])
    val = round(num / den * 100, 1) if den > 0 else 0.0

    # G-1: 感染部位确认计数
    site_confirmed_count = 0
    site_unconfirmed_count = 0
    try:
        from db import get_infection_site, build_exclusion_key, _get_infection_site_collection
        from config.indicator_windows import SITE_REQUIRED
        if SITE_REQUIRED:
            coll = _get_infection_site_collection()
            if coll is not None:
                confirmed_keys = set()
                for doc in coll.find(
                    {"indicator_code": "ICU-05", "period": period, "revoked_at": None},
                    {"exclusion_key": 1, "_id": 0},
                ):
                    ek = doc.get("exclusion_key", "")
                    if ek:
                        confirmed_keys.add(ek)

                for pat in qualified_den:
                    pid = pat.get("pid") or pat.get("dc_pid") or pat.get("_id") or ""
                    t0 = pat.get("t0")
                    if not pid or not t0:
                        continue
                    ek = build_exclusion_key(str(pid), t0)
                    if ek in confirmed_keys:
                        site_confirmed_count += 1
                    else:
                        site_unconfirmed_count += 1
    except Exception:
        pass

    # 统计新口径差异
    new_shock_count = len(candidate_den_patients)
    old_shock_count = len(official_den_patients)
    shock_diff = new_shock_count - old_shock_count

    # SOFA-2 评分统计
    sofa2_scores = [p.get("sofa2_total") for p in candidate_den_patients if p.get("sofa2_total") is not None]
    sofa2_mean = round(sum(sofa2_scores) / len(sofa2_scores), 1) if sofa2_scores else None

    # ============================================================
    # Shadow 模式完整指标
    # ============================================================
    shadow_den_patients = candidate_den_patients
    shadow_den_exclusion_keys = {p.get("exclusion_key") for p in shadow_den_patients if p.get("exclusion_key")}

    # Shadow 分子: 影子分母中完成 Bundle 的患者
    # 合并: 旧口径分子(h1_patients) + 新候选影子分子(shadow_h1_patients)
    # 去重: 用 exclusion_key 防止同一患者重复计入
    official_h1_in_shadow = [
        p for p in d.get("h1_patients", [])
        if p.get("exclusion_key") in shadow_den_exclusion_keys
    ]
    shadow_only_h1 = [
        p for p in d.get("shadow_h1_patients", [])
        if p.get("exclusion_key") in shadow_den_exclusion_keys
    ]
    seen_keys_1h = {p.get("exclusion_key") for p in official_h1_in_shadow if p.get("exclusion_key")}
    for p in shadow_only_h1:
        if p.get("exclusion_key") not in seen_keys_1h:
            official_h1_in_shadow.append(p)
    shadow_num_1h_candidates = official_h1_in_shadow

    official_h3_in_shadow = [
        p for p in d.get("h3_patients", [])
        if p.get("exclusion_key") in shadow_den_exclusion_keys
    ]
    shadow_only_h3 = [
        p for p in d.get("shadow_h3_patients", [])
        if p.get("exclusion_key") in shadow_den_exclusion_keys
    ]
    seen_keys_3h = {p.get("exclusion_key") for p in official_h3_in_shadow if p.get("exclusion_key")}
    for p in shadow_only_h3:
        if p.get("exclusion_key") not in seen_keys_3h:
            official_h3_in_shadow.append(p)
    shadow_num_3h_candidates = official_h3_in_shadow

    # Shadow 人工排除 (1h 和 3h 分别排除，分母可能不同)
    shadow_ex_1h = apply_exclusions(f"ICU-05-1h", dept_codes, period, shadow_num_1h_candidates, shadow_den_patients)
    shadow_ex_3h = apply_exclusions(f"ICU-05-3h", dept_codes, period, shadow_num_3h_candidates, shadow_den_patients)

    # 关键: 1h 和 3h 各自使用自己的排除后分母
    shadow_den_1h = len(shadow_ex_1h["den_items"])
    shadow_den_3h = len(shadow_ex_3h["den_items"])
    shadow_num_1h = len(shadow_ex_1h["num_items"])
    shadow_num_3h = len(shadow_ex_3h["num_items"])
    shadow_rate_1h = round(shadow_num_1h / shadow_den_1h * 100, 1) if shadow_den_1h > 0 else 0.0
    shadow_rate_3h = round(shadow_num_3h / shadow_den_3h * 100, 1) if shadow_den_3h > 0 else 0.0

    # Shadow excluded counts
    shadow_excluded_den_1h = shadow_ex_1h["excluded_den"]
    shadow_excluded_num_1h = shadow_ex_1h["excluded_num"]
    shadow_excluded_den_3h = shadow_ex_3h["excluded_den"]
    shadow_excluded_num_3h = shadow_ex_3h["excluded_num"]

    # Shadow raw counts (before exclusions)
    shadow_raw_den = len(shadow_den_patients)
    shadow_raw_num_1h = len(shadow_num_1h_candidates)
    shadow_raw_num_3h = len(shadow_num_3h_candidates)

    return {
        # 正式指标 (旧口径 K1 AND K2，shadow模式不变)
        "num": num, "den": den, "val": val, "val_type": "percent",
        "raw_num": ex["raw_num"], "raw_den": ex["raw_den"],
        "excluded_num": ex["excluded_num"], "excluded_den": ex["excluded_den"],
        # Shadow 模式完整指标 (1h/3h 各自独立分母)
        "shadow_raw_den": shadow_raw_den,
        "shadow_den_1h": shadow_den_1h,
        "shadow_num_1h": shadow_num_1h,
        "shadow_rate_1h": shadow_rate_1h,
        "shadow_den_3h": shadow_den_3h,
        "shadow_num_3h": shadow_num_3h,
        "shadow_rate_3h": shadow_rate_3h,
        "shadow_raw_num_1h": shadow_raw_num_1h,
        "shadow_raw_num_3h": shadow_raw_num_3h,
        "shadow_excluded_den_1h": shadow_excluded_den_1h,
        "shadow_excluded_num_1h": shadow_excluded_num_1h,
        "shadow_excluded_den_3h": shadow_excluded_den_3h,
        "shadow_excluded_num_3h": shadow_excluded_num_3h,
        # 其他统计
        "site_confirmed_count": site_confirmed_count,
        "site_unconfirmed_count": site_unconfirmed_count,
        "new_shock_count": new_shock_count,
        "old_shock_count": old_shock_count,
        "shock_diff": shock_diff,
        "sofa2_mean": sofa2_mean,
        "sofa2_scored_count": len(sofa2_scores),
        # 候选引擎统计
        "raw_candidate_count": cand_summary.get("raw_candidate_count", 0),
        "high_probability_count": cand_summary.get("high_probability_count", 0),
        "probable_count": cand_summary.get("probable_count", 0),
        "pending_review_count": cand_summary.get("pending_review_count", 0),
        "not_candidate_count": cand_summary.get("not_candidate_count", 0),
        # Shadow 模式信息
        "candidate_mode": CANDIDATE_ENGINE_MODE,
    }


def _compute_icu06(dept_codes, start, end):
    """ICU-06: 抗菌药物前病原学送检率"""
    d = get_icu06_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu07(dept_codes, start, end):
    """ICU-07: DVT预防率"""
    d = get_dvt_prevention_patients(dept_codes, start, end)
    num = d.get("all_count", 0)
    # 分母 = 在科患者
    den = _count_icu_patients(dept_codes, start, end)
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}



EXCLUSION_COLLECTION = "icu_indicator_exclusion"


def apply_exclusions(code, dept_codes, period, num_items, den_items):
    # type: (str, list, str, list, list) -> dict
    """
    从分子/分母明细中剔除已排除的记录。
    返回 {num_items, den_items, excluded_num, excluded_den, raw_num, raw_den}
    """
    dept_key = ",".join(dept_codes) if len(dept_codes) > 1 else dept_codes[0]
    excluded_keys = set()
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db[EXCLUSION_COLLECTION]
            docs = coll.find(
                {"dept_code": dept_key, "period": period, "code": code, "excluded": True},
                {"exclusion_key": 1, "_id": 0},
            )
            excluded_keys = {d["exclusion_key"] for d in docs}
            break
        except Exception:
            continue

    raw_num = len(num_items)
    raw_den = len(den_items)

    filtered_num = [item for item in num_items if item.get("exclusion_key") not in excluded_keys]
    filtered_den = [item for item in den_items if item.get("exclusion_key") not in excluded_keys]

    return {
        "num_items": filtered_num,
        "den_items": filtered_den,
        "excluded_num": raw_num - len(filtered_num),
        "excluded_den": raw_den - len(filtered_den),
        "raw_num": raw_num,
        "raw_den": raw_den,
    }


def _compute_icu08(dept_codes, start, end):
    """ICU-08: ARDS俯卧位实施率（支持人工排除）"""
    d = get_icu08_data(dept_codes, start, end)
    period = start[:7]  # "YYYY-MM"
    ex = apply_exclusions("ICU-08", dept_codes, period,
                          d.get("num_patients", []), d.get("den_patients", []))
    raw_num = ex["raw_num"]
    raw_den = ex["raw_den"]
    excluded_num = ex["excluded_num"]
    excluded_den = ex["excluded_den"]
    num = raw_num - excluded_num
    den = raw_den - excluded_den
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {
        "num": num, "den": den, "val": val, "val_type": "percent",
        "raw_num": raw_num, "raw_den": raw_den,
        "excluded_num": excluded_num, "excluded_den": excluded_den,
    }


def _compute_icu09(dept_codes, start, end):
    """ICU-09: 镇痛评估率"""
    d = get_icu09_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu10(dept_codes, start, end):
    """ICU-10: 镇静评估率"""
    d = get_icu10_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu11(dept_codes, start, end):
    """ICU-11: ICU患者标化病死指数(SMR)"""
    d = get_icu11_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den, 2) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "ratio"}


def _compute_icu12(dept_codes, start, end):
    """ICU-12: 非计划气管插管拔管率"""
    d = get_icu12_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu13(dept_codes, start, end):
    """ICU-13: 拔管后48h再插管率"""
    d = get_icu13_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu14(dept_codes, start, end):
    """ICU-14: 非计划转入ICU率"""
    d = get_icu14_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu15(dept_codes, start, end):
    """ICU-15: 转出ICU后48h重返率"""
    d = get_icu15_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu16(dept_codes, start, end):
    """ICU-16: VAP发病率"""
    d = get_icu16_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 1000, 2) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "permille"}


def _compute_icu17(dept_codes, start, end):
    """ICU-17: CRBSI发病率"""
    d = get_icu17_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 1000, 2) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "permille"}


def _compute_icu18(dept_codes, start, end):
    """ICU-18: 急性脑损伤患者意识评估率"""
    d = get_icu18_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 2) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_icu19(dept_codes, start, end):
    """ICU-19: 48h内肠内营养启动率"""
    d = get_icu19_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 2) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _compute_cauti(dept_codes, start, end):
    """CAUTI: 尿管相关感染率"""
    d = get_cauti_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 1000, 2) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "permille"}


def _count_icu_patients(dept_codes, start, end):
    """辅助：统计期内在科患者数（原有 + 新入）"""
    try:
        c = get_patient_census(dept_codes, start, end, distinct_by="admission")
        return c["total"]
    except Exception:
        return 0


# ============================================================
# 2. 指标映射表：indicator_code → compute_function
# ============================================================

def _compute_census(dept_codes, start, end):
    """ICU-00: 患者动态（原有/新入/出科/期末）"""
    c = get_patient_census(dept_codes, start, end)
    carry_in = c["carry_in"]
    total = c["total"]
    val = round(carry_in / total * 100, 1) if total > 0 else 0.0
    return {
        "num": carry_in, "den": total, "val": val, "val_type": "percent",
        "census": {
            "carry_in": c["carry_in"], "new_admit": c["new_admit"],
            "discharge": c["discharge"], "carry_out": c["carry_out"],
            "total": c["total"],
        },
    }


INDICATOR_COMPUTERS = {
    "ICU-00": _compute_census,
    "ICU-01": _compute_icu01,
    "ICU-02": _compute_icu02,
    "ICU-03": _compute_icu03,
    "ICU-04": _compute_icu04,
    "ICU-05-1h": lambda dc, s, e: _compute_icu05(dc, s, e, "1h"),
    "ICU-05-3h": lambda dc, s, e: _compute_icu05(dc, s, e, "3h"),
    "ICU-05-6h": lambda dc, s, e: _compute_icu05(dc, s, e, "6h"),
    "ICU-06": _compute_icu06,
    "ICU-07": _compute_icu07,
    "ICU-08": _compute_icu08,
    "ICU-09": _compute_icu09,
    "ICU-10": _compute_icu10,
    "ICU-11": _compute_icu11,
    "ICU-12": _compute_icu12,
    "ICU-13": _compute_icu13,
    "ICU-14": _compute_icu14,
    "ICU-15": _compute_icu15,
    "ICU-16": _compute_icu16,
    "ICU-17": _compute_icu17,
    "ICU-18": _compute_icu18,
    "ICU-19": _compute_icu19,
    "CAUTI": _compute_cauti,
}

MOCK_INDICATORS = []
NO_DATA_INDICATORS = set()

# ============================================================
# 3. 汇总表结构 & 索引
# ============================================================

SUMMARY_COLLECTION = "icu_monthly_summary"

SUMMARY_INDEXES = [
    ({"dept_code": 1, "period": 1, "indicator": 1}, True),   # 唯一索引
    ({"period": 1}, False),
    ({"indicator": 1, "period": 1}, False),
]


def ensure_summary_collection():
    """创建汇总表索引（幂等）"""
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db[SUMMARY_COLLECTION]
            for keys, unique in SUMMARY_INDEXES:
                try:
                    coll.create_index(list(keys.items()), unique=unique, background=True)
                except Exception: pass
            break
        except Exception: continue


# ============================================================
# 4. 预聚合主函数
# ============================================================

def rebuild_summary(dept_codes: list, periods: list, indicators: list = None,
                    progress_callback=None) -> dict:
    """
    遍历 科室 × 月份 × 指标，调用取数函数，upsert 到汇总表。

    返回: {total, success, failed, errors: [{period, indicator, error}]}
    """
    if indicators is None:
        indicators = list(INDICATOR_COMPUTERS.keys()) + MOCK_INDICATORS

    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "errors": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db[SUMMARY_COLLECTION]
            break
        except Exception: continue
    else:
        stats["errors"].append({"error": "No database available"})
        return stats

    def _emit_progress(current_period: str = "", current_indicator: str = "", event: str = "progress"):
        if not progress_callback:
            return
        try:
            progress_callback(
                stats["total"],
                stats["success"],
                stats["failed"],
                current_period,
                current_indicator,
                event,
            )
        except TypeError:
            progress_callback(stats["total"], stats["success"], stats["failed"])

    def _compute_one(period: str, indicator: str) -> dict:
        _emit_progress(period, indicator, "started")
        year, month = period.split("-")
        start = f"{year}-{month}-01"
        import calendar
        end_day = calendar.monthrange(int(year), int(month))[1]
        end = f"{year}-{month}-{end_day:02d}"
        t0 = time.time()
        if indicator not in INDICATOR_COMPUTERS:
            raise ValueError(f"Unknown indicator: {indicator}")
        result = INDICATOR_COMPUTERS[indicator](dept_codes, start, end)
        elapsed = int((time.time() - t0) * 1000)
        census_data = result.pop("census", None)
        data_available = result.pop("data_available", True)
        raw_num = result.pop("raw_num", None)
        raw_den = result.pop("raw_den", None)
        excluded_num = result.pop("excluded_num", None)
        excluded_den = result.pop("excluded_den", None)
        site_confirmed_count = result.pop("site_confirmed_count", None)
        site_unconfirmed_count = result.pop("site_unconfirmed_count", None)
        new_shock_count = result.pop("new_shock_count", None)
        old_shock_count = result.pop("old_shock_count", None)
        shock_diff = result.pop("shock_diff", None)
        sofa2_mean = result.pop("sofa2_mean", None)
        sofa2_scored_count = result.pop("sofa2_scored_count", None)
        # 查询三层人工覆盖计数
        override_count = 0
        try:
            from db import get_client, BED_DB_NAMES
            for db_name in BED_DB_NAMES:
                try:
                    db = get_client(db_name)[db_name]
                    month_start = datetime(int(year), int(month), 1)
                    next_month_start = month_start + timedelta(days=end_day)
                    override_count = db.icu_manual_override.count_documents({
                        "created_at": {
                            "$gte": month_start,
                            "$lt": next_month_start,
                        },
                    })
                    break
                except Exception:
                    continue
        except Exception:
            pass

        doc = {
            "dept_code": ",".join(dept_codes) if len(dept_codes) > 1 else (dept_codes[0] if dept_codes else "all"),
            "period": period,
            "indicator": indicator,
            "numerator": result["num"],
            "denominator": result["den"],
            "value": result["val"],
            "value_type": result.get("val_type", "percent"),
            "updated_at": datetime.utcnow(),
            "calc_duration_ms": elapsed,
            "data_available": data_available,
            "override_count": override_count,
        }
        if census_data:
            doc["census"] = census_data
        if raw_num is not None:
            doc["raw_num"] = raw_num
            doc["raw_den"] = raw_den
            doc["excluded_num"] = excluded_num
            doc["excluded_den"] = excluded_den
        if site_confirmed_count is not None:
            doc["site_confirmed_count"] = site_confirmed_count
            doc["site_unconfirmed_count"] = site_unconfirmed_count
        if new_shock_count is not None:
            doc["new_shock_count"] = new_shock_count
            doc["old_shock_count"] = old_shock_count
            doc["shock_diff"] = shock_diff
        if sofa2_mean is not None:
            doc["sofa2_mean"] = sofa2_mean
            doc["sofa2_scored_count"] = sofa2_scored_count
        return doc

    light_first = {
        "ICU-00": 10, "ICU-01": 10, "ICU-02": 10, "ICU-03": 10,
        "ICU-04": 20, "ICU-05-1h": 20, "ICU-05-3h": 20, "ICU-05-6h": 20,
        "ICU-07": 20, "ICU-08": 20, "ICU-09": 30, "ICU-10": 30,
        "ICU-12": 30, "ICU-13": 30, "ICU-14": 30, "ICU-15": 30,
        "ICU-16": 30, "ICU-17": 30, "ICU-18": 30,
        "ICU-06": 90, "ICU-11": 80, "ICU-19": 80,
    }
    tasks = sorted(
        [(period, indicator) for period in periods for indicator in indicators],
        key=lambda item: (light_first.get(item[1], 50), item[0], item[1]),
    )
    max_workers = min(6, max(1, len(tasks)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_compute_one, period, indicator): (period, indicator) for period, indicator in tasks}
        for future in as_completed(futures):
            period, indicator = futures[future]
            try:
                doc = future.result()
                if not doc.get("data_available", True):
                    stats["skipped"] = stats.get("skipped", 0) + 1
                else:
                    coll.update_one(
                        {"dept_code": doc["dept_code"], "period": period, "indicator": indicator},
                        {"$set": doc},
                        upsert=True,
                    )
                stats["success"] += 1

            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append({
                    "period": period, "indicator": indicator,
                    "error": str(e)[:200],
                })

            stats["total"] += 1
            _emit_progress(period, indicator, "finished")

    return stats


def rebuild_recent(months: int = 13):
    """重算最近 N 个月（默认 13 个月覆盖跨年）"""
    now = datetime.utcnow()
    periods = []
    for i in range(months):
        d = now - timedelta(days=30 * i)
        periods.append(f"{d.year}-{d.month:02d}")
    periods.reverse()

    # 获取全部科室
    dept_codes = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            docs = list(db.department.find({}, {"code": 1}))
            if docs:
                dept_codes = [d["code"] for d in docs]
                break
        except Exception: continue

    print(f"[rebuild] Starting rebuild: {len(dept_codes)} depts × {len(periods)} periods = ~{len(dept_codes)*len(periods)} calcs")
    stats = rebuild_summary(dept_codes, periods)
    print(f"[rebuild] Done: {stats['success']}/{stats['total']} success, {stats['failed']} failed")
    if stats["errors"]:
        for e in stats["errors"][:5]:
            print(f"  FAIL: {e['period']} {e['indicator']}: {e['error']}")
    return stats


# ============================================================
# 5. 读汇总接口
# ============================================================

def read_summary(dept_codes: list, periods: list, indicators: list = None) -> list:
    """从汇总表读取聚合数据"""
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db[SUMMARY_COLLECTION]
            dept_key = ",".join(dept_codes) if len(dept_codes) > 1 else (dept_codes[0] if dept_codes else "all")
            query = {"dept_code": dept_key, "period": {"$in": periods}}
            if indicators:
                query["indicator"] = {"$in": [i for i in indicators if i not in NO_DATA_INDICATORS]}
            else:
                query["indicator"] = {"$nin": list(NO_DATA_INDICATORS)}
            return list(coll.find(query, {"_id": 0}).sort([("indicator", 1), ("period", 1)]))
        except Exception: continue
    return []
