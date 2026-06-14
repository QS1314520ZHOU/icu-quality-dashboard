# main.py
from fastapi import FastAPI
from datetime import date, datetime
from ai_analyzer import analyze
from db import get_open_bed_count, get_occupied_bed_days, get_client, BED_DB_NAMES
import random

app = FastAPI(title="ICU质控指标API")

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
    "ICU-05": {"name": "感染性休克bundle完成率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-06": {"name": "抗菌药物治疗前病原学送检率", "unit": "%", "good": (90, 100), "warn": (50, 100), "dir": "higher"},
    "ICU-07": {"name": "DVT预防率", "unit": "%", "good": (85, 100), "warn": (60, 100), "dir": "higher"},
    "ICU-08": {"name": "中重度ARDS俯卧位通气实施率", "unit": "%", "good": (80, 100), "warn": (50, 100), "dir": "higher"},
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
    "ICU-05": {"numerator": "完成3h/6h Bundle集束化治疗的患者数", "denominator": "确诊为感染性休克的患者总数"},
    "ICU-06": {"numerator": "使用限制/非限制类抗生素前送检病原学标本的患者数", "denominator": "接受抗菌药物治疗的患者总数"},
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
        "ICU-05": {"1h": 88.0, "3h": 76.0, "6h": 65.0}, "ICU-06": 93.5,
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
        icu01_den = 1560  # 完全无数据时回退 mock
        icu01_num = 1284
        icu01_value = 82.3

    import random as _random
    _random.seed(hash(period + icu_unit))
    def _jitter(v, pct=0.15):
        return max(0, round(v * (1 + _random.uniform(-pct, pct))))

    summary_data = {
        "ICU-01": {"num": icu01_num, "den": icu01_den},
        "ICU-02": {"num": _jitter(18, 0.1), "den": 20},
        "ICU-03": {"num": _jitter(56, 0.1), "den": 20},
        "ICU-04": {"num": _jitter(87, 0.15), "den": 150},
        "ICU-05": {"num": _jitter(76, 0.1), "den": 100},
        "ICU-06": {"num": _jitter(131, 0.1), "den": 140},
        "ICU-07": {"num": _jitter(135, 0.1), "den": 155},
        "ICU-08": {"num": _jitter(34, 0.15), "den": 47},
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
        elif code == "ICU-05":
            # Bundle 分时段，保持 mock
            val = base[code]
            display_val = val.get("3h") if isinstance(val, dict) else val
            val_for_status = val
        else:
            # 根据变化后的分子分母重算比值
            cfg = INDICATORS_CONFIG.get(code, {})
            multiplier = 100  # default
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

    # ---- ICU-02/03：非患者指标，返回空 ----
    if code in ("ICU-02", "ICU-03"):
        return []

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
                    "hisPid": 1, "name": 1, "hisBed": 1, "gender": 1, "birthday": 1,
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
                    mrn = d.get("hisPid") or d.get("mrn") or "-"

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
    period=2026-06           → 单月
    period=2026-01&end_period=2026-06 → 跨月汇总
    """
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
        return sorted(result, key=lambda x: x["code"])

    # 单月查询
    rows = query_summary(period, icu_unit)
    return [
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

@app.get("/api/indicators/{code}/trend")
def indicator_trend(code: str, year: int, icu_unit: str = "all"):
    """第二级：某指标全年12个月趋势"""
    rows = query_trend(code, year, icu_unit)
    return {
        "code": code, 
        "name": NAME_MAP.get(code, code),
        "months": [f"{m}月" for m in range(1, 13)],
        "values": [rows.get(m) for m in range(1, 13)],
    }

@app.get("/api/indicators/{code}/detail")
def indicator_detail(code: str, period: str, part: str, icu_unit: str = "all"):
    """
    第三级：分子/分母下钻明细。
    """
    items = query_detail(code, period, part, icu_unit)

    # ICU-01 的描述需要区分分子（在床天数）和分母（床位配置）
    if code == "ICU-01":
        if part == "numerator":
            source_desc = "实际占用总床日数 — 每位患者在统计期内的在床天数"
        else:
            source_desc = "实际开放总床日数 — 各科室床位配置（每床每日计1床日）"
    else:
        desc_info = SOURCE_DESC.get(code, {"numerator": "分子明细", "denominator": "分母明细"})
        source_desc = desc_info.get(part, "明细")

    return {
        "code": code,
        "name": NAME_MAP.get(code, code),
        "part": part,
        "count": len(items),
        "source_desc": source_desc,
        "patients": items,
    }


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
