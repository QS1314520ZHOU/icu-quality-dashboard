# main.py
from fastapi import FastAPI, BackgroundTasks
from datetime import date, datetime, timedelta
from ai_analyzer import analyze, get_all_ai_decisions, override_ai_decision, ensure_ai_cache_collection as ensure_ai_cache
from db import get_open_bed_count, get_occupied_bed_days, get_staff_count, get_icu04_apache_data, get_bundle_data, get_icu08_data, get_icu06_data, get_dvt_prevention_patients, get_client, BED_DB_NAMES, PROFESSION_CN
import random
import time as time_module
import threading
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
    ensure_ai_cache()
    _start_scheduler()

# 简易缓存（TTL 60秒）
_cache = {}
_CACHE_TTL = 60


def _cache_key(prefix, *args):
    return f"{prefix}:{':'.join(str(a) for a in args)}"


def _cache_get(key):
    entry = _cache.get(key)
    if entry and time_module.time() - entry["ts"] < _CACHE_TTL:
        return entry["val"]
    return None


def _cache_set(key, val):
    _cache[key] = {"val": val, "ts": time_module.time()}

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
}

NAME_MAP = {code: cfg["name"] for code, cfg in INDICATORS_CONFIG.items()}
UNIT_MAP = {code: cfg["unit"] for code, cfg in INDICATORS_CONFIG.items()}

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
    "ICU-17": {"numerator": "新发生导管相关血流感染(CRBSI)的例次数", "denominator": "血管导管留置累计使用总天数"},
    "ICU-18": {"numerator": "进行意识状态评分(GCS/FOUR)测定的急性脑损伤患者数", "denominator": "同期收治的急性脑损伤患者总数"},
    "ICU-19": {"numerator": "入科48小时内启动肠内营养(EN)支持的患者数", "denominator": "同期入住ICU时间超过48小时的患者总数"},
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
    base = get_mock_base_values()

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
        icu01_den = 1560
        icu01_num = 1284
        icu01_value = 82.3

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

    import random as _random
    _random.seed(hash(period + icu_unit))
    def _jitter(v, pct=0.15):
        return max(0, round(v * (1 + _random.uniform(-pct, pct))))

    # ICU-02/03 兜底
    if icu02_num == 0: icu02_num = _jitter(18, 0.1)
    if icu03_num == 0: icu03_num = _jitter(56, 0.1)
    if icu02_den == 0: icu02_den = 20

    # ----- ICU-04 分子分母：从 score 表取真实 APACHEⅡ 数据 -----
    icu04_data = get_icu04_apache_data(dept_codes, start_date, end_date)
    icu04_num = icu04_data["num_count"]
    icu04_den = icu04_data["den_count"]
    if icu04_num == 0 and icu04_den == 0:
        icu04_num = _jitter(87, 0.15)
        icu04_den = 150

    # ----- ICU-06：抗菌药物前病原学送检率（DataCenter.VI_ICU_ZYYZ）-----
    icu06_data = get_icu06_data(dept_codes, start_date, end_date)
    icu06_num = icu06_data["num_count"]
    icu06_den = icu06_data["den_count"]
    if icu06_den == 0:
        icu06_den = icu04_den
        icu06_num = 0  # 无抗生素数据时送检为0, 不用mock

    # ----- ICU-07：DVT预防率（DataCenter.VI_ICU_ZYYZ 医嘱包含匹配）-----
    dvt_data = get_dvt_prevention_patients(dept_codes, start_date, end_date)
    icu07_num = dvt_data.get("all_count", 0)
    icu07_den = icu04_den  # 分母=同期在科患者（同ICU-04）
    if icu07_num == 0:
        icu07_num = _jitter(135, 0.15)

    # ----- ICU-08：ARDS俯卧位实施率（三闸门分母 + 俯卧位分子）-----
    icu08_data = get_icu08_data(dept_codes, start_date, end_date)
    icu08_num = icu08_data["num_count"]
    icu08_den = icu08_data["den_count"]
    if icu08_den == 0:
        icu08_num = _jitter(72, 0.1)
        icu08_den = _jitter(100, 0.05)

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
        "ICU-09": {"num": _jitter(148, 0.1), "den": 155},
        "ICU-10": {"num": _jitter(142, 0.1), "den": 155},
        "ICU-11": {"num": _jitter(11, 0.1), "den": 12},
        "ICU-12": {"num": _jitter(2, 0.3), "den": 62},
        "ICU-13": {"num": _jitter(3, 0.3), "den": 73},
        "ICU-14": {"num": _jitter(5, 0.2), "den": 74},
        "ICU-15": {"num": _jitter(3, 0.3), "den": 120},
        "ICU-16": {"num": _jitter(8, 0.2), "den": 879},
        "ICU-17": {"num": _jitter(2, 0.3), "den": 1110},
        "ICU-18": {"num": _jitter(67, 0.1), "den": 75},
        "ICU-19": {"num": _jitter(110, 0.1), "den": 140},
    }
    
    rows = []
    for code, info in summary_data.items():
        if code == "ICU-01" and icu01_den > 0:
            display_val = icu01_value
            val_for_status = icu01_value
        else:
            # 根据变化后的分子分母重算比值
            if info["den"] == 0:
                display_val = 0.0
                val_for_status = 0.0
            else:
                cfg = INDICATORS_CONFIG.get(code, {})
                multiplier = 100
                if cfg.get("unit") == "‰":
                    multiplier = 1000
                elif cfg.get("unit") == ":1":
                    multiplier = 1
                if code == "ICU-11":
                    display_val = round(info["num"] / info["den"], 2)
                else:
                    display_val = round(info["num"] / info["den"] * multiplier, 1)
                val_for_status = display_val
        rows.append({
            "indicator": code,
            "numerator": info["num"],
            "denominator": info["den"],
            "value": display_val,
            "status": eval_status(code, val_for_status)
        })
    return rows

