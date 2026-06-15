# main.py
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from datetime import date, datetime, timedelta
from ai_analyzer import analyze, get_all_ai_decisions, override_ai_decision, ensure_ai_cache_collection as ensure_ai_cache
from db import get_open_bed_count, get_occupied_bed_days, get_staff_count, get_icu04_apache_data, get_bundle_data, get_icu08_data, get_icu06_data, get_icu09_data, get_icu10_data, get_icu11_data, get_icu12_data, get_icu13_data, get_icu14_data, get_icu15_data, get_icu16_data, get_icu17_data, get_icu18_data, get_icu19_data, get_cauti_data, get_tri_tube_suspected_warnings, confirm_tri_tube_warning, get_dvt_prevention_patients, get_client, BED_DB_NAMES, PROFESSION_CN
import random
import time as time_module
import threading
import uuid
import summary as summary_module

app = FastAPI(title="ICU质控指标API")

# ---- 定时调度（后台线程，每天凌晨跑一次） ----
_scheduler_started = False


def _start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _run_daily():
        while True:
            now = datetime.now()
            # 每天凌晨 2:00 执行
            next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            wait_sec = (next_run - now).total_seconds()
            time_module.sleep(wait_sec)
            try:
                print(f"[scheduler] Starting daily rebuild at {datetime.now()}")
                summary_module.rebuild_recent(months=13)
            except Exception as e:
                print(f"[scheduler] Error: {e}")

    t = threading.Thread(target=_run_daily, daemon=True)
    t.start()
    print("[scheduler] Daily rebuild scheduler started")


@app.on_event("startup")
def on_startup():
    summary_module.ensure_summary_collection()
    ensure_detail_cache_collection()
    ensure_ai_cache()
    _start_scheduler()

# 简易缓存（TTL 60秒，支持 nocache 参数强制刷新）
_cache = {}
_CACHE_TTL = 60


def _cache_key(prefix, *args):
    return f"{prefix}:{':'.join(str(a) for a in args)}"


def _cache_get(key, nocache: bool = False):
    if nocache:
        return None
    entry = _cache.get(key)
    if entry and time_module.time() - entry["ts"] < _CACHE_TTL:
        return entry["val"]
    return None


def _cache_set(key, val):
    _cache[key] = {"val": val, "ts": time_module.time()}


DETAIL_CACHE_COLLECTION = "icu_indicator_detail_cache"


def _dept_cache_key(dept_codes: list) -> str:
    return ",".join(dept_codes) if len(dept_codes) > 1 else dept_codes[0]


def _get_detail_cache_collection():
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            return db[DETAIL_CACHE_COLLECTION]
        except Exception:
            continue
    return None


def ensure_detail_cache_collection():
    coll = _get_detail_cache_collection()
    if coll is None:
        return
    try:
        coll.create_index(
            [("dept_code", 1), ("period", 1), ("code", 1), ("part", 1)],
            unique=True,
            background=True,
        )
        coll.create_index([("period", 1), ("code", 1)], background=True)
        coll.create_index([("updated_at", -1)], background=True)
    except Exception as e:
        print(f"[detail-cache] ensure index failed: {e}")


def _is_historical_period(period: str) -> bool:
    try:
        y, m = [int(x) for x in period.split("-")]
        now = datetime.now()
        return (y, m) < (now.year, now.month)
    except Exception:
        return False


def _read_detail_cache(dept_codes: list, period: str, code: str, part: str):
    coll = _get_detail_cache_collection()
    if coll is None:
        return None
    doc = coll.find_one({
        "dept_code": _dept_cache_key(dept_codes),
        "period": period,
        "code": code,
        "part": part,
    }, {"_id": 0})
    if not doc:
        return None
    return doc.get("patients", [])


