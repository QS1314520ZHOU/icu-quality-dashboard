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
from datetime import datetime, timedelta
from typing import Optional
from pymongo import MongoClient, ASCENDING
from db import (
    get_client, get_datacenter_client, BED_DB_NAMES,
    get_open_bed_count, get_occupied_bed_days, get_staff_count,
    get_icu04_apache_data, get_bundle_data, get_icu06_data,
    get_dvt_prevention_patients, get_icu08_data,
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
    """ICU-05: Bundle完成率 (1h/3h/6h)"""
    d = get_bundle_data(dept_codes, start, end)
    key = f"h{hour[0]}_num"
    num = d.get(key, 0)
    den = d["total"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


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


def _compute_icu08(dept_codes, start, end):
    """ICU-08: ARDS俯卧位实施率"""
    d = get_icu08_data(dept_codes, start, end)
    num = d["num_count"]
    den = d["den_count"]
    val = round(num / den * 100, 1) if den > 0 else 0.0
    return {"num": num, "den": den, "val": val, "val_type": "percent"}


def _count_icu_patients(dept_codes, start, end):
    """辅助：统计期内在科患者数"""
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        end_wide = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
        for db_name in BED_DB_NAMES:
            try:
                db = get_client(db_name)[db_name]
                return db.patient.count_documents({
                    "deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"},
                    "icuAdmissionTime": {"$lte": end_wide},
                    "$or": [{"icuDischargeTime": {"$gte": start_dt}}, {"icuDischargeTime": None},
                            {"icuDischargeTime": {"$exists": False}}],
                })
            except Exception: continue
    except Exception: pass
    return 0


# ============================================================
# 2. 指标映射表：indicator_code → compute_function
# ============================================================

INDICATOR_COMPUTERS = {
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
    # ICU-09~19 暂用 mock：分子=0, 分母=在科患者数
}

MOCK_INDICATORS = [
    "ICU-09", "ICU-10", "ICU-11", "ICU-12", "ICU-13", "ICU-14",
    "ICU-15", "ICU-16", "ICU-17", "ICU-18", "ICU-19",
]

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

    stats = {"total": 0, "success": 0, "failed": 0, "errors": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db[SUMMARY_COLLECTION]
            break
        except Exception: continue
    else:
        stats["errors"].append({"error": "No database available"})
        return stats

    for period in periods:
        year, month = period.split("-")
        start = f"{year}-{month}-01"
        end_day = 31 if int(month) in [1,3,5,7,8,10,12] else (30 if int(month) != 2 else 28)
        end = f"{year}-{month}-{end_day:02d}"

        for indicator in indicators:
            stats["total"] += 1
            t0 = time.time()

            try:
                if indicator in INDICATOR_COMPUTERS:
                    result = INDICATOR_COMPUTERS[indicator](dept_codes, start, end)
                elif indicator in MOCK_INDICATORS:
                    den = _count_icu_patients(dept_codes, start, end)
                    result = {"num": 0, "den": den, "val": 0.0, "val_type": "percent"}
                else:
                    raise ValueError(f"Unknown indicator: {indicator}")

                elapsed = int((time.time() - t0) * 1000)

                doc = {
                    "dept_code": ",".join(dept_codes) if len(dept_codes) > 1 else dept_codes[0],
                    "period": period,
                    "indicator": indicator,
                    "numerator": result["num"],
                    "denominator": result["den"],
                    "value": result["val"],
                    "value_type": result.get("val_type", "percent"),
                    "updated_at": datetime.utcnow(),
                    "calc_duration_ms": elapsed,
                }

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

            if progress_callback:
                progress_callback(stats["total"], stats["success"], stats["failed"])

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
            dept_key = ",".join(dept_codes) if len(dept_codes) > 1 else dept_codes[0]
            query = {"dept_code": dept_key, "period": {"$in": periods}}
            if indicators:
                query["indicator"] = {"$in": indicators}
            return list(coll.find(query, {"_id": 0}).sort([("indicator", 1), ("period", 1)]))
        except Exception: continue
    return []