def query_trend(code: str, year: int, icu_unit: str = "all"):
    """
    第二级：单指标全年 12 个月趋势数据
    """
    base = get_mock_base_values()
    val = base.get(code, 50.0)
    if isinstance(val, dict):
        val = val.get("3h", 75.0)
    
    random.seed(hash(code) + year)
    trend_vals = []
    for m in range(1, 13):
        if m > 6:
            trend_vals.append(None)
        else:
            jitter = random.uniform(-0.1, 0.1) * val
            trend_vals.append(round(max(0.0, val + jitter), 1 if UNIT_MAP[code] != "" else 2))
            
    return {m: trend_vals[m-1] for m in range(1, 13)}

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
                # 抗菌药 + 目的徽章
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

    # ---- ICU-07：DVT预防率明细 ----
    if code == "ICU-07":
        data = get_dvt_prevention_patients(dept_codes, start_date, end_date)
        if part == "numerator":
            items = []
            for p in data.get("drug_patients", []):
                items.append({
                    "patient_id": p.get("patient_id", p.get("pid", "")), "name": p.get("name", ""),
                    "gender": "", "age": "", "bed_no": f"药物预防({p.get('order_count',0)}条)", "dept": "",
                    "admit_time": str(p.get("matched_orders", [""])[0])[:60] if p.get("matched_orders") else "",
                    "discharge_time": "", "admission_source": "", "value": p.get("order_count", 0),
                })
            for p in data.get("mech_patients", []):
                items.append({
                    "patient_id": p.get("patient_id", p.get("pid", "")), "name": p.get("name", ""),
                    "gender": "", "age": "", "bed_no": f"机械预防({p.get('order_count',0)}条)", "dept": "",
                    "admit_time": str(p.get("matched_orders", [""])[0])[:60] if p.get("matched_orders") else "",
                    "discharge_time": "", "admission_source": "", "value": p.get("order_count", 0),
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
    返回符合前端大屏期待的数据格式。
    ICU-01 的分母优先从 MongoDB bedRecord/configBed 取真实床位日数。
    """
    base = get_mock_base_values()

    # ----- ICU-01：用 MongoDB 真实数据重新计算 -----
    start_str = start.isoformat() if hasattr(start, 'isoformat') else str(start)
    end_str = end.isoformat() if hasattr(end, 'isoformat') else str(end)

    # 分母：实际开放总床日数（bedRecord / configBed）
    icu01_den = get_icu01_bed_days(dept, start_str, end_str)

    # 分子：实际占用总床日数（patient 表，排除 invalid）
    dept_codes = _resolve_dept_codes(dept)
    icu01_num = 0
    for dc in dept_codes:
        icu01_num += get_occupied_bed_days(dc, start_str, end_str)

    if icu01_num > 0 and icu01_den > 0:
        base["ICU-01"] = round(icu01_num / icu01_den * 100, 1)

    trend = {}
    months = ["1月", "2月", "3月", "4月", "5月", "6月"]
    for code, val in base.items():
        if isinstance(val, (int, float)):
            random.seed(hash(code))
            trend[code] = [
                round(max(0.0, val * (0.9 + random.random() * 0.2)), 1 if code != "ICU-11" else 2)
                for _ in range(6)
            ]

    return {
        "values": base,
        "trend": trend,
        "months": months
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

@app.get("/api/indicators/list")
def indicator_list(period: str, icu_unit: str = "all", end_period: str = ""):
    """
    第一级：指标汇总列表。
    period=2026-06 单月, period=2026-01&end_period=2026-06 跨月汇总。
    """
    ck = _cache_key("list", period, icu_unit, end_period)
    cached = _cache_get(ck)
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

        agg = {}       # code → {num, den, unit, name, monthly: {mon: val}}
        for mon in month_labels:
            rows = query_summary(mon, icu_unit)
            for r in rows:
                code = r["indicator"]
                if code not in agg:
                    agg[code] = {"num": 0, "den": 0, "unit": UNIT_MAP.get(code, ""),
                                 "name": NAME_MAP.get(code, code), "monthly": {}}
                agg[code]["num"] += r["numerator"]
                agg[code]["den"] += r["denominator"]
                agg[code]["monthly"][mon] = r["value"]

        # ICU-02/03 是时点值(人数/床位数),跨月不累加,取最后一个月
        for code in ("ICU-02", "ICU-03"):
            if code in agg and len(month_labels) > 1:
                last = query_summary(month_labels[-1], icu_unit)
                for r in last:
                    if r["indicator"] == code:
                        agg[code]["num"] = r["numerator"]
                        agg[code]["den"] = r["denominator"]

        result = []
        for code, v in agg.items():
            if code == "ICU-11":
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
                "status": eval_status(code, val),
                "months": month_labels,
                "monthly": [v["monthly"].get(mon) for mon in month_labels],
            })
        result = sorted(result, key=lambda x: x["code"])
        _cache_set(ck, result)
        return result

    # 单月查询
    rows = query_summary(period, icu_unit)
    result = [
        {
            "code": r["indicator"],
            "name": NAME_MAP.get(r["indicator"], r["indicator"]),
            "numerator": r["numerator"],
            "denominator": r["denominator"],
            "value": r["value"],
            "unit": UNIT_MAP.get(r["indicator"], ""),
            "status": r["status"],
        } for r in rows
    ]
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
def indicator_detail(code: str, period: str, part: str, icu_unit: str = "all", end_period: str = ""):
    """
    第三级：分子/分母下钻明细。
    支持 end_period 跨月聚合。
    """
    ck = _cache_key("detail", code, period, part, icu_unit, end_period)
    cached = _cache_get(ck)
    if cached is not None:
        return cached
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
        # 聚合：按 patient_id 去重累加
        merged = {}
        for mon in months:
            for p in query_detail(code, mon, part, icu_unit):
                pid = p.get("patient_id", "")
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
        items = query_detail(code, period, part, icu_unit)

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
    else:
        desc_info = SOURCE_DESC.get(code, {"numerator": "分子明细", "denominator": "分母明细"})
        source_desc = desc_info.get(part, "明细")

    result = {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "part": part,
        "count": len(items),
        "source_desc": source_desc,
        "patients": items,
    }
    _cache_set(ck, result)
    return result


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