def _write_detail_cache(dept_codes: list, period: str, code: str, part: str, items: list):
    coll = _get_detail_cache_collection()
    if coll is None:
        return
    coll.update_one(
        {
            "dept_code": _dept_cache_key(dept_codes),
            "period": period,
            "code": code,
            "part": part,
        },
        {
            "$set": {
                "dept_code": _dept_cache_key(dept_codes),
                "period": period,
                "code": code,
                "part": part,
                "patients": items,
                "count": len(items),
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


def _detail_cache_payload(code: str, period: str, part: str, icu_unit: str, nocache: bool = False):
    dept_codes = _resolve_dept_codes(icu_unit)
    if _is_historical_period(period) and not nocache:
        cached = _read_detail_cache(dept_codes, period, code, part)
        if cached is not None:
            return cached
    items = query_detail(code, period, part, icu_unit)
    if _is_historical_period(period):
        _write_detail_cache(dept_codes, period, code, part, items)
    return items


def rebuild_detail_cache(dept_codes: list, periods: list, indicators: list = None,
                         icu_unit: str = "all", progress_callback=None) -> dict:
    indicators = indicators or list(summary_module.INDICATOR_COMPUTERS.keys())
    stats = {"total": 0, "success": 0, "failed": 0, "errors": []}
    tasks = [(p, c, part) for p in periods if _is_historical_period(p)
             for c in indicators for part in ("numerator", "denominator")]
    for period, code, part in tasks:
        try:
            if progress_callback:
                progress_callback(stats["total"], stats["success"], stats["failed"], period, code, part, "started")
            items = query_detail(code, period, part, icu_unit)
            _write_detail_cache(dept_codes, period, code, part, items)
            stats["success"] += 1
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append({"period": period, "indicator": code, "part": part, "error": str(e)[:200]})
        stats["total"] += 1
        if progress_callback:
            progress_callback(stats["total"], stats["success"], stats["failed"], period, code, part, "finished")
    return stats


# 响应头中间件：禁止浏览器缓存 API
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

# deptCode → 科室名称映射（从 department 表读取，带缓存兜底）
DEPT_MAP = {
    "JJL000282": "ICU病区",
    "JJL000283": "ICU护理单元",
    "0801": "ICU病区老",
}

# 前端科室筛选 → deptCode 列表
def _resolve_dept_codes(icu_unit: str) -> list:
    """
    将前端科室筛选参数解析为 deptCode 列表。
    'all' 时从数据库动态加载全部科室编码。
    """
    if icu_unit and icu_unit != "all":
        # 直接按 code 或 name 匹配
        for db_name in BED_DB_NAMES:
            try:
                db = get_client()[db_name]
                doc = db.department.find_one({
                    "$or": [{"code": icu_unit}, {"name": icu_unit}]
                }, {"code": 1})
                if doc:
                    return [doc["code"]]
            except Exception:
                continue
        # 没匹配到，当作 code 直接使用
        return [icu_unit]

    # 'all'：从数据库取所有科室 code
    codes = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client()[db_name]
            docs = list(db.department.find({}, {"code": 1, "_id": 0}))
            if docs:
                codes = [d["code"] for d in docs]
                break
        except Exception:
            continue
    return codes if codes else ["JJL000282", "JJL000283", "0801"]  # 最终兜底

# 19个质控指标的元数据与中文映射
INDICATORS_CONFIG = {
    "ICU-01": {"name": "ICU床位使用率", "unit": "%", "good": (75, 85), "warn": (60, 95), "dir": "range"},
    "ICU-02": {"name": "ICU医师床位比", "unit": ":1", "good": (0.8, 99), "warn": (0.5, 99), "dir": "higher"},
    "ICU-03": {"name": "ICU护士床位比", "unit": ":1", "good": (2.5, 99), "warn": (2.0, 99), "dir": "higher"},
    "ICU-04": {"name": "APACHEⅡ≥15分收治率", "unit": "%", "good": (50, 100), "warn": (30, 100), "dir": "higher"},
    "ICU-05-1h": {"name": "感染性休克1h Bundle完成率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-05-3h": {"name": "感染性休克3h Bundle完成率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-05-6h": {"name": "感染性休克6h Bundle完成率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-06": {"name": "抗菌药物治疗前病原学送检率", "unit": "%", "good": (90, 100), "warn": (50, 100), "dir": "higher"},
    "ICU-07": {"name": "DVT预防率", "unit": "%", "good": (85, 100), "warn": (60, 100), "dir": "higher"},
    "ICU-08": {"name": "中重度ARDS俯卧位通气实施率", "unit": "%", "good": (80, 100), "warn": (50, 100), "dir": "higher",
               "numerator_desc": "住院期间有俯卧位记录的患者数",
               "denominator_desc": "中重度ARDS患者数(P/F<150且PEEP≥5且有创氧疗途径)"},
    "ICU-09": {"name": "ICU镇痛评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-10": {"name": "ICU镇静评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-11": {"name": "ICU患者标化病死指数(SMR)", "unit": "", "good": (0, 1.0), "warn": (0, 1.2), "dir": "lower"},
    "ICU-12": {"name": "非计划气管插管拔管率", "unit": "%", "good": (0, 5), "warn": (0, 10), "dir": "lower"},
    "ICU-13": {"name": "拔管后48h再插管率", "unit": "%", "good": (0, 5), "warn": (0, 12), "dir": "lower"},
    "ICU-14": {"name": "非计划转入ICU率", "unit": "%", "good": (0, 5), "warn": (0, 10), "dir": "lower"},
    "ICU-15": {"name": "转出ICU后48h重返率", "unit": "%", "good": (0, 3), "warn": (0, 6), "dir": "lower"},
    "ICU-16": {"name": "VAP发病率", "unit": "‰", "good": (0, 8), "warn": (0, 15), "dir": "lower"},
    "ICU-17": {"name": "CRBSI发病率", "unit": "‰", "good": (0, 2), "warn": (0, 5), "dir": "lower"},
    "ICU-18": {"name": "急性脑损伤意识评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-19": {"name": "48h内肠内营养启动率", "unit": "%", "good": (80, 100), "warn": (50, 100), "dir": "higher"},
    "CAUTI": {"name": "CAUTI尿管相关感染率", "unit": "‰", "good": (0, 2), "warn": (0, 5), "dir": "lower"},
}

NAME_MAP = {code: cfg["name"] for code, cfg in INDICATORS_CONFIG.items()}
UNIT_MAP = {code: cfg["unit"] for code, cfg in INDICATORS_CONFIG.items()}
NO_DATA_INDICATORS = set()

# 数据源详细说明 (供下钻明细弹窗使用)
SOURCE_DESC = {
    "ICU-01": {"numerator": "实际占用床位数累计之和", "denominator": "实际开放床位数累计之和"},
    "ICU-02": {"numerator": "ICU在岗执业医师总人数", "denominator": "实际开放床位数总和"},
    "ICU-03": {"numerator": "ICU在岗执业护士总人数", "denominator": "实际开放床位数总和"},
    "ICU-04": {"numerator": "首次APACHEⅡ评分≥15分的患者数", "denominator": "同期入住ICU的患者总人数"},
    "ICU-05-1h": {"numerator": "1h内完成bundle患者数", "denominator": "确诊感染性休克患者数"},
    "ICU-05-3h": {"numerator": "3h内完成bundle患者数", "denominator": "确诊感染性休克患者数"},
    "ICU-05-6h": {"numerator": "6h内完成bundle患者数", "denominator": "确诊感染性休克患者数"},
    "ICU-06": {"numerator": "首剂抗菌药前完成病原学送检(培养/镜检/免疫/分子)的患者数", "denominator": "以治疗为目的使用抗菌药的患者数(已剔除围术期/短疗程预防)"},
    "ICU-07": {"numerator": "实施物理或药物DVT预防措施的患者数", "denominator": "同期入住ICU的所有患者数"},
    "ICU-08": {"numerator": "实施俯卧位通气治疗的患者数", "denominator": "满足PEEP≥5且OI≤150的ARDS患者数"},
    "ICU-09": {"numerator": "进行镇痛评分(NRS/CPOT/BPS)测定的患者数", "denominator": "同期入住ICU的所有患者数"},
    "ICU-10": {"numerator": "进行镇静评分(RASS/SAS)测定的患者数", "denominator": "同期入住ICU的所有患者数"},
    "ICU-11": {"numerator": "实际死亡患者总数", "denominator": "预计死亡概率(SMR公式计算)累计总和"},
    "ICU-12": {"numerator": "非计划自行拔除气管导管的例数", "denominator": "行气管插管机械通气拔管的总例数"},
    "ICU-13": {"numerator": "气管插管拔除后48小时内重新插管的例数", "denominator": "行气管插管机械通气拔管的总例数"},
    "ICU-14": {"numerator": "非计划由手术室/病房转入ICU的患者数", "denominator": "同期手术后入ICU患者的总人数"},
    "ICU-15": {"numerator": "转出ICU后48小时内再次因同一/新发病情收治入ICU的患者数", "denominator": "同期转出ICU的患者总人数"},
    "ICU-16": {"numerator": "新发生呼吸机相关性肺炎(VAP)的例次数", "denominator": "有创呼吸机累计使用总天数"},
    "ICU-17": {"numerator": "新发生中心导管相关血流感染(CRBSI)的例次数", "denominator": "中心血管导管患者-导管日：同一患者同一日存在≥1根中心静脉导管/PICC/中心静脉透析或CRRT通路计1日；动脉导管、PICCO、中长导管等非中心导管不计入；置管日与拔管日均按占用日历日计入"},
    "ICU-18": {"numerator": "进行意识状态评分(GCS/FOUR)测定的急性脑损伤患者数", "denominator": "同期收治的急性脑损伤患者总数"},
    "ICU-19": {"numerator": "入科48小时内启动肠内营养(EN)支持的患者数", "denominator": "同期入住ICU时间超过48小时的患者总数"},
    "CAUTI": {"numerator": "新发生尿管相关感染(CAUTI)的例次数", "denominator": "导尿管留置累计使用总天数"},
}

# 基础Mock数据产生器
def get_mock_base_values():
    return {
        "ICU-01": 82.3, "ICU-02": 0.9, "ICU-03": 2.8, "ICU-04": 58.2,
        "ICU-05-1h": 88.0, "ICU-05-3h": 76.0, "ICU-05-6h": 65.0, "ICU-06": 93.5,
        "ICU-07": 87.1, "ICU-08": 72.4, "ICU-09": 95.2, "ICU-10": 91.8,
        "ICU-11": 0.92, "ICU-12": 3.2, "ICU-13": 4.1, "ICU-14": 6.8,
        "ICU-15": 2.5, "ICU-16": 9.1, "ICU-17": 1.8, "ICU-18": 89.3, "ICU-19": 78.6,
    }

def eval_status(code, val) -> str:
    cfg = INDICATORS_CONFIG.get(code)
    if not cfg:
        return "unknown"
    if isinstance(val, dict):
        val = val.get("3h", 75.0)
    
    g_lo, g_hi = cfg["good"]
    w_lo, w_hi = cfg["warn"]
    if g_lo <= val <= g_hi:
        return "good"
    if w_lo <= val <= w_hi:
        return "warn"
    return "danger"


def _summary_row_to_api(r: dict) -> dict:
    code = r["indicator"]
    value = r.get("value", 0)
    numerator = r.get("numerator")
    denominator = r.get("denominator")
    if code in NO_DATA_INDICATORS and (numerator in (0, None)) and denominator:
        numerator = None
        denominator = None
        value = None
    return {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "unit": UNIT_MAP.get(code, ""),
        "status": "unknown" if value is None else eval_status(code, value),
    }


def _calc_value(code: str, numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    if code == "ICU-11":
        return round(numerator / denominator, 2)
    if code == "ICU-18":
        return round(numerator / denominator * 100, 2)
    unit = UNIT_MAP.get(code, "")
    if unit == "‰":
        return round(numerator / denominator * 1000, 1)
    if unit == ":1":
        return round(numerator / denominator, 1)
    return round(numerator / denominator * 100, 1)


def _live_summary_row(code: str, period: str, icu_unit: str) -> dict | None:
    year, month = period.split("-")
    start_date = f"{year}-{month}-01"
    end_day = 31 if int(month) in [1,3,5,7,8,10,12] else (30 if int(month) != 2 else 28)
    end_date = f"{year}-{month}-{end_day:02d}"
    dept_codes = _resolve_dept_codes(icu_unit)

    data = None
    if code == "ICU-09":
        data = get_icu09_data(dept_codes, start_date, end_date)
    elif code == "ICU-10":
        data = get_icu10_data(dept_codes, start_date, end_date)
    elif code == "ICU-11":
        data = get_icu11_data(dept_codes, start_date, end_date)
    elif code == "ICU-12":
        data = get_icu12_data(dept_codes, start_date, end_date)
    elif code == "ICU-13":
        data = get_icu13_data(dept_codes, start_date, end_date)
    elif code == "ICU-14":
        data = get_icu14_data(dept_codes, start_date, end_date)
    elif code == "ICU-15":
        data = get_icu15_data(dept_codes, start_date, end_date)
    elif code == "ICU-16":
        data = get_icu16_data(dept_codes, start_date, end_date)
    elif code == "ICU-17":
        data = get_icu17_data(dept_codes, start_date, end_date)
    elif code == "ICU-18":
        data = get_icu18_data(dept_codes, start_date, end_date)
    elif code == "ICU-19":
        data = get_icu19_data(dept_codes, start_date, end_date)
    elif code == "CAUTI":
        data = get_cauti_data(dept_codes, start_date, end_date)
    if not data:
        return None

    numerator = data.get("num_count", 0)
    denominator = data.get("den_count", 0)
    value = _calc_value(code, numerator, denominator)
    return {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "unit": UNIT_MAP.get(code, ""),
        "status": eval_status(code, value),
    }


def _repair_stale_summary_rows(rows: list, period: str, icu_unit: str) -> list:
    fixed = []
    for row in rows:
        code = row.get("code")
        if code in NO_DATA_INDICATORS:
            fixed.append(_empty_indicator_row(code))
            continue
        needs_live = (
            code in ("ICU-09", "ICU-10") and row.get("numerator", 0) == 0
        ) or (
            code == "ICU-11" and (row.get("numerator", 0) == 0 or row.get("value", 0) == 0)
        ) or (
            code in ("ICU-12", "ICU-13", "ICU-14", "ICU-15", "ICU-16", "ICU-17", "ICU-18", "ICU-19", "CAUTI") and row.get("value", 0) == 0
        )
        if needs_live:
            live = _live_summary_row(row["code"], period, icu_unit)
            if live and (live.get("numerator", 0) > 0 or live.get("denominator", 0) > 0):
                fixed.append(live)
                continue
        fixed.append(row)
    return fixed


def _empty_indicator_row(code: str) -> dict:
    return {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "numerator": None,
        "denominator": None,
        "value": None,
        "unit": UNIT_MAP.get(code, ""),
        "status": "unknown",
    }


def _ensure_no_data_indicator_rows(rows: list) -> list:
    by_code = {r.get("code"): r for r in rows}
    for code in NO_DATA_INDICATORS:
        by_code[code] = _empty_indicator_row(code)
    return sorted(by_code.values(), key=lambda x: x.get("code", ""))

# ---- ICU-01 分母：从 MongoDB 读取实际开放床位日数 ----
def get_icu01_bed_days(dept: str, start_date: str, end_date: str) -> int:
    """
    ICU床位使用率 分母 = 实际开放总床日数（开放床位数 × 统计天数）。

    优先 bedRecord（deptCode 支持逗号分隔多科室 + time + bedNum），
    兜底 configBed（统计 hisName 条数）。

    dept=all 时汇总全部 ICU 科室的床位数，再乘以天数。
    """
    dept_codes = _resolve_dept_codes(dept)

    # 计算统计天数
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d")
        days = (ed - sd).days + 1
        if days <= 0:
            days = 30
    except Exception:
        days = 30

    # 汇总各科室床位数
    total_beds = 0
    for dc in dept_codes:
        total_beds += get_open_bed_count(dc, start_date, end_date)

    # 无数据兜底：跨库 configBed 总计
    if total_beds == 0:
        for db_name in BED_DB_NAMES:
            try:
                db = get_client()[db_name]
                total_beds = sum(
                    db.configBed.count_documents({"deptCode": dc})
                    for dc in dept_codes
                )
                if total_beds > 0:
                    break
            except Exception:
                continue

    return total_beds * days


# ---- 辅助数据查询实现 ----
def query_summary(period: str, icu_unit: str = "all"):
    """
    第一级：某月所有指标的汇总列表，包括分子分母
    """
    # 计算当月的起止日期
    year, month = period.split("-")
    start_date = f"{year}-{month}-01"
    end_day = 31 if int(month) in [1,3,5,7,8,10,12] else (30 if int(month) != 2 else 28)
    end_date = f"{year}-{month}-{end_day:02d}"

    # ----- ICU-01 分母：从 MongoDB 取真实床位日数 -----
    icu01_den = get_icu01_bed_days(icu_unit, start_date, end_date)

    # ----- ICU-01 分子：从 patient 表取实际占用总床日数 -----
    icu01_num = 0
    dept_codes = _resolve_dept_codes(icu_unit)
    for dc in dept_codes:
        icu01_num += get_occupied_bed_days(dc, start_date, end_date)

    # 计算 ICU-01 比值
    if icu01_num > 0 and icu01_den > 0:
        icu01_value = round(icu01_num / icu01_den * 100, 1)
    elif icu01_den > 0:
        icu01_value = 0.0
    else:
        icu01_value = None

    # ----- ICU-02/03 分子：从 account 表取真实医师/护士人数 -----
    icu02_num = 0
    icu03_num = 0
    for dc in dept_codes:
        icu02_num += get_staff_count(dc, "doctor")
        icu03_num += get_staff_count(dc, "nurse")

    # ICU-02/03 分母 = 开放床位数
    icu02_den = 0
    for dc in dept_codes:
        icu02_den += get_open_bed_count(dc, start_date, end_date)

    # ----- ICU-04 分子分母：从 score 表取真实 APACHEⅡ 数据 -----
    icu04_data = get_icu04_apache_data(dept_codes, start_date, end_date)
    icu04_num = icu04_data["num_count"]
    icu04_den = icu04_data["den_count"]

    # ----- ICU-06：抗菌药物前病原学送检率（DataCenter.VI_ICU_ZYYZ）-----
    icu06_data = get_icu06_data(dept_codes, start_date, end_date)
    icu06_num = icu06_data["num_count"]
    icu06_den = icu06_data["den_count"]
    if icu06_den == 0:
        icu06_num = 0

    # ----- ICU-09：镇痛评估率（bedside + score 双源）-----
    icu09_data = get_icu09_data(dept_codes, start_date, end_date)
    icu09_num = icu09_data["num_count"]
    icu09_den = icu09_data["den_count"]
    if icu09_den == 0:
        icu09_num = 0

    # ----- ICU-10：镇静评估率（bedside param_score_rass_obs + score rass）-----
    icu10_data = get_icu10_data(dept_codes, start_date, end_date)
    icu10_num = icu10_data["num_count"]
    icu10_den = icu10_data["den_count"]
    if icu10_den == 0:
        icu10_num = 0

    # ----- ICU-11：标化病死指数 SMR（实际死亡数 / 预计死亡数）-----
    icu11_data = get_icu11_data(dept_codes, start_date, end_date)
    icu11_num = icu11_data["num_count"]
    icu11_den = icu11_data["den_count"]

    # ----- ICU-12/13：人工气道非计划拔管与48h再置管 -----
    icu12_data = get_icu12_data(dept_codes, start_date, end_date)
    icu12_num = icu12_data["num_count"]
    icu12_den = icu12_data["den_count"]
    icu13_data = get_icu13_data(dept_codes, start_date, end_date)
    icu13_num = icu13_data["num_count"]
    icu13_den = icu13_data["den_count"]

    # ----- ICU-14：非计划转入ICU率 -----
    icu14_data = get_icu14_data(dept_codes, start_date, end_date)
    icu14_num = icu14_data["num_count"]
    icu14_den = icu14_data["den_count"]
    icu15_data = get_icu15_data(dept_codes, start_date, end_date)
    icu15_num = icu15_data["num_count"]
    icu15_den = icu15_data["den_count"]

    # ----- ICU-16/17/CAUTI：三管院感发病率 -----
    icu16_data = get_icu16_data(dept_codes, start_date, end_date)
    icu16_num = icu16_data["num_count"]
    icu16_den = icu16_data["den_count"]
    icu17_data = get_icu17_data(dept_codes, start_date, end_date)
    icu17_num = icu17_data["num_count"]
    icu17_den = icu17_data["den_count"]
    icu18_data = get_icu18_data(dept_codes, start_date, end_date)
    icu18_num = icu18_data["num_count"]
    icu18_den = icu18_data["den_count"]
    icu19_data = get_icu19_data(dept_codes, start_date, end_date)
    icu19_num = icu19_data["num_count"]
    icu19_den = icu19_data["den_count"]
    cauti_data = get_cauti_data(dept_codes, start_date, end_date)
    cauti_num = cauti_data["num_count"]
    cauti_den = cauti_data["den_count"]

    # ----- ICU-07：DVT预防率（DataCenter.VI_ICU_ZYYZ 医嘱包含匹配）-----
    dvt_data = get_dvt_prevention_patients(dept_codes, start_date, end_date)
    icu07_num = dvt_data.get("all_count", 0)
    icu07_den = icu04_den  # 分母=同期在科患者（同ICU-04）

    # ----- ICU-08：ARDS俯卧位实施率（三闸门分母 + 俯卧位分子）-----
    icu08_data = get_icu08_data(dept_codes, start_date, end_date)
    icu08_num = icu08_data["num_count"]
    icu08_den = icu08_data["den_count"]

    # ----- ICU-05-1h/3h/6h：从 infectionShockV2 表取真实 Bundle 数据 -----
    bundle_data = get_bundle_data(dept_codes, start_date, end_date)
    bun_den = bundle_data["total"]
    bun_1h = bundle_data["h1_num"]
    bun_3h = bundle_data["h3_num"]
    bun_6h = bundle_data["h6_num"]

    summary_data = {
        "ICU-01": {"num": icu01_num, "den": icu01_den},
        "ICU-02": {"num": icu02_num, "den": icu02_den},
        "ICU-03": {"num": icu03_num, "den": icu02_den},
        "ICU-04": {"num": icu04_num, "den": icu04_den},
        "ICU-05-1h": {"num": bun_1h, "den": bun_den},
        "ICU-05-3h": {"num": bun_3h, "den": bun_den},
        "ICU-05-6h": {"num": bun_6h, "den": bun_den},
        "ICU-06": {"num": icu06_num, "den": icu06_den},
        "ICU-07": {"num": icu07_num, "den": icu07_den},
        "ICU-08": {"num": icu08_num, "den": icu08_den},
        "ICU-09": {"num": icu09_num, "den": icu09_den},
        "ICU-10": {"num": icu10_num, "den": icu10_den},
        "ICU-11": {"num": icu11_num, "den": icu11_den},
        "ICU-12": {"num": icu12_num, "den": icu12_den},
        "ICU-13": {"num": icu13_num, "den": icu13_den},
        "ICU-14": {"num": icu14_num, "den": icu14_den},
        "ICU-15": {"num": icu15_num, "den": icu15_den},
        "ICU-16": {"num": icu16_num, "den": icu16_den},
        "ICU-17": {"num": icu17_num, "den": icu17_den},
        "ICU-18": {"num": icu18_num, "den": icu18_den},
        "ICU-19": {"num": icu19_num, "den": icu19_den},
        "CAUTI": {"num": cauti_num, "den": cauti_den},
    }
    
    rows = []
    for code, info in summary_data.items():
        if code == "ICU-01" and icu01_den > 0:
            display_val = icu01_value
            val_for_status = icu01_value
        else:
            # 根据变化后的分子分母重算比值
            if info["den"] in (0, None):
                display_val = None
                val_for_status = None
            else:
                cfg = INDICATORS_CONFIG.get(code, {})
                multiplier = 100
                if cfg.get("unit") == "‰":
                    multiplier = 1000
                elif cfg.get("unit") == ":1":
                    multiplier = 1
                if code == "ICU-11":
                    display_val = round(info["num"] / info["den"], 2)
                elif code == "ICU-18":
                    display_val = round(info["num"] / info["den"] * multiplier, 2)
                else:
                    display_val = round(info["num"] / info["den"] * multiplier, 1)
                val_for_status = display_val
        rows.append({
            "indicator": code,
            "numerator": info["num"],
            "denominator": info["den"],
            "value": display_val,
            "status": "unknown" if val_for_status is None else eval_status(code, val_for_status)
        })
    return rows

def query_trend(code: str, year: int, icu_unit: str = "all"):
    """
    第二级：单指标全年 12 个月趋势数据。只读预聚合表，避免趋势弹窗触发实时重算。
    """
    periods = [f"{year}-{m:02d}" for m in range(1, 13)]
    rows = summary_module.read_summary(_resolve_dept_codes(icu_unit), periods, [code])
    by_period = {r.get("period"): r.get("value") for r in rows}
    return {m: by_period.get(f"{year}-{m:02d}") for m in range(1, 13)}

def query_detail(code: str, period: str, part: str, icu_unit: str = "all"):
    """
    第三级：明细数据。
    ICU-01 分子 → 患者明细（含在床天数）
    ICU-01 分母 → 床位配置明细
    其他指标 → 患者明细
    """
    year, month = period.split("-")
    start_date = f"{year}-{month}-01"
    end_day = 31 if int(month) in [1,3,5,7,8,10,12] else (30 if int(month) != 2 else 28)
    end_date = f"{year}-{month}-{end_day:02d}"

    from datetime import datetime as dt, timedelta
    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    dept_codes = _resolve_dept_codes(icu_unit)

    # ---- ICU-01 分母：床位数 × 天数（汇总，不列明细床位） ----
    if code == "ICU-01" and part == "denominator":
        total_beds = 0
        for db_name in BED_DB_NAMES:
            try:
                db = get_client()[db_name]
                total_beds = sum(
                    db.configBed.count_documents({"deptCode": dc})
                    for dc in dept_codes
                )
                if total_beds > 0:
                    break
            except Exception:
                continue
        days = (end_dt - start_dt).days + 1
        return [{
            "patient_id": "—",
            "name": f"开放床位数 {total_beds} 张 × 统计 {days} 天 = {total_beds * days} 总床日",
            "gender": "",
            "age": "",
            "bed_no": f"{total_beds} 张",
            "dept": "",
            "admit_time": f"统计 {days} 天",
            "discharge_time": "",
            "admission_source": "",
            "value": total_beds * days,
        }]

    # ---- ICU-08：ARDS俯卧位实施率明细 ----
    if code == "ICU-08":
        data = get_icu08_data(dept_codes, start_date, end_date)
        if part == "numerator":
            items = []
            for p in data.get("num_patients", []):
                items.append({
                    "patient_id": p.get("mrn", ""),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": f"俯卧{p.get('prone_count',0)}次",
                    "dept": "",
                    "admit_time": str(p.get("prone_times", [""])[0])[:16] if p.get("prone_times") else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": p.get("prone_count", 0),
                })
            return items
        else:
            items = []
            for p in data.get("den_patients", []):
                flow_v = p.get('flow_val')
                flow_s = f"  流速: {flow_v}L/min" if flow_v is not None else ""
                items.append({
                    "patient_id": p.get("mrn", ""),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": f"P/F={p.get('pf_ratio','?')}  PEEP={p.get('peep','?')}",
                    "dept": "",
                    "admit_time": f"纳入: {p.get('arm','')}  |  氧疗途径: {p.get('o2_route','?')}{flow_s}",
                    "discharge_time": str(p.get("pf_time", ""))[:16] if p.get("pf_time") else "",
                    "admission_source": "",
                    "value": round(p.get('pf_ratio', 0), 1) if isinstance(p.get('pf_ratio'), (int, float)) else p.get('pf_ratio', 0),
                })
            return items

    # ---- ICU-04：从 score 表取 APACHEⅡ 明细 ----
    if code == "ICU-04":
        data = get_icu04_apache_data(dept_codes, start_date, end_date)
        if part == "numerator":
            # 返回首次 APACHEⅡ ≥ 15 的患者
            items = []
            for p in data.get("num_patients", []):
                items.append({
                    "patient_id": p.get("mrn") or p.get("hisPid") or p.get("patientId") or str(p.get("_id", "-"))[-8:],
                    "name": p.get("name", "-"),
                    "gender": "",
                    "age": "",
                    "bed_no": p.get("hisBed", ""),
                    "dept": "",
                    "admit_time": p.get("score_time").strftime("%Y-%m-%d %H:%M") if p.get("score_time") else "-",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": p.get("score", 0),
                })
            return items
        else:
            # 分母：所有在科患者
            items = []
            for p in data.get("den_patients", []):
                items.append({
                    "patient_id": p.get("mrn") or p.get("hisPid") or p.get("patientId") or str(p.get("_id", "-"))[-8:],
                    "name": p.get("name", "-"),
                    "gender": "",
                    "age": "",
                    "bed_no": p.get("hisBed", ""),
                    "dept": "",
                    "admit_time": p.get("icuAdmissionTime").strftime("%Y-%m-%d %H:%M") if p.get("icuAdmissionTime") else "-",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": 1,
                })
            return items

    # ---- ICU-05-1h/3h/6h：Bundle 明细 ----
    if code in ("ICU-05-1h", "ICU-05-3h", "ICU-05-6h"):
        data = get_bundle_data(dept_codes, start_date, end_date)
        hour = code.split("-")[2]  # '1h', '3h', '6h'
        key = f"h{hour[0]}_patients"
        if part == "numerator":
            items = []
            for p in data.get(key, []):
                items.append({
                    "patient_id": p.get("mrn", ""), "name": p.get("name", ""),
                    "gender": "", "age": "", "bed_no": p.get("hisBed", ""), "dept": "",
                    "admit_time": "", "discharge_time": "", "admission_source": "",
                    "value": 1,
                })
            return items
        else:
            items = [{"patient_id": d.get("mrn", ""), "name": d.get("name", ""),
                      "gender": "", "age": "", "bed_no": "", "dept": "",
                      "admit_time": str(d.get("diagnosisTime", ""))[:16] if d.get("diagnosisTime") else "",
                      "discharge_time": "", "admission_source": "", "value": 1}
                     for d in data.get("den_patients", [])]
            return items

    # ---- ICU-06：抗菌药物送检率明细（含治疗/预防判定） ----
    if code == "ICU-06":
        data = get_icu06_data(dept_codes, start_date, end_date)
        if part == "numerator":
            items = []
            for p in data.get("num_patients", []):
                tt = p.get("test_time")
                items.append({
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": p.get("test_name", "")[:60] or p.get("test_source", ""),
                    "dept": "",
                    "admit_time": tt.strftime("%Y-%m-%d %H:%M") if hasattr(tt, 'strftime') else str(tt)[:16] if tt else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": 1,
                })
            return items
        else:
            items = []
            for p in data.get("den_patients", []):
                at = p.get("abx_time")
                purpose = p.get("purpose", "治疗性")
                decided_by = p.get("decided_by", "rule")
                reason = p.get("reason", "")
                confidence = p.get("confidence", 1.0)
                need_review = p.get("need_review", False)
                drug = p.get("abx_drug", "")[:50] or "抗菌药"
                # 抗菌药 + 目的徽章 (仅非 rule 时标注来源)
                if decided_by == "rule":
                    drug_display = f"{drug} [{purpose}]"
                else:
                    drug_display = f"{drug} [{purpose}·{decided_by}]"
                abx_time_str = at.strftime("%m/%d %H:%M") if hasattr(at, 'strftime') else str(at)[:16] if at else ""
                # 低置信度标记: AI 置信度<0.6 或 fallback 或 need_review
                is_low_conf = (
                    need_review
                    or decided_by == "fallback"
                    or (decided_by == "ai" and confidence < 0.6)
                )
                items.append({
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": drug_display,
                    "dept": f"c={confidence:.2f}" if decided_by in ("ai", "fallback") else "",
                    "admit_time": f"⏱{abx_time_str} | {reason[:60]}" if reason else abx_time_str,
                    "discharge_time": "",
                    "admission_source": "low_confidence" if is_low_conf else "",
                    "value": p.get("total_doses", 1),
                })
            return items

    # ---- ICU-09：镇痛评估率明细 ----
    if code == "ICU-09":
        data = get_icu09_data(dept_codes, start_date, end_date)
        if part == "numerator":
            items = []
            for p in data.get("num_patients", []):
                at = p.get("assess_time")
                items.append({
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": p.get("assess_source", ""),
                    "dept": p.get("assess_scale", ""),
                    "admit_time": at.strftime("%Y-%m-%d %H:%M") if hasattr(at, 'strftime') else str(at)[:16] if at else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": p.get("assess_value", ""),
                })
            return items
        else:
            items = []
            for p in data.get("den_patients", []):
                at = p.get("icu_admit")
                items.append({
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": "",
                    "dept": "",
                    "admit_time": at.strftime("%Y-%m-%d %H:%M") if hasattr(at, 'strftime') else str(at)[:16] if at else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": 1,
                })
            return items

    # ---- ICU-10：镇静评估率明细 ----
    if code == "ICU-10":
        data = get_icu10_data(dept_codes, start_date, end_date)
        if part == "numerator":
            items = []
            for p in data.get("num_patients", []):
                at = p.get("assess_time")
                items.append({
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": p.get("assess_source", ""),
                    "dept": p.get("assess_scale", ""),
                    "admit_time": at.strftime("%Y-%m-%d %H:%M") if hasattr(at, 'strftime') else str(at)[:16] if at else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": p.get("assess_value", ""),
                })
            return items
        else:
            items = []
            for p in data.get("den_patients", []):
                at = p.get("icu_admit")
                items.append({
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": "",
                    "dept": "",
                    "admit_time": at.strftime("%Y-%m-%d %H:%M") if hasattr(at, 'strftime') else str(at)[:16] if at else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": 1,
                })
            return items

    # ---- ICU-11：标化病死指数(SMR)明细 ----
    if code == "ICU-11":
        data = get_icu11_data(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        for p in src:
            at = p.get("apache_time")
            dt_out = p.get("icu_discharge")
            cal_dead = p.get("apache_calDead", 0)
            items.append({
                "patient_id": p.get("patient_id", p.get("mrn", "")),
                "name": p.get("name", ""),
                "gender": "", "age": "",
                "bed_no": p.get("dischargedType", ""),
                "dept": p.get("dept_code", ""),
                "admit_time": at.strftime("%Y-%m-%d %H:%M") if hasattr(at, 'strftime') else str(at)[:16] if at else "",
                "discharge_time": dt_out.strftime("%Y-%m-%d %H:%M") if hasattr(dt_out, 'strftime') else str(dt_out)[:16] if dt_out else "",
                "admission_source": "",
                "value": round(cal_dead, 4) if isinstance(cal_dead, (int, float)) else cal_dead,
            })
        return items

    # ---- ICU-12/13：人工气道明细 ----
    if code in ("ICU-12", "ICU-13"):
        data = get_icu12_data(dept_codes, start_date, end_date) if code == "ICU-12" \
            else get_icu13_data(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        for p in src:
            tube_start = p.get("tube_start")
            tube_end = p.get("tube_end")
            reinsert_start = p.get("reinsert_start")
            if code == "ICU-13" and part == "numerator":
                event = f"{p.get('tube_type', '')} → {p.get('reinsert_type', '')}"
                time_desc = (
                    f"拔管 {tube_end.strftime('%Y-%m-%d %H:%M') if hasattr(tube_end, 'strftime') else str(tube_end)[:16]}"
                    f" / 再置管 {reinsert_start.strftime('%Y-%m-%d %H:%M') if hasattr(reinsert_start, 'strftime') else str(reinsert_start)[:16]}"
                )
            else:
                event = p.get("tube_type", "")
                time_desc = tube_end.strftime("%Y-%m-%d %H:%M") if hasattr(tube_end, 'strftime') else str(tube_end)[:16] if tube_end else ""
            items.append({
                "detail_id": p.get("tube_id", ""),
                "patient_id": p.get("patient_id", p.get("mrn", "")),
                "name": p.get("name", ""),
                "gender": "", "age": "",
                "bed_no": event,
                "dept": p.get("dept_code", ""),
                "admit_time": time_desc,
                "discharge_time": tube_start.strftime("%Y-%m-%d %H:%M") if hasattr(tube_start, 'strftime') else str(tube_start)[:16] if tube_start else "",
                "admission_source": "",
                "tube_type": p.get("tube_type", ""),
                "tube_start": tube_start.strftime("%Y-%m-%d %H:%M") if hasattr(tube_start, 'strftime') else str(tube_start)[:16] if tube_start else "",
                "tube_end": tube_end.strftime("%Y-%m-%d %H:%M") if hasattr(tube_end, 'strftime') else str(tube_end)[:16] if tube_end else "",
                "unplanned": p.get("unplanned", False),
                "reinsert_type": p.get("reinsert_type", ""),
                "reinsert_start": reinsert_start.strftime("%Y-%m-%d %H:%M") if hasattr(reinsert_start, 'strftime') else str(reinsert_start)[:16] if reinsert_start else "",
                "value": 1,
            })
        return items

    # ---- ICU-14：非计划转入ICU率明细 ----
    if code == "ICU-14":
        data = get_icu14_data(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        for p in src:
            icu_admit = p.get("icuAdmissionTime")
            basis = (
                "转入类型含“手术”和“转入”；转入计划=“非计划转入”"
                if part == "numerator"
                else "转入类型含“手术”和“转入”"
            )
            items.append({
                "detail_id": p.get("pid", ""),
                "patient_id": p.get("patient_id", p.get("mrn", "")),
                "name": p.get("name", ""),
                "gender": "", "age": "",
                "bed_no": p.get("admissionType", ""),
                "dept": p.get("operation_name", ""),
                "admit_time": icu_admit.strftime("%Y-%m-%d %H:%M") if hasattr(icu_admit, 'strftime') else str(icu_admit)[:16] if icu_admit else "",
                "discharge_time": "",
                "admission_source": p.get("admissionPlan", ""),
                "admissionType": p.get("admissionType", ""),
                "admissionPlan": p.get("admissionPlan", ""),
                "operation_name": p.get("operation_name", ""),
                "icuAdmissionTime": icu_admit.strftime("%Y-%m-%d %H:%M") if hasattr(icu_admit, 'strftime') else str(icu_admit)[:16] if icu_admit else "",
                "basis": basis,
                "value": 1,
            })
        return items

    # ---- ICU-16/17/CAUTI：三管院感明细 ----
    if code == "ICU-15":
        data = get_icu15_data(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        for p in src:
            discharge_time = p.get("icu_discharge")
            re_admit = p.get("re_icu_admit")
            discharge_text = discharge_time.strftime("%Y-%m-%d %H:%M") if hasattr(discharge_time, "strftime") else str(discharge_time)[:16] if discharge_time else ""
            re_admit_text = re_admit.strftime("%Y-%m-%d %H:%M") if hasattr(re_admit, "strftime") else str(re_admit)[:16] if re_admit else "/"
            source_text = "合并历史" if p.get("source") == "patInIcuHistoryList" else "Patient记录"
            readmit_source = "合并历史" if p.get("re_admit_source") == "patInIcuHistoryList" else ("Patient记录" if p.get("re_admit_source") else "")
            basis = (
                f"出科后48小时内重返ICU；依据：{source_text}"
                + (f" + {readmit_source}" if readmit_source else "")
                if re_admit
                else f"同期转出ICU；依据：{source_text}"
            )
            items.append({
                "detail_id": f"{p.get('pid', '')}-{discharge_text}",
                "patient_id": p.get("patient_id", p.get("mrn", "")),
                "name": p.get("name", ""),
                "gender": "", "age": "",
                "bed_no": p.get("dept_code", ""),
                "dept": p.get("re_admit_dept_code", ""),
                "admit_time": discharge_text,
                "discharge_time": re_admit_text,
                "admission_source": source_text,
                "icuDischargeTime": discharge_text,
                "reIcuAdmissionTime": re_admit_text,
                "event_source": source_text,
                "basis": basis,
                "value": 1,
            })
        return items

    if code == "ICU-18":
        data = get_icu18_data(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        for p in src:
            admit_time = p.get("icu_admit")
            assess_time = p.get("first_assess_time")
            admit_text = admit_time.strftime("%Y-%m-%d %H:%M") if hasattr(admit_time, "strftime") else str(admit_time)[:16] if admit_time else ""
            assess_text = assess_time.strftime("%Y-%m-%d %H:%M") if hasattr(assess_time, "strftime") else str(assess_time)[:16] if assess_time else "/"
            assessed_text = "是" if p.get("assessed") else "否"
            items.append({
                "detail_id": p.get("pid", ""),
                "patient_id": p.get("patient_id", p.get("mrn", "")),
                "name": p.get("name", ""),
                "gender": "", "age": "",
                "bed_no": p.get("category", ""),
                "dept": p.get("den_source", ""),
                "admit_time": admit_text,
                "discharge_time": assess_text,
                "admission_source": p.get("assess_source", ""),
                "brain_category": p.get("category", ""),
                "den_source": p.get("den_source", ""),
                "evidence": p.get("evidence", ""),
                "ai_confidence": p.get("ai_confidence", ""),
                "assessed": assessed_text,
                "firstAssessTime": assess_text,
                "assessSource": p.get("assess_source", ""),
                "basis": f"{p.get('den_source', '')}: {p.get('evidence', '')}",
                "value": 1,
            })
        return items

    if code == "ICU-19":
        data = get_icu19_data(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        source_label = {
            "bedside": "护理评估",
            "classification": "营养医嘱",
            "name": "医嘱名称",
            "none": "未启动",
        }
        for p in src:
            admit_time = p.get("icu_admit")
            en_time = p.get("en_start_time")
            discharge_time = p.get("icu_discharge")
            admit_text = admit_time.strftime("%Y-%m-%d %H:%M") if hasattr(admit_time, "strftime") else str(admit_time)[:16] if admit_time else ""
            en_text = en_time.strftime("%Y-%m-%d %H:%M") if hasattr(en_time, "strftime") else str(en_time)[:16] if en_time else "/"
            discharge_text = discharge_time.strftime("%Y-%m-%d %H:%M") if hasattr(discharge_time, "strftime") else str(discharge_time)[:16] if discharge_time else ""
            contraindication = "、".join(p.get("contraindication_hits", [])) if p.get("contraindication_hits") else ""
            source = p.get("source", "none")
            source_text = source_label.get(source, source)
            hit = p.get("hit", "")
            route = p.get("route", "")
            hit_text = hit or route or p.get("drug_name", "")
            if not hit_text:
                hit_text = "未检出"
            window_text = "48h内启动" if p.get("within_48h") else ("超过48h启动" if en_time else "未启动")
            contraindication_text = contraindication or "无"
            basis = (
                f"{window_text}；来源：{source_text}；命中：{hit_text}；"
                f"禁忌证标注：{contraindication_text}"
            )
            items.append({
                "detail_id": p.get("pid", ""),
                "patient_id": p.get("patient_id", p.get("mrn", "")),
                "name": p.get("name", ""),
                "gender": "", "age": "",
                "bed_no": source_text,
                "dept": hit_text,
                "admit_time": admit_text,
                "discharge_time": en_text,
                "admission_source": window_text,
                "icuAdmissionTime": admit_text,
                "icuDischargeTime": discharge_text,
                "enStartTime": en_text,
                "enSource": source_text,
                "enHit": hit_text,
                "enRoute": route,
                "enDrug": p.get("drug_name", ""),
                "contraindication": contraindication,
                "windowResult": window_text,
                "basis": basis,
                "value": 1 if p.get("within_48h") else 0,
            })
        return items

    if code in ("ICU-16", "ICU-17", "CAUTI"):
        getter = {
            "ICU-16": get_icu16_data,
            "ICU-17": get_icu17_data,
            "CAUTI": get_cauti_data,
        }[code]
        data = getter(dept_codes, start_date, end_date)
        src = data.get("num_patients" if part == "numerator" else "den_patients", [])
        items = []
        if part == "numerator":
            for p in src:
                dtm = p.get("diagnosisTime")
                items.append({
                    "detail_id": p.get("diagnosis_id", ""),
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": p.get("diseaseType", ""),
                    "dept": p.get("notes", ""),
                    "admit_time": dtm.strftime("%Y-%m-%d %H:%M") if hasattr(dtm, 'strftime') else str(dtm)[:16] if dtm else "",
                    "discharge_time": "",
                    "admission_source": p.get("lastEditUserId", ""),
                    "diseaseType": p.get("diseaseType", ""),
                    "diagnosisTime": dtm.strftime("%Y-%m-%d %H:%M") if hasattr(dtm, 'strftime') else str(dtm)[:16] if dtm else "",
                    "notes": p.get("notes", ""),
                    "basis": p.get("dedup_basis", ""),
                    "value": 1,
                })
        else:
            grouped = {}
            for p in src:
                group_key = (
                    p.get("pid") or p.get("patient_id") or p.get("mrn", ""),
                    p.get("device_type", ""),
                    "" if code == "ICU-17" else (p.get("tube_type", "") or p.get("device_value", "")),
                )
                g = grouped.setdefault(group_key, {
                    "base": p,
                    "days": set(),
                    "tube_ids": set(),
                    "record_times": [],
                    "starts": [],
                    "ends": [],
                })
                if p.get("device_day"):
                    g["days"].add(p.get("device_day"))
                if p.get("tube_id"):
                    g["tube_ids"].add(p.get("tube_id"))
                for field, target in (("record_time", "record_times"), ("tube_start", "starts"), ("tube_end", "ends")):
                    if p.get(field):
                        g[target].append(p.get(field))

            for _, g in grouped.items():
                p = g["base"]
                day_count = len(g["days"])
                point_count = len(g["tube_ids"]) if g["tube_ids"] else len(g["record_times"])
                point_label = "记录点数" if code == "ICU-16" else "置管点数"
                if code == "ICU-17":
                    point_label = "中心导管数"
                first_day = min(g["days"]) if g["days"] else ""
                last_day = max(g["days"]) if g["days"] else ""
                start_time = min(g["starts"]) if g["starts"] else None
                end_time = max(g["ends"]) if g["ends"] else None
                day_range = f"{first_day} ~ {last_day}" if first_day and last_day and first_day != last_day else first_day
                tube_type = p.get("tube_type", "") or p.get("device_value", "")
                if code == "ICU-17" and p.get("tube_types"):
                    tube_type = "、".join(p.get("tube_types", []))
                excluded = p.get("excluded_evidence", []) or []
                excluded_text = ""
                if excluded:
                    excluded_text = "；剔除：" + "、".join(
                        f"{e.get('tube_type', '')}({e.get('exclude_reason', '')})"
                        for e in excluded[:5]
                    )
                admission_source = f"{day_count}天，{point_count}个{point_label}{excluded_text}"
                basis_text = f"{p.get('dedup_basis') or '按病人+管道/设备合并'}；累计{day_count}天，{point_label}{point_count}{excluded_text}"
                if code == "ICU-17":
                    admission_source = f"{day_count}个中心导管日，涉及{point_count}根中心导管{excluded_text}"
                    basis_text = f"{p.get('dedup_basis') or '患者-中心导管日去重'}；累计{day_count}个中心导管日，涉及{point_count}根中心导管{excluded_text}"
                items.append({
                    "detail_id": f"{p.get('pid', '')}-{p.get('device_type', '')}-{tube_type}",
                    "patient_id": p.get("patient_id", p.get("mrn", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": p.get("device_type", ""),
                    "dept": tube_type,
                    "admit_time": str(day_count),
                    "discharge_time": "",
                    "admission_source": admission_source,
                    "device_type": p.get("device_type", ""),
                    "device_value": p.get("device_value", ""),
                    "tube_type": tube_type,
                    "device_day": day_range,
                    "device_days": day_count,
                    "tube_points": point_count,
                    "record_time": "",
                    "tube_start": start_time.strftime("%Y-%m-%d %H:%M") if hasattr(start_time, 'strftime') else str(start_time)[:16] if start_time else "",
                    "tube_end": end_time.strftime("%Y-%m-%d %H:%M") if hasattr(end_time, 'strftime') else str(end_time)[:16] if end_time else "",
                    "basis": basis_text,
                    "value": day_count,
                })
        return items

    # ---- ICU-07：DVT预防率明细 ----
    if code == "ICU-07":
        data = get_dvt_prevention_patients(dept_codes, start_date, end_date)
        if part == "numerator":
            items = []
            for p in data.get("drug_patients", []):
                orders = p.get("matched_orders", [])
                items.append({
                    "patient_id": p.get("patient_id", p.get("pid", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": "药物预防",
                    "dept": "",
                    "admit_time": orders[0][:60] if orders else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": p.get("order_count", 0),
                })
            for p in data.get("mech_patients", []):
                orders = p.get("matched_orders", [])
                items.append({
                    "patient_id": p.get("patient_id", p.get("pid", "")),
                    "name": p.get("name", ""),
                    "gender": "", "age": "",
                    "bed_no": "机械预防",
                    "dept": "",
                    "admit_time": orders[0][:60] if orders else "",
                    "discharge_time": "",
                    "admission_source": "",
                    "value": p.get("order_count", 0),
                })
            return items
        else:
            data2 = get_icu04_apache_data(dept_codes, start_date, end_date)
            items = [{"patient_id": p.get("patientId", str(p.get("_id", ""))[-8:]), "name": p.get("name", ""),
                      "gender": "", "age": "", "bed_no": p.get("hisBed", ""), "dept": "",
                      "admit_time": p.get("icuAdmissionTime").strftime("%Y-%m-%d %H:%M") if p.get("icuAdmissionTime") else "-",
                      "discharge_time": "", "admission_source": "", "value": 1}
                     for p in data2.get("den_patients", [])]
            return items

    # ---- ICU-02/03：从 account 表取真实医护人员明细 ----
    if code in ("ICU-02", "ICU-03"):
        from db import DOCTOR_PROFESSIONS, NURSE_PROFESSIONS
        professions = DOCTOR_PROFESSIONS if code == "ICU-02" else NURSE_PROFESSIONS
        staff = []
        if part == "numerator":
            for db_name in BED_DB_NAMES:
                try:
                    db = get_client()[db_name]
                    docs = list(db.account.find(
                        {
                            "valid": "valid",
                            "departmentCode": {"$regex": "|".join(dept_codes)},
                            "profession": {"$in": list(professions)},
                        },
                        {
                            "username": 1, "trueName": 1, "profession": 1,
                            "sex": 1, "educationLevel": 1, "entryTime": 1,
                            "departmentCode": 1, "_id": 0,
                        },
                    ))
                    if docs:
                        for d in docs:
                            staff.append({
                                "patient_id": d.get("username", "-"),
                                "name": d.get("trueName") or d.get("username", "-"),
                                "gender": d.get("sex", ""),
                                "age": "",
                                "bed_no": PROFESSION_CN.get(d.get("profession", ""), d.get("profession", "")),
                                "dept": d.get("departmentCode", ""),
                                "admit_time": d.get("entryTime").strftime("%Y-%m-%d") if d.get("entryTime") else "-",
                                "discharge_time": "",
                                "admission_source": d.get("educationLevel", ""),
                                "value": 1,
                            })
                        break
                except Exception:
                    continue
        else:
            # 分母：床位配置
            total_beds = 0
            for db_name in BED_DB_NAMES:
                try:
                    db = get_client()[db_name]
                    total_beds = sum(db.configBed.count_documents({"deptCode": dc}) for dc in dept_codes)
                    if total_beds > 0: break
                except Exception: continue
            staff = [{
                "patient_id": "—",
                "name": f"开放床位数 {total_beds} 张",
                "gender": "", "age": "",
                "bed_no": f"{total_beds} 张", "dept": "",
                "admit_time": "", "discharge_time": "", "admission_source": "",
                "value": total_beds,
            }]
        return staff

    # ---- 分子 / 其他指标：患者明细 ----
    patients = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client()[db_name]
            query = {
                "deptCode": {"$in": dept_codes},
                "status": {"$ne": "invalid"},
                "icuAdmissionTime": {"$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)},
                "$or": [
                    {"icuDischargeTime": {"$gte": start_dt}},
                    {"icuDischargeTime": None},
                    {"icuDischargeTime": {"$exists": False}},
                ],
            }
            docs = list(db.patient.find(
                query,
                {
                    "mrn": 1, "hisPid": 1, "name": 1, "hisBed": 1, "gender": 1, "birthday": 1,
                    "icuAdmissionTime": 1, "icuDischargeTime": 1,
                    "admissionSource": 1, "dept": 1, "status": 1, "_id": 0,
                },
            ).limit(200))
            if docs:
                for d in docs:
                    age = ""
                    if d.get("birthday"):
                        try:
                            bd = d["birthday"]
                            if hasattr(bd, 'year'):
                                age = str(end_dt.year - bd.year)
                        except Exception:
                            pass

                    admit_dt = d.get("icuAdmissionTime")
                    discharge_dt = d.get("icuDischargeTime")
                    mrn = d.get("mrn") or d.get("hisPid") or "-"

                    # ICU-01 分子：计算每位患者的在床天数
                    if code == "ICU-01" and part == "numerator" and admit_dt:
                        first_midnight = dt(admit_dt.year, admit_dt.month, admit_dt.day) + timedelta(days=1)
                        if discharge_dt:
                            last_midnight = dt(discharge_dt.year, discharge_dt.month, discharge_dt.day)
                        else:
                            last_midnight = end_dt
                        first = max(first_midnight, start_dt)
                        last = min(last_midnight, end_dt)
                        bed_days = max(0, (last - first).days + 1) if first <= last else 0
                    else:
                        bed_days = d.get("status", "-")

                    patients.append({
                        "patient_id": mrn,
                        "name": d.get("name") or "-",
                        "gender": d.get("gender", ""),
                        "age": age,
                        "bed_no": d.get("hisBed", "-"),
                        "dept": d.get("dept", ""),
                        "admit_time": (admit_dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if admit_dt else "-",
                        "discharge_time": (discharge_dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if discharge_dt else "在科",
                        "admission_source": d.get("admissionSource", ""),
                        "value": bed_days,
                    })
                break
        except Exception:
            continue

    return patients


# ---- REST 接口 ----

@app.get("/api/indicators")
def get_all_indicators(start: date, end: date, dept: str = "all"):
    """
    返回实时大屏数据。
    values 为所选区间聚合值，trend 为逐月真实指标值，不再使用 mock/random。
    """
    if end < start:
        start, end = end, start

    month_labels = []
    y, m = start.year, start.month
    while (y < end.year) or (y == end.year and m <= end.month):
        month_labels.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1

    end_period = month_labels[-1] if len(month_labels) > 1 else ""
    rows = indicator_list(month_labels[0], dept, end_period, nocache=True)
    values = {r["code"]: r.get("value") for r in rows}
    numerators = {r["code"]: r.get("numerator") for r in rows}
    denominators = {r["code"]: r.get("denominator") for r in rows}
    trend = {}
    for r in rows:
        code = r["code"]
        if r.get("months") and r.get("monthly"):
            trend[code] = r["monthly"]
            continue
        trend[code] = []
        for mon in month_labels:
            live = indicator_list(mon, dept, nocache=True)
            item = next((x for x in live if x.get("code") == code), None)
            trend[code].append(item.get("value") if item else None)

    return {
        "values": values,
        "numerators": numerators,
        "denominators": denominators,
        "trend": trend,
        "months": [f"{int(mon.split('-')[1])}月" for mon in month_labels],
        "periods": month_labels,
        "rows": rows,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

@app.post("/api/ai/analyze")
def ai_analyze(payload: dict):
    period = payload.get("period", "2026-06")
    indicators_list = payload.get("indicators", [])
    
    values_dict = {}
    if indicators_list:
        for item in indicators_list:
            if isinstance(item, dict) and "code" in item and "value" in item:
                values_dict[item["code"]] = item["value"]
    else:
        values_dict = payload.get("values", get_mock_base_values())
        
    return analyze(period, values_dict)


def _periods_between(start_period: str, end_period: str = "") -> list:
    if not end_period:
        end_period = start_period
    sy, sm = start_period.split("-")
    ey, em = end_period.split("-")
    periods = []
    y, m = int(sy), int(sm)
    while (y < int(ey)) or (y == int(ey) and m <= int(em)):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return periods


def _month_end_day(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 31 if month in [1, 3, 5, 7, 8, 10, 12] else 30


def _aggregate_dashboard_rows(dept_codes: list, periods: list, icu_unit: str) -> tuple[list, dict]:
    summary_rows = summary_module.read_summary(dept_codes, periods)
    rows_by_period = {}
    for row in summary_rows:
        rows_by_period.setdefault(row.get("period"), []).append(row)

    # 本月若尚未预聚合，允许只对本月兜底实时计算；历史月份不实时重算。
    now = datetime.now()
    current_period = f"{now.year}-{now.month:02d}"
    if current_period in periods and not rows_by_period.get(current_period):
        try:
            live_rows = query_summary(current_period, icu_unit)
            rows_by_period[current_period] = [
                {
                    "period": current_period,
                    "indicator": r.get("code"),
                    "numerator": r.get("numerator"),
                    "denominator": r.get("denominator"),
                    "value": r.get("value"),
                }
                for r in live_rows
            ]
        except Exception:
            rows_by_period[current_period] = []

    agg = {}
    for period in periods:
        for row in rows_by_period.get(period, []):
            code = row.get("indicator") or row.get("code")
            if not code:
                continue
            if code not in agg:
                agg[code] = {
                    "code": code,
                    "name": NAME_MAP.get(code, code),
                    "unit": UNIT_MAP.get(code, ""),
                    "numerator": 0,
                    "denominator": 0,
                    "monthly": {},
                }
            num = row.get("numerator")
            den = row.get("denominator")
            agg[code]["numerator"] += num or 0
            agg[code]["denominator"] += den or 0
            agg[code]["monthly"][period] = row.get("value")

    for code in ("ICU-02", "ICU-03"):
        last_rows = rows_by_period.get(periods[-1], []) if periods else []
        for row in last_rows:
            if (row.get("indicator") or row.get("code")) == code and code in agg:
                agg[code]["numerator"] = row.get("numerator")
                agg[code]["denominator"] = row.get("denominator")

    result = []
    for code in UNIT_MAP:
        item = agg.get(code)
        if not item:
            result.append({
                "code": code,
                "name": NAME_MAP.get(code, code),
                "unit": UNIT_MAP.get(code, ""),
                "numerator": None,
                "denominator": None,
                "value": None,
                "status": "unknown",
                "monthly": [None for _ in periods],
            })
            continue
        num, den = item.get("numerator"), item.get("denominator")
        value = None if num is None or den in (None, 0) else _calc_value(code, num, den)
        item["value"] = value
        item["status"] = "unknown" if value is None else eval_status(code, value)
        item["monthly"] = [item["monthly"].get(p) for p in periods]
        result.append(item)
    return result, rows_by_period


def _dashboard_risk_hint(code: str, status: str) -> str:
    if status == "unknown":
        return "当前范围暂无预聚合结果，建议先刷新该时间段。"
    hints = {
        "ICU-06": "建议核查治疗性抗菌药判定、用药前送检流程和低置信度 AI 判定。",
        "ICU-16": "建议核查有创通气维护、VAP 诊断确认和呼吸机日分母明细。",
        "ICU-17": "建议核查中心导管置管维护、导管日去重和 CRBSI 诊断确认。",
        "CAUTI": "建议核查导尿管留置必要性、导尿管日去重和 CAUTI 诊断确认。",
        "ICU-11": "建议核查 APACHE 评分完整性、死亡/转归数据和预计死亡率口径。",
        "ICU-19": "建议核查入科 48h 内 EN 启动记录、禁忌证留痕和营养医嘱匹配。",
    }
    return hints.get(code, "建议质控团队核查该指标分子、分母明细及相关流程依从性。")


def _dashboard_trend_delta(values: list) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None
    return round(nums[-1] - nums[0], 2)


def _format_tri_warning_basis(warn_type: str, evidence: list, confidence=None) -> str:
    type_text = warn_type or "三管感染"
    evidence_names = []
    for ev in evidence or []:
        name = ev.get("type") if isinstance(ev, dict) else ""
        if name:
            evidence_names.append(str(name))
    evidence_names = list(dict.fromkeys(evidence_names))
    if evidence_names:
        basis = f"满足疑似{type_text}线索：{'、'.join(evidence_names)}。"
    else:
        basis = f"系统发现疑似{type_text}线索。"
    if confidence is not None:
        try:
            basis += f" 置信度 {float(confidence):.2f}。"
        except Exception:
            pass
    return basis + "需医生确认后才可能进入正式指标。"


@app.get("/api/dashboard/command-center")
def dashboard_command_center(period: str, end_period: str = "", icu_unit: str = "all"):
    """
    实时大屏指挥舱聚合接口：只做轻量编排，不改各指标业务口径。
    历史数据优先读月度预聚合；本月缺失时允许实时兜底。
    """
    periods = _periods_between(period, end_period)
    dept_codes = _resolve_dept_codes(icu_unit)
    rows, _ = _aggregate_dashboard_rows(dept_codes, periods, icu_unit)
    values = {r["code"]: r.get("value") for r in rows}
    trend = {r["code"]: r.get("monthly", []) for r in rows}
    months = [f"{int(p.split('-')[1])}月" for p in periods]

    risk_rank = {"danger": 0, "warn": 1, "unknown": 2, "good": 3}
    abnormal = []
    for row in rows:
        if row.get("status") in ("danger", "warn", "unknown"):
            item = dict(row)
            item["delta"] = _dashboard_trend_delta(row.get("monthly", []))
            item["hint"] = _dashboard_risk_hint(row["code"], row.get("status"))
            abnormal.append(item)
    abnormal.sort(key=lambda x: (risk_rank.get(x.get("status"), 9), x.get("code", "")))

    risk_counts = {
        "danger": sum(1 for r in rows if r.get("status") == "danger"),
        "warn": sum(1 for r in rows if r.get("status") == "warn"),
        "unknown": sum(1 for r in rows if r.get("status") == "unknown"),
        "good": sum(1 for r in rows if r.get("status") == "good"),
    }
    needs_attention = risk_counts["danger"] + risk_counts["warn"]
    overall_status = "danger" if risk_counts["danger"] else ("warn" if risk_counts["warn"] else "good")

    try:
        ai = analyze(f"{period}~{end_period or period}", values)
    except Exception:
        ai = {"summary": "AI 分析暂不可用，请先查看异常指标与待办线索。", "abnormal": [], "hints": []}

    tri_summary = {"count": 0, "types": {}, "items": [], "notice": ""}
    try:
        sy, sm = [int(x) for x in periods[0].split("-")]
        ey, em = [int(x) for x in periods[-1].split("-")]
        start_date = f"{sy}-{sm:02d}-01"
        end_date = f"{ey}-{em:02d}-{_month_end_day(ey, em):02d}"
        tri_items = get_tri_tube_suspected_warnings(dept_codes, start_date, end_date, min_hours=48)
        type_counts = {}
        for item in tri_items:
            key = item.get("suspect_type") or item.get("type") or item.get("infection_type") or "疑似感染"
            type_counts[key] = type_counts.get(key, 0) + 1
        preview_items = []
        for item in tri_items[:8]:
            warn_type = item.get("suspect_type") or item.get("type") or item.get("infection_type") or "疑似感染"
            evidence = item.get("evidence") or []
            confidence = item.get("confidence")
            preview_items.append({
                "patient_id": item.get("patient_id") or item.get("mrn") or item.get("hisPid") or item.get("pid", ""),
                "name": item.get("name", ""),
                "type": warn_type,
                "time": item.get("diagnosis_time") or item.get("time") or item.get("event_time") or "",
                "basis": item.get("basis") or item.get("reason") or _format_tri_warning_basis(warn_type, evidence, confidence),
                "confidence": confidence,
                "evidence": evidence,
                "rule": "至少同时满足：相关装置留置超过 48 小时，并出现感染相关证据；未人工确认前不计入正式感染分子。",
            })
        tri_summary = {
            "count": len(tri_items),
            "types": type_counts,
            "items": preview_items,
            "notice": "AI 疑似预警仅作医生确认线索，未确认前不计入正式指标分子。",
        }
    except Exception as e:
        tri_summary = {"count": 0, "types": {}, "items": [], "notice": f"三管预警读取失败：{str(e)[:80]}"}

    low_confidence = {"count": 0, "items": []}
    try:
        decisions = get_all_ai_decisions(
            period_start=period,
            period_end=end_period or period,
            min_confidence=0.6,
            limit=20,
        )
        low_confidence = {"count": len(decisions), "items": decisions[:8]}
    except Exception:
        low_confidence = {"count": 0, "items": []}

    ai_todos = []
    if tri_summary["count"]:
        ai_todos.append({
            "type": "tri_tube_warning",
            "title": "三管疑似感染待确认",
            "count": tri_summary["count"],
            "description": "建议感染质控人员核查疑似 VAP/CRBSI/CAUTI 线索。",
        })
    if low_confidence["count"]:
        ai_todos.append({
            "type": "low_confidence_abx",
            "title": "抗菌药 AI 判定待复核",
            "count": low_confidence["count"],
            "description": "建议复核 ICU-06 分母中低置信度治疗/预防用药判定。",
        })

    return {
        "period": period,
        "end_period": end_period or period,
        "icu_unit": icu_unit,
        "months": months,
        "periods": periods,
        "rows": rows,
        "values": values,
        "trend": trend,
        "risk": {
            "overall_status": overall_status,
            "counts": risk_counts,
            "abnormal_count": risk_counts["danger"],
            "warning_count": risk_counts["warn"],
            "attention_count": needs_attention,
            "unknown_count": risk_counts["unknown"],
            "headline": f"{risk_counts['danger']}项严重异常，{risk_counts['warn']}项预警，合计{needs_attention}项需关注",
            "explain": "严重异常=超过异常阈值的指标；预警=未达最佳但仍在预警范围的指标；AI异常列表中的数量为严重异常+预警合计。",
        },
        "abnormal": abnormal,
        "ai": {
            "summary": ai.get("summary", ""),
            "abnormal": ai.get("abnormal", []),
            "hints": ai.get("hints", []),
            "todos": ai_todos,
            "tri_tube": tri_summary,
            "low_confidence": low_confidence,
            "explain": "AI待办=三管疑似线索数+低置信度抗菌药判定数；三管疑似是待确认线索，不等同于已确诊感染例数。",
        },
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

@app.get("/api/indicators/list")
def indicator_list(period: str, icu_unit: str = "all", end_period: str = "", nocache: bool = False):
    """
    第一级：指标汇总列表。
    period=2026-06 单月, period=2026-01&end_period=2026-06 跨月汇总。
    nocache=true 强制刷新，绕过服务器缓存。
    """
    ck = _cache_key("list", period, icu_unit, end_period)
    cached = _cache_get(ck, nocache=nocache)
    if cached is not None:
        return cached
    if end_period:
        # 跨月汇总：逐月累加分子/分母，记录每月比值
        start_y, start_m = period.split("-")
        end_y, end_m = end_period.split("-")
        month_labels = []
        y, m = int(start_y), int(start_m)
        while (y < int(end_y)) or (y == int(end_y) and m <= int(end_m)):
            month_labels.append(f"{y}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1

        summary_rows = summary_module.read_summary(_resolve_dept_codes(icu_unit), month_labels)
        if summary_rows:
            rows_by_month = {}
            for r in summary_rows:
                rows_by_month.setdefault(r["period"], []).append(r)
        else:
            rows_by_month = {}

        agg = {}       # code → {num, den, unit, name, monthly: {mon: val}}
        for mon in month_labels:
            rows = rows_by_month.get(mon) or []
            if rows_by_month.get(mon):
                rows = [_summary_row_to_api(r) for r in rows]
            for r in rows:
                code = r.get("indicator") or r.get("code")
                if code not in agg:
                    agg[code] = {"num": 0, "den": 0, "unit": UNIT_MAP.get(code, ""),
                                 "name": NAME_MAP.get(code, code), "monthly": {}}
                agg[code]["num"] += r.get("numerator", 0)
                agg[code]["den"] += r.get("denominator", 0)
                agg[code]["monthly"][mon] = r.get("value", 0)

        # ICU-02/03 是时点值(人数/床位数),跨月不累加,取最后一个月
        for code in ("ICU-02", "ICU-03"):
            if code in agg and len(month_labels) > 1:
                last = rows_by_month.get(month_labels[-1]) or []
                for r in last:
                    if (r.get("indicator") or r.get("code")) == code:
                        agg[code]["num"] = r.get("numerator", 0)
                        agg[code]["den"] = r.get("denominator", 0)

        result = []
        for code in UNIT_MAP:
            if code not in agg:
                agg[code] = {
                    "num": None,
                    "den": None,
                    "unit": UNIT_MAP.get(code, ""),
                    "name": NAME_MAP.get(code, code),
                    "monthly": {},
                }
        for code, v in agg.items():
            if v["num"] is None or v["den"] is None:
                val = None
            elif code == "ICU-11":
                val = round(v["num"] / v["den"], 2) if v["den"] > 0 else 0
            elif v["unit"] == "‰":
                val = round(v["num"] / v["den"] * 1000, 1) if v["den"] > 0 else 0
            elif v["unit"] == ":1":
                val = round(v["num"] / v["den"], 1) if v["den"] > 0 else 0
            else:
                val = round(v["num"] / v["den"] * 100, 1) if v["den"] > 0 else 0
            result.append({
                "code": code,
                "name": v["name"],
                "numerator": v["num"],
                "denominator": v["den"],
                "value": val,
                "unit": v["unit"],
                "status": "unknown" if val is None else eval_status(code, val),
                "months": month_labels,
                "monthly": [v["monthly"].get(mon) for mon in month_labels],
            })
        result = sorted(result, key=lambda x: x["code"])
        result = _ensure_no_data_indicator_rows(result)
        _cache_set(ck, result)
        return result

    # 单月查询
    rows = summary_module.read_summary(_resolve_dept_codes(icu_unit), [period])
    if rows:
        result = [_summary_row_to_api(r) for r in rows]
    else:
        result = []
    existing_codes = {r.get("code") for r in result}
    for code in UNIT_MAP:
        if code not in existing_codes:
            result.append(_empty_indicator_row(code))
    result = _ensure_no_data_indicator_rows(result)
    _cache_set(ck, result)
    return result

@app.get("/api/indicators/{code}/trend")
def indicator_trend(code: str, year: int, icu_unit: str = "all",
                    start_month: int = 1, end_month: int = 12):
    """第二级：某指标趋势，支持指定月份范围"""
    rows = query_trend(code, year, icu_unit)
    months = [f"{m}月" for m in range(start_month, end_month + 1)]
    values = [rows.get(m) for m in range(start_month, end_month + 1)]
    return {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "months": months,
        "values": values,
    }

@app.get("/api/indicators/{code}/detail")
def indicator_detail(code: str, period: str, part: str, icu_unit: str = "all", end_period: str = "",
                     nocache: bool = False, limit: int = 200, offset: int = 0):
    """
    第三级：分子/分母下钻明细。
    支持 end_period 跨月聚合。
    nocache=true 强制刷新。
    """
    limit = max(1, min(int(limit or 200), 1000))
    offset = max(0, int(offset or 0))
    ck = _cache_key("detail", code, period, part, icu_unit, end_period)
    cached = _cache_get(ck, nocache=nocache)
    if cached is not None:
        result = dict(cached)
        all_items = result.get("all_patients") or result.get("patients", [])
        result["count"] = len(all_items)
        result["limit"] = limit
        result["offset"] = offset
        result["has_more"] = offset + limit < len(all_items)
        result["patients"] = all_items[offset:offset + limit]
        result.pop("all_patients", None)
        return result
    # 跨月汇总
    if end_period:
        start_y, start_m = period.split("-")
        end_y, end_m = end_period.split("-")
        months = []
        y, m = int(start_y), int(start_m)
        while (y < int(end_y)) or (y == int(end_y) and m <= int(end_m)):
            months.append(f"{y}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1
        # 聚合：患者类指标按 patient_id 去重；例次类指标优先按 detail_id 去重。
        merged = {}
        for mon in months:
            for p in _detail_cache_payload(code, mon, part, icu_unit, nocache=nocache):
                pid = p.get("detail_id") or p.get("patient_id", "")
                if pid == "—" or (code == "ICU-01" and part == "numerator"):
                    # 累加数值
                    if pid in merged:
                        merged[pid]["value"] = (merged[pid].get("value", 0) or 0) + (p.get("value", 0) or 0)
                    else:
                        merged[pid] = dict(p)
                else:
                    merged[pid] = dict(p)
        items = list(merged.values())

        # 跨月分母：重算总天数和名称
        if code == "ICU-01" and part == "denominator":
            total_days = sum(
                31 if int(m.split("-")[1]) in [1,3,5,7,8,10,12]
                else (30 if int(m.split("-")[1]) != 2 else 28)
                for m in months
            )
            # 取床位数
            dcodes = _resolve_dept_codes(icu_unit)
            total_beds_count = 0
            for db_name in BED_DB_NAMES:
                try:
                    db = get_client()[db_name]
                    total_beds_count = sum(db.configBed.count_documents({"deptCode": dc}) for dc in dcodes)
                    if total_beds_count > 0: break
                except Exception: continue
            if total_beds_count == 0: total_beds_count = 18
            for p in items:
                if p.get("patient_id") == "—":
                    p["name"] = f"开放床位数 {total_beds_count} 张 × 统计 {total_days} 天 = {total_beds_count * total_days} 总床日"
                    p["value"] = total_beds_count * total_days
                    p["bed_no"] = f"{total_beds_count} 张"
                    p["admit_time"] = f"统计 {total_days} 天"
    else:
        items = _detail_cache_payload(code, period, part, icu_unit, nocache=nocache)

    # 各指标明细描述
    if code == "ICU-01":
        source_desc = "实际占用总床日数 — 每位患者在统计期内的在床天数" if part == "numerator" \
            else "实际开放总床日数 — 各科室床位配置（每床每日计1床日）"
    elif code == "ICU-02":
        source_desc = "分子：来自 account 表，筛选 valid 医师（主任医师/副主任医师/主治医师/医师/规培/进修/实习）" if part == "numerator" \
            else "分母：来自 configBed 表，统计科室实际开放床位数"
    elif code == "ICU-03":
        source_desc = "分子：来自 account 表，筛选 valid 护士（护士长/护理组长/护士/规培/进修/实习护士）" if part == "numerator" \
            else "分母：来自 configBed 表，统计科室实际开放床位数"
    elif code == "ICU-04":
        source_desc = "分子：来自 score 表，当月首次 APACHEⅡ 评分 total ≥ 15 的患者" if part == "numerator" \
            else "分母：来自 patient 表，统计期内在科患者（排除 invalid）"
    elif code in ("ICU-05-1h", "ICU-05-3h", "ICU-05-6h"):
        h = code.split("-")[2]
        source_desc = f"分子：来自 infectionShockV2 表，{h} bundle 达标（baStandard或finish）的患者" if part == "numerator" \
            else "分母：来自 diseaseDiagnosis 表，脓毒性休克诊断 + patient 表在科过滤"
    elif code == "ICU-06":
        source_desc = (f"分子：来自 VI_ICU_ZYYZ 培养类检验医嘱，首次抗生素前有病原学送检的患者（送检≤首剂时间）" if part == "numerator"
            else f"分母：来自 drugExe 抗菌药执行记录，经三层判定（A感染信号→B围术期→C短疗程→AI灰区）确认治疗目的，已剔除预防性用药")
    elif code == "ICU-07":
        source_desc = "分子：来自 DataCenter.VI_ICU_ZYYZ，抗凝药或机械预防医嘱包含匹配（排除封管/有创压肝素）" if part == "numerator" \
            else "分母：来自 patient 表，统计期内在科患者（排除 invalid）"
    elif code == "ICU-09":
        source_desc = "分子：床旁评估记录或量表评分记录中完成镇痛评分（NRS/CPOT/BPS等）的患者，明细展示评分中文名、分值和时间" if part == "numerator" \
            else "分母：同期入住ICU的患者总人数"
    elif code == "ICU-10":
        source_desc = "分子：床旁评估记录或量表评分记录中完成镇静评分（RASS等）的患者，明细展示评分中文名、分值和时间" if part == "numerator" \
            else "分母：同期入住ICU的患者总人数"
    elif code == "ICU-11":
        source_desc = "分子：已结案完整病例中在院死亡或非医嘱离院的患者数" if part == "numerator" \
            else "分母：死亡、出院、非医嘱离院且有入科24小时内首次APACHEⅡ评分病例的预计死亡率之和"
    elif code == "ICU-12":
        source_desc = "分子：气管插管/气插管/气切套管拔管记录中 unPlannedEndTube 为 true 的非计划拔管，已排除换管" if part == "numerator" \
            else "分母：统计期内气管插管/气插管/气切套管拔管记录，已排除 replace=true 换管"
    elif code == "ICU-13":
        source_desc = "分子：拔管后48小时内同患者再次气管插管/气插管/气切套管，气管插管转气切套管计入，replace=true 换管不计" if part == "numerator" \
            else "分母：统计期内气管插管/气插管/气切套管拔管记录，已排除 replace=true 换管"
    elif code == "ICU-19":
        source_desc = (
            "分子：入住ICU超过48小时患者中，入科48小时内启动肠内营养(EN)者；优先取护理评估，其次营养医嘱和医嘱名称兜底"
            if part == "numerator"
            else "分母：同期入住ICU时间超过48小时的患者；EN禁忌证仅标注留痕，不自动剔除"
        )
    else:
        desc_info = SOURCE_DESC.get(code, {"numerator": "分子明细", "denominator": "分母明细"})
        source_desc = desc_info.get(part, "明细")

    result = {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "part": part,
        "count": len(items),
        "source_desc": source_desc,
        "all_patients": items,
    }
    _cache_set(ck, result)
    paged = dict(result)
    paged["limit"] = limit
    paged["offset"] = offset
    paged["has_more"] = offset + limit < len(items)
    paged["patients"] = items[offset:offset + limit]
    paged.pop("all_patients", None)
    return paged


class TriTubeConfirmPayload(BaseModel):
    pid: str
    suspect_type: str
    diagnosis_time: str = ""
    user_id: str
    notes: str = ""


@app.get("/api/tri-tube/warnings")
def tri_tube_warnings(period: str, icu_unit: str = "all", min_hours: int = 48, nocache: bool = False):
    """
    AI疑似三管感染预警，仅作医生确认线索，不计入正式指标分子。
    """
    ck = _cache_key("tri_tube_warnings", period, icu_unit, min_hours)
    cached = _cache_get(ck, nocache)
    if cached is not None:
        return cached

    year, month = period.split("-")
    start_date = f"{year}-{month}-01"
    end_day = 31 if int(month) in [1,3,5,7,8,10,12] else (30 if int(month) != 2 else 28)
    end_date = f"{year}-{month}-{end_day:02d}"
    dept_codes = _resolve_dept_codes(icu_unit)
    items = get_tri_tube_suspected_warnings(dept_codes, start_date, end_date, min_hours=min_hours)
    result = {
        "count": len(items),
        "notice": "AI疑似预警，需医生确认；未确认前不计入ICU-16/ICU-17/CAUTI分子",
        "items": items,
    }
    _cache_set(ck, result)
    return result


@app.post("/api/tri-tube/warnings/confirm")
def tri_tube_warning_confirm(payload: TriTubeConfirmPayload):
    """
    医生确认疑似预警后，写入正式感染诊断记录。
    """
    if not payload.user_id:
        return {"ok": False, "error": "user_id required"}
    diagnosis_time = datetime.fromisoformat(payload.diagnosis_time) if payload.diagnosis_time else datetime.now()
    try:
        doc = confirm_tri_tube_warning(
            pid=payload.pid,
            suspect_type=payload.suspect_type,
            diagnosis_time=diagnosis_time,
            user_id=payload.user_id,
            notes=payload.notes,
        )
        return {"ok": True, "diagnosis": doc}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/departments")
def get_departments():
    """
    从 MongoDB department 表读取所有科室列表。
    用于前端下拉菜单和 URL deptCode 参数解析。
    """
    departments = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client()[db_name]
            docs = list(db.department.find({}, {
                "code": 1, "name": 1, "shortName": 1, "hospitalName": 1, "_id": 0
            }))
            if docs:
                departments = docs
                break
        except Exception:
            continue

    # 如果 MongoDB 无数据，回退到静态映射
    if not departments:
        departments = [
            {"code": k, "name": v, "shortName": v}
            for k, v in DEPT_MAP.items()
        ]

    return departments


# ---- 预聚合汇总表接口 ----

@app.get("/api/summary/list")
def summary_list(dept: str = "all", start_period: str = "", end_period: str = ""):
    """
    从 icu_monthly_summary 汇总表读取指标数据（毫秒级）。
    """
    dept_codes = _resolve_dept_codes(dept)
    periods = []
    if start_period and end_period:
        sy, sm = start_period.split("-")
        ey, em = end_period.split("-")
        y, m = int(sy), int(sm)
        while (y < int(ey)) or (y == int(ey) and m <= int(em)):
            periods.append(f"{y}-{m:02d}")
            m += 1
            if m > 12: m, y = 1, y + 1
    elif start_period:
        periods = [start_period]
    else:
        periods = [f"{datetime.now().year}-{datetime.now().month:02d}"]

    rows = summary_module.read_summary(dept_codes, periods)
    return rows


@app.post("/api/admin/rebuild-summary")
def admin_rebuild(dept: str = "all", start_period: str = "", end_period: str = "",
                  indicators: str = ""):
    """
    手动触发预聚合。可指定范围。
    POST /api/admin/rebuild-summary?dept=all&start_period=2024-01&end_period=2025-12
    """
    dept_codes = _resolve_dept_codes(dept)
    periods = []
    if start_period and end_period:
        sy, sm = start_period.split("-")
        ey, em = end_period.split("-")
        y, m = int(sy), int(sm)
        while (y < int(ey)) or (y == int(ey) and m <= int(em)):
            periods.append(f"{y}-{m:02d}")
            m += 1
            if m > 12: m, y = 1, y + 1
    else:
        # 默认最近 13 个月
        now = datetime.now()
        for i in range(13):
            d = now - timedelta(days=30 * i)
            periods.append(f"{d.year}-{d.month:02d}")
        periods = list(set(periods))
        periods.sort()

    ind_list = [i.strip() for i in indicators.split(",") if i.strip()] if indicators else None
    if ind_list:
        ind_list = [i for i in ind_list if i in summary_module.INDICATOR_COMPUTERS]

    stats = summary_module.rebuild_summary(dept_codes, periods, ind_list)
    stats["dept_codes"] = dept_codes
    stats["periods"] = periods
    return stats


@app.get("/api/admin/rebuild-status")
def admin_rebuild_status():
    """查看最近一次预聚合状态"""
    for db_name in BED_DB_NAMES:
        try:
            db = get_client()[db_name]
            coll = db["icu_monthly_summary"]
            total = coll.count_documents({})
            latest = list(coll.find({}, {"period": 1, "updated_at": 1, "_id": 0}).sort("updated_at", -1).limit(1))
            periods = coll.distinct("period")
            depts = coll.distinct("dept_code")
            indicators = coll.distinct("indicator")
            return {
                "total_docs": total,
                "periods": sorted(periods),
                "depts": depts,
                "indicators": sorted(indicators),
                "latest_update": latest[0] if latest else None,
            }
        except Exception: continue
    return {"error": "Database not available"}


# ---- 手动刷新端点（异步） ----

_refresh_tasks = {}       # task_id → {status, dept_codes, period, stats?, error?}
_refresh_lock = threading.Lock()
_REFRESH_TASK_TTL = 3600  # 任务状态保留 1 小时，整年刷新完成后仍可查看结果


@app.post("/api/refresh")
def trigger_refresh(dept_code: str = "all", year: int = None, month: int = None,
                    start_period: str = "", end_period: str = "",
                    indicators: str = ""):
    """
    手动触发当前科室+当前月份的预聚合重建（异步）。

    POST /api/refresh?dept_code=JJL000282&year=2026&month=6

    内部使用 _resolve_dept_codes 解析（与 indicator_list 同源），
    保证 summary 写入的 dept_code key 与前端查询完全一致。

    返回 task_id，前端轮询 GET /api/refresh/{task_id} 获取状态。
    """
    # 参数校验与默认值
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    dept_codes = _resolve_dept_codes(dept_code)
    if not start_period:
        start_period = f"{year}-{month:02d}"
    if not end_period:
        end_period = start_period

    sy, sm = start_period.split("-")
    ey, em = end_period.split("-")
    periods = []
    y, m = int(sy), int(sm)
    while (y < int(ey)) or (y == int(ey) and m <= int(em)):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1

    indicator_list = [i.strip() for i in indicators.split(",") if i.strip()] if indicators else None
    if indicator_list:
        indicator_list = [i for i in indicator_list if i in summary_module.INDICATOR_COMPUTERS]
    else:
        indicator_list = list(summary_module.INDICATOR_COMPUTERS.keys())
    historical_periods = [p for p in periods if _is_historical_period(p)]
    summary_total = len(periods) * len(indicator_list)
    detail_total = len(historical_periods) * len(indicator_list) * 2

    task_key = "|".join([
        dept_code,
        ",".join(dept_codes),
        ",".join(periods),
        ",".join(indicator_list),
    ])
    task_id = uuid.uuid4().hex[:12]
    with _refresh_lock:
        for existing_id, existing in _refresh_tasks.items():
            if existing.get("status") == "running" and existing.get("task_key") == task_key:
                return {"task_id": existing_id, **existing, "reused": True}
        _refresh_tasks[task_id] = {
            "status": "running",
            "dept_codes": dept_codes,
            "periods": periods,
            "dept_code_param": dept_code,
            "task_key": task_key,
            "total": summary_total + detail_total,
            "summary_total": summary_total,
            "detail_total": detail_total,
            "done": 0,
            "started": 0,
            "success": 0,
            "failed": 0,
            "phase": "summary",
            "current_period": periods[0] if periods else "",
            "current_indicator": indicator_list[0] if indicator_list else "",
            "started_at": datetime.utcnow().isoformat(),
        }

    def _run_rebuild():
        try:
            progress_base = {"done": 0, "success": 0, "failed": 0}
            def _progress(total, success, failed, current_period="", current_indicator="", event="progress"):
                progress_base["done"] = total
                progress_base["success"] = success
                progress_base["failed"] = failed
                with _refresh_lock:
                    if task_id in _refresh_tasks:
                        payload = {
                            "done": total,
                            "success": success,
                            "failed": failed,
                        }
                        if current_period:
                            payload["current_period"] = current_period
                        if current_indicator:
                            payload["current_indicator"] = current_indicator
                        if event == "started":
                            payload["started"] = min(
                                _refresh_tasks[task_id].get("started", 0) + 1,
                                _refresh_tasks[task_id].get("total", 0),
                            )
                        payload["last_event"] = event
                        payload["updated_at"] = datetime.utcnow().isoformat()
                        _refresh_tasks[task_id].update(payload)

            def _detail_progress(total, success, failed, current_period="", current_indicator="", part="", event="progress"):
                with _refresh_lock:
                    if task_id in _refresh_tasks:
                        done = progress_base["done"] + total
                        payload = {
                            "phase": "detail",
                            "done": done,
                            "success": progress_base["success"] + success,
                            "failed": progress_base["failed"] + failed,
                            "current_period": current_period,
                            "current_indicator": current_indicator,
                            "current_part": part,
                            "last_event": event,
                            "updated_at": datetime.utcnow().isoformat(),
                        }
                        if event == "started":
                            payload["started"] = min(
                                _refresh_tasks[task_id].get("started", 0) + 1,
                                _refresh_tasks[task_id].get("total", 0),
                            )
                        _refresh_tasks[task_id].update(payload)

            stats = summary_module.rebuild_summary(
                dept_codes,
                periods,
                indicator_list,
                progress_callback=_progress,
            )
            detail_stats = rebuild_detail_cache(
                dept_codes,
                periods,
                indicator_list,
                icu_unit=dept_code,
                progress_callback=_detail_progress,
            )
            with _refresh_lock:
                _refresh_tasks[task_id].update({
                    "status": "completed",
                    "phase": "completed",
                    "done": summary_total + detail_stats["total"],
                    "success": stats["success"] + detail_stats["success"],
                    "failed": stats["failed"] + detail_stats["failed"],
                    "stats": {
                        "total": summary_total + detail_stats["total"],
                        "success": stats["success"] + detail_stats["success"],
                        "failed": stats["failed"] + detail_stats["failed"],
                        "summary": stats,
                        "detail": detail_stats,
                    },
                    "completed_at": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            with _refresh_lock:
                _refresh_tasks[task_id].update({
                    "status": "error",
                    "error": str(e)[:500],
                    "completed_at": datetime.utcnow().isoformat(),
                })

    t = threading.Thread(target=_run_rebuild, daemon=True)
    t.start()

    # 清理过期任务（超过 TTL 的已完成/错误任务）
    with _refresh_lock:
        expired = [
            tid for tid, tinfo in _refresh_tasks.items()
            if tinfo["status"] in ("completed", "error")
            and (datetime.utcnow() - datetime.fromisoformat(tinfo.get("completed_at", tinfo["started_at"]))).total_seconds() > _REFRESH_TASK_TTL
        ]
        for tid in expired:
            del _refresh_tasks[tid]

    return {
        "task_id": task_id,
        "status": "running",
        "dept_codes": dept_codes,
        "periods": periods,
        "indicator_count": len(indicator_list),
        "total": summary_total + detail_total,
        "summary_total": summary_total,
        "detail_total": detail_total,
        "started": 0,
    }


@app.get("/api/refresh/{task_id}")
def get_refresh_status(task_id: str):
    """
    查询刷新任务状态。

    GET /api/refresh/abc123def456
    → {task_id, status: "running"|"completed"|"error", stats?, error?}
    """
    with _refresh_lock:
        task = _refresh_tasks.get(task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found"}
    return {"task_id": task_id, **task}


# ============================================================
# ICU-06 AI 决策复核接口
# ============================================================

@app.get("/api/ai-decisions")
def list_ai_decisions(dept: str = "all", period_start: str = "",
                      period_end: str = "", min_confidence: float = None,
                      limit: int = 500):
    """
    查询 AI 判定记录，供主任复核。
    可选筛选：科室、时间范围、置信度阈值。

    GET /api/ai-decisions?period_start=2026-06&min_confidence=0.6
    返回: [{hisPid, task, purpose, confidence, reason, decided_by, created_at}]
    """
    return get_all_ai_decisions(
        dept_codes=None,
        period_start=period_start or None,
        period_end=period_end or None,
        min_confidence=min_confidence,
        limit=limit,
    )


@app.post("/api/ai-decisions/override")
def override_ai(payload: dict):
    """
    人工推翻 AI 判定。

    POST /api/ai-decisions/override
    Body: {
      "hisPid": "ZY0100000001",
      "purpose": "治疗性",
      "reason": "患者有明确肺部感染影像学证据",
      "overridden_by": "张主任"
    }

    写回 ai_decision_cache 表，标记 by='manual_override'，置信度=1.0。
    下次同 hisPid 查询时直接使用人工判定，不再调 AI。
    """
    hispid = payload.get("hisPid", "").strip()
    purpose = payload.get("purpose", "").strip()
    reason = payload.get("reason", "").strip()
    overridden_by = payload.get("overridden_by", "主任").strip()

    if not hispid:
        return {"success": False, "error": "hisPid is required"}
    if purpose not in ("治疗性", "预防性"):
        return {"success": False, "error": "purpose must be 治疗性 or 预防性"}
    if not reason:
        return {"success": False, "error": "reason is required"}

    return override_ai_decision(hispid, purpose, reason, overridden_by)
