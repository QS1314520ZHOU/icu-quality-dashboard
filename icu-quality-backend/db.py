# db.py - MongoDB 连接 & ICU-01 分母逻辑（从 .env 读取配置）
import os
from pathlib import Path
from pymongo import MongoClient
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
import re
from dotenv import load_dotenv

# 加载 .env 文件。打包成二进制后，优先读取可执行文件同目录的 .env。
import sys

if getattr(sys, "frozen", False):
    env_candidates = [
        Path(sys.executable).resolve().parent / ".env",
        Path.cwd() / ".env",
    ]
else:
    env_candidates = [
        Path(__file__).parent / ".env",
        Path.cwd() / ".env",
    ]
for env_path in env_candidates:
    if env_path.exists():
        load_dotenv(env_path)
        break


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ============================================================
# 数据库连接配置
# ============================================================
class DBConfig:
    def __init__(self, prefix: str):
        self.host = _env(f"{prefix}_DB_HOST", "127.0.0.1")
        self.port = int(_env(f"{prefix}_DB_PORT", "27017"))
        self.user = _env(f"{prefix}_DB_USER")
        self.password = _env(f"{prefix}_DB_PASSWORD")
        self.auth_db = _env(f"{prefix}_DB_AUTH")


# SmartCare（ICU 临床业务库）
SMARTCARE_CFG = DBConfig("SMARTCARE")
# DataCenter（数据中心 / 指标汇总库）
DATACENTER_CFG = DBConfig("DATACENTER")

# bedRecord / configBed / patient 所在的数据库，按优先级排列
# 优先使用 .env 中 SMARTCARE_DB_AUTH 指定的库，其 _4y 变体作为兜底
_smartcare_auth = SMARTCARE_CFG.auth_db  # e.g. "SmartCare" or "SmartCare_4y"
if _smartcare_auth.endswith("_4y"):
    BED_DB_NAMES = [_smartcare_auth, _smartcare_auth.replace("_4y", "")]
else:
    BED_DB_NAMES = [_smartcare_auth, _smartcare_auth + "_4y"]

# ============================================================
# 连接缓存
# ============================================================
_clients: dict[str, MongoClient] = {}


def _make_client(cfg: DBConfig, db_name: str) -> MongoClient:
    """
    创建 MongoDB 连接。
    优先用 .env 配置的账号密码认证；认证失败时自动回退到无认证连接。
    """
    if cfg.user:
        try:
            client = MongoClient(
                host=cfg.host,
                port=cfg.port,
                username=cfg.user,
                password=cfg.password,
                authSource=cfg.auth_db,
                serverSelectionTimeoutMS=3000,
            )
            # 验证认证是否成功
            client[db_name].command("ping")
            return client
        except Exception:
            pass  # 认证失败 → 回退无认证连接

    # 无认证回退
    return MongoClient(
        host=cfg.host,
        port=cfg.port,
        serverSelectionTimeoutMS=5000,
    )


def get_client(db_name: str = "SmartCare") -> MongoClient:
    """
    懒加载 MongoDB 连接。
    优先匹配 DataCenter / SmartCare 配置，按 db_name 归属选择合适的凭证。
    """
    if db_name in _clients:
        return _clients[db_name]

    # 根据库名猜测所属配置（SmartCare_4y 也用 SmartCare 凭证）
    if db_name.startswith("SmartCare") or db_name == "SmartCare":
        cfg = SMARTCARE_CFG
    else:
        cfg = DATACENTER_CFG

    client = _make_client(cfg, db_name)
    _clients[db_name] = client
    return client


def get_smartcare_client() -> MongoClient:
    """获取 SmartCare 库的连接（用于 bedRecord/configBed 查询）"""
    return get_client(BED_DB_NAMES[0])


def get_datacenter_client() -> MongoClient:
    """获取 DataCenter 库的连接"""
    return get_client(DATACENTER_CFG.auth_db or "DataCenter")


def get_datacenter_db():
    """获取 .env 指定的 DataCenter 数据库句柄。"""
    db_name = DATACENTER_CFG.auth_db or "DataCenter"
    return get_datacenter_client()[db_name]


def _gbk_mojibake(text: str) -> str:
    """兼容 4y 库中以 GBK 字节误按 latin1 存储/展示的中文字段。"""
    try:
        return text.encode("gbk").decode("latin1")
    except Exception:
        return text


def _keyword_regex(keywords: list[str]) -> str:
    variants = []
    seen = set()
    for kw in keywords:
        for item in (kw, _gbk_mojibake(kw)):
            if item and item not in seen:
                seen.add(item)
                variants.append(re.escape(item))
    return "|".join(variants)


# 不同院区/接口的医嘱状态编码不完全一致：
# - 旧接口常见 "3"
# - 部分 DataCenter_4y 只保留 "已审核/停止"，没有 "已执行"
# 取消/撤销不纳入。
EXECUTED_ORDER_STATUSES = [
    "已执行", "已审核", "停止", "3",
    _gbk_mojibake("已执行"), _gbk_mojibake("已审核"), _gbk_mojibake("停止"),
]
LAB_ORDER_TYPES = ["检验", _gbk_mojibake("检验")]


# ============================================================
# ICU-01 分母查询
# ============================================================

def get_open_bed_count(dept_code: str, start_date: str, end_date: str) -> int:
    """
    ICU-01（ICU床位使用率）分母 —— 实际开放床位数。

    优先级：
      1. bedRecord 集合：按 deptCode（支持逗号分隔多科室）、time、BedNum 查询
      2. configBed 集合：统计该 deptCode 下的床位数量（hisName 条数）

    参数：
      dept_code  - 科室编码，如 "JJL000282"
      start_date - 统计开始日期 "YYYY-MM-DD"
      end_date   - 统计结束日期 "YYYY-MM-DD"

    返回：开放床位数，无数据返回 0
    """
    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
    except ValueError:
        return 0

    for db_name in BED_DB_NAMES:
        try:
            client = get_client(db_name)
            db = client[db_name]

            # ---- Priority 1: bedRecord ----
            # deptCode 可能是逗号分隔的多科室字段，如 "JJL000283,0801,JJL000282"
            # 用正则匹配目标 dept_code
            bed_record = db.bedRecord.find_one({
                "deptCode": {"$regex": dept_code},
                "time": {"$gte": start_dt, "$lte": end_dt},
            })
            if bed_record and bed_record.get("bedNum"):
                return int(bed_record["bedNum"])

            # ---- Priority 2: configBed 兜底 ----
            # 每个 configBed 文档对应一张床位，hisName 是床位号
            config_count = db.configBed.count_documents({"deptCode": dept_code})
            if config_count > 0:
                return config_count

        except Exception:
            continue  # 当前库不可用，尝试下一个

    return 0


def get_all_dept_open_beds(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    批量获取多个科室的开放床位数。
    返回 {dept_code: bed_count}
    """
    result = {}
    for dc in dept_codes:
        result[dc] = get_open_bed_count(dc, start_date, end_date)
    return result


# ============================================================
# ICU-01 分子：实际占用总床日数
# ============================================================

def get_occupied_bed_days(dept_code: str, start_date: str, end_date: str) -> int:
    """
    ICU-01（ICU床位使用率）分子 —— 实际占用总床日数。

    定义：统计期内，每日 0 点时刻在 ICU 的患者人数总和。

    逻辑：
      - 查询 patient 表，条件：
        deptCode = 目标科室
        status != 'invalid'
        icuAdmissionTime <= 统计期末
        icuDischargeTime >= 统计期始 或 未出院
      - 对每位患者计算与统计期的日期交集：
        患者"在科"的午夜范围 = [入科次日0点, 出科当日0点]
        (入院当日不计，出院当日计入 —— 符合卫生部统计口径)
      - 与统计期 [start_date, end_date] 取交集，计天数

    返回：占用总床日数，无数据返回 0
    """
    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
    except ValueError:
        return 0

    total = 0

    for db_name in BED_DB_NAMES:
        try:
            client = get_client(db_name)
            db = client[db_name]

            # 查询符合条件的患者（只取需要的字段）
            patients = list(db.patient.find(
                {
                    "deptCode": dept_code,
                    "status": {"$ne": "invalid"},
                    "icuAdmissionTime": {"$lte": datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)},
                    "$or": [
                        {"icuDischargeTime": {"$gte": start_dt}},
                        {"icuDischargeTime": None},
                        {"icuDischargeTime": {"$exists": False}},
                    ],
                },
                {"icuAdmissionTime": 1, "icuDischargeTime": 1},
            ))

            if not patients:
                continue  # 当前库无数据，尝试下一个

            for p in patients:
                admit_dt: datetime = p.get("icuAdmissionTime")
                discharge_dt: datetime | None = p.get("icuDischargeTime")

                if not admit_dt:
                    continue

                # 患者"在科"的午夜范围：
                # 首个在科午夜 = 入科日期的次日 0:00（入院当日不计）
                first_midnight = datetime(
                    admit_dt.year, admit_dt.month, admit_dt.day
                ) + timedelta(days=1)

                # 末个在科午夜 = 出科日期的 0:00（出院当日计入）
                if discharge_dt:
                    last_midnight = datetime(
                        discharge_dt.year, discharge_dt.month, discharge_dt.day
                    )
                else:
                    last_midnight = end_dt  # 未出院，计到统计期末

                # 与统计期取交集
                first = max(first_midnight, start_dt)
                last = min(last_midnight, end_dt)

                if first <= last:
                    total += (last - first).days + 1

            break  # 有数据就不再查下一个库

        except Exception:
            continue

    return total


# ============================================================
# ICU-02/03：医师/护士人数（从 account 表读取）
# ============================================================

DOCTOR_PROFESSIONS = {
    "AttendingDoctor", "DeputyDirector", "Director", "DirectorAssistant",
    "Doctor", "Intern", "StandardizedDoctor", "StudyDoctor",
}
NURSE_PROFESSIONS = {
    "Matron", "MatronAssistant", "Nurse", "NurseLeader",
    "PracticeNurse", "StandardizedNurse", "StudyNurse",
}

PROFESSION_CN = {
    "AttendingDoctor": "主治医师",
    "DeputyDirector": "副主任医师",
    "Director": "主任医师",
    "DirectorAssistant": "主任助理",
    "Doctor": "医师",
    "Intern": "实习生",
    "StandardizedDoctor": "规培医师",
    "StudyDoctor": "进修医师",
    "Matron": "护士长",
    "MatronAssistant": "护士长助理",
    "Nurse": "护士",
    "NurseLeader": "护理组长",
    "PracticeNurse": "实习护士",
    "StandardizedNurse": "规培护士",
    "StudyNurse": "进修护士",
    "Admin": "管理员",
    "SystemAdmin": "系统管理员",
}


def get_staff_count(dept_code: str, role: str) -> int:
    """
    从 account 表统计某科室的医师或护士人数。

    role: 'doctor' → 统计 Doctor + Director
          'nurse'  → 统计 Nurse + NurseLeader + Matron

    参数 dept_code 支持逗号分隔多科室字段的 regex 匹配。
    """
    professions = DOCTOR_PROFESSIONS if role == "doctor" else NURSE_PROFESSIONS

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            count = db.account.count_documents({
                "valid": "valid",
                "departmentCode": {"$regex": dept_code},
                "profession": {"$in": list(professions)},
            })
            if count > 0:
                return count
        except Exception:
            continue
    return 0


# ============================================================
# ICU-04：APACHEⅡ≥15 收治率
# ============================================================

def get_icu04_apache_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    返回 {den_count, num_count, num_patients, den_patients}

    分母：统计期内该科室在科患者数（status != invalid，入出科时间与统计期有交集）
    分子：分母患者中，当月首次 apacheII 评分 total ≥ 15 的人数
    """
    from datetime import datetime as dt, timedelta
    from bson import ObjectId

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)

    result = {"den_count": 0, "num_count": 0, "num_patients": [], "den_patients": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # 分母：在科患者
            den_patients = list(db.patient.find(
                {
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                    "icuAdmissionTime": {"$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)},
                    "$or": [
                        {"icuDischargeTime": {"$gte": start_dt}},
                        {"icuDischargeTime": None},
                        {"icuDischargeTime": {"$exists": False}},
                    ],
                },
                {"_id": 1, "mrn": 1, "hisPid": 1, "patientId": 1, "name": 1, "hisBed": 1, "icuAdmissionTime": 1},
            ))
            den_ids = [str(p["_id"]) for p in den_patients]
            result["den_count"] = len(den_ids)
            result["den_patients"] = den_patients

            if not den_ids:
                continue

            # 分子：聚合查询 — 一次查出所有患者的首次 apacheII 评分
            pipeline = [
                {"$match": {
                    "pid": {"$in": den_ids},
                    "scoreType": "apacheII",
                    "valid": True,
                    "time": {
                        "$gte": start_dt,
                        "$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59),
                    },
                }},
                {"$sort": {"time": 1}},
                {"$group": {
                    "_id": "$pid",
                    "total": {"$first": "$total"},
                    "score_time": {"$first": "$time"},
                }},
                {"$match": {"total": {"$gte": 15}}},
            ]
            high_scores = {s["_id"]: s for s in list(db.score.aggregate(pipeline))}

            # 构建患者映射
            pat_map = {str(p["_id"]): p for p in den_patients}
            num_patients = []
            for pid_str, s in high_scores.items():
                p = pat_map.get(pid_str)
                if p:
                    num_patients.append({
                        "_id": pid_str,
                        "mrn": p.get("mrn", "") or p.get("hisPid", ""),
                        "patientId": p.get("patientId", ""),
                        "name": p.get("name", ""),
                        "hisBed": p.get("hisBed", ""),
                        "score": s.get("total", 0),
                        "score_time": s.get("score_time"),
                    })

            result["num_count"] = min(len(num_patients), result["den_count"])
            result["num_patients"] = num_patients
            break

        except Exception:
            continue

    return result


# ============================================================
# ICU-05：感染性休克 Bundle 完成率（1h/3h/6h）
# ============================================================

def get_bundle_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    返回 {total, h1_num, h3_num, h6_num, h1_patients, h3_patients, h6_patients, den_patients}
    分母 = diseaseDiagnosis 表中 diseaseType='脓毒性休克', 诊断时间在统计期内,
           且患者在该科室的 patient 表中(status != invalid)
    分子1h/3h/6h = infectionShockV2 中 bundle 达标
    """
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)

    result = {"total": 0, "h1_num": 0, "h3_num": 0, "h6_num": 0,
              "h1_patients": [], "h3_patients": [], "h6_patients": [], "den_patients": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # 分母：diseaseDiagnosis 表 脓毒性休克
            diagnoses = list(db.diseaseDiagnosis.find(
                {
                    "diseaseType": "脓毒性休克",
                    "valid": {"$ne": False},
                    "diagnosisTime": {
                        "$gte": start_dt,
                        "$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59),
                    },
                },
                {"pid": 1, "patientName": 1, "mrn": 1, "diagnosisTime": 1},
            ))
            if not diagnoses:
                continue

            # 关联 patient 表，过滤 deptCode 和 status
            shock_pids = list(set(d["pid"] for d in diagnoses))
            # pid 是字符串，patient._id 是 ObjectId，需转换比较
            from bson import ObjectId
            obj_ids = []
            for pid in shock_pids:
                try:
                    obj_ids.append(ObjectId(pid))
                except Exception:
                    pass

            patients = list(db.patient.find(
                {
                    "_id": {"$in": obj_ids},
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                },
                {"_id": 1, "mrn": 1, "hisPid": 1, "name": 1, "hisBed": 1},
            ))
            valid_pids = set(str(p["_id"]) for p in patients)
            pat_map = {str(p["_id"]): p for p in patients}

            # 筛出在该科室的有效诊断，建立 {diseaseId_string: diag} 映射
            diag_by_id = {}
            den_list = []
            for d in diagnoses:
                if d["pid"] in valid_pids:
                    diag_by_id[str(d["_id"])] = d
                    den_list.append(d)
            result["total"] = len(den_list)
            result["den_patients"] = [
                {"_id": d["pid"], "mrn": d.get("mrn", ""), "name": d.get("patientName", ""),
                 "hisBed": "", "diagnosisTime": d.get("diagnosisTime")}
                for d in den_list
            ]

            if not den_list:
                continue

            # 分子：通过 diseaseId 关联 infectionShockV2
            diag_id_strings = list(diag_by_id.keys())
            shocks = list(db.infectionShockV2.find(
                {"diseaseId": {"$in": diag_id_strings}},
                {"diseaseId": 1, "group1H": 1, "group3H": 1, "group6H": 1},
            ))
            shock_map = {s["diseaseId"]: s for s in shocks}

            for did_str, s in shock_map.items():
                diag = diag_by_id.get(did_str)
                if not diag:
                    continue
                pid_str = diag["pid"]
                p = pat_map.get(pid_str)
                if not p:
                    continue
                info = {
                    "_id": pid_str,
                    "mrn": p.get("mrn", "") or p.get("hisPid", ""),
                    "name": p.get("name", ""),
                    "hisBed": p.get("hisBed", ""),
                }
                g1 = s.get("group1H", {}) or {}
                g3 = s.get("group3H", {}) or {}
                g6 = s.get("group6H", {}) or {}
                if g1.get("baStandard") or g1.get("finish"):
                    result["h1_num"] += 1
                    result["h1_patients"].append(info)
                if g3.get("baStandard") or g3.get("finish"):
                    result["h3_num"] += 1
                    result["h3_patients"].append(info)
                # 6h达标 = 路径1(6h全部完成) OR 路径2(休克纠正 AND 1h达标 AND 3h达标)
                h1_ok = g1.get("baStandard") or g1.get("finish")
                h3_ok = g3.get("baStandard") or g3.get("finish")
                h6_ok = g6.get("baStandard") or g6.get("finish")
                shock_corrected = g1.get("finish") or g3.get("finish")
                if h6_ok or (shock_corrected and h1_ok and h3_ok):
                    result["h6_num"] += 1
                    result["h6_patients"].append(info)

            break
        except Exception:
            continue

    return result


# ============================================================
# ICU-08 氧疗途径判定（主判据，替代通气模式猜测）
# ============================================================

# 无创氧疗途径 — 命中任一即排除
O2_ROUTE_NON_INVASIVE = {"鼻塞", "面罩", "无创", "高流量", "箱氧", "鼻导管",
                          "储氧面罩", "低流量", "低流量用氧", "低流量箱氧",
                          "未吸氧", "鼻氧", "面罩吸氧", "储氧", "鼻", "拒绝",
                          "拒绝吸氧", "暂停吸氧", "球囊", "呼吸球囊", "球囊通气",
                          "简易呼吸器", "家用呼吸机", "家用", "文丘里", "无创高频",
                          "高频", "鼻管辅"}

# 有创氧疗途径 — 经人工气道
O2_ROUTE_INVASIVE = {"管辅", "切辅", "管氧", "切氧", "管文", "切文", "管高", "切高", "有创"}


def _num_from_item(item: dict, prefer_str: bool = False) -> float | None:
    keys = ("strVal", "fVal") if prefer_str else ("fVal", "strVal")
    for key in keys:
        raw = item.get(key)
        if raw in (None, ""):
            continue
        try:
            return float(str(raw).replace("%", "").replace("L/min", "").strip())
        except (TypeError, ValueError):
            continue
    return None


def _pf_ratio_from_bedsides(bedsides: list) -> float | None:
    vals = {}
    for item in bedsides or []:
        if item.get("valid") != "valid":
            continue
        code = item.get("code")
        if code == "param_bg_P/Fratio":
            return _num_from_item(item)
        if code == "param_bg_OI":
            vals["oi"] = _num_from_item(item, prefer_str=True)
        elif code == "param_bg_po2":
            vals["po2"] = _num_from_item(item)
        elif code == "param_bg_FiO2":
            vals["fio2"] = _num_from_item(item, prefer_str=True)
    if vals.get("oi") is not None:
        return vals["oi"]
    po2 = vals.get("po2")
    fio2 = vals.get("fio2")
    if po2 is not None and fio2:
        fio2_fraction = fio2 / 100 if fio2 > 1 else fio2
        if fio2_fraction > 0:
            return po2 / fio2_fraction
    return None


def _parse_o2_routes(raw: str) -> set:
    """解析氧疗途径字符串（可能含 、/ 分隔的组合值），返回归一化集合。过滤纯数字脏数据。"""
    if not raw:
        return set()
    s = raw.strip().replace("、", ",").replace("，", ",").replace("/", ",")
    s = s.replace("+", ",").replace(" ", "")
    routes = set()
    for x in s.split(","):
        x = x.strip()
        if not x:
            continue
        # 过滤纯数字（脏数据）
        try:
            float(x)
            continue  # 纯数字，跳过
        except ValueError:
            pass
        routes.add(x)
    return routes


def is_invasive_by_o2route(raw_route: str) -> tuple:
    """
    氧疗途径判定有创/无创。
    返回 (is_invasive: bool, routes: set, reason: str)
    """
    routes = _parse_o2_routes(raw_route)
    if not routes:
        return False, routes, "空值"

    # 无创命中 → 排除
    non_inv = {kw for route in routes for kw in O2_ROUTE_NON_INVASIVE if kw in route}
    if non_inv:
        return False, routes, f"无创途径({','.join(non_inv)})"

    # 有创命中 → 纳入
    inv = {kw for route in routes for kw in O2_ROUTE_INVASIVE if kw in route}
    if inv:
        return True, routes, f"有创途径({','.join(inv)})"

    # 未知 → 排除（保守）
    return False, routes, f"未知途径({','.join(routes)})"


# ============================================================
# ICU-08：中重度ARDS俯卧位实施率 分母 — P/F ≤150 且 PEEP≥5 且有创通气
# ============================================================

def get_ards_denominator(dept_codes: list, start_date: str, end_date: str,
                         peep_threshold: float = 5.0, oi_threshold: float = 150.0,
                         time_tolerance_min: int = 60) -> dict:
    """
    ICU-08 分母：中重度ARDS患者（PEEP≥5 且 P/F≤150）。

    【取数逻辑】
    1. 从 bGATemp 表取 code='param_bg_P/Fratio' 且 bedsides.valid='valid' 的血气
    2. 每条血气按 pid 关联 bedside 表，向前找最近一条 code='param_vent_peep'
       且 valid=true 且时间在 ±time_tolerance_min 分钟内的 PEEP 记录
    3. 配对后判定：strVal≥peep_threshold 且 fVal≤oi_threshold
    4. 同一 pid 在统计期内首次满足条件即纳入分母

    关联字段：
      bGATemp.eventExe.pid == bedside.pid  (patient ObjectId)
      bGATemp → patient._id 关联获取 deptCode/mrn

    返回: {total, patients: [{pid, mrn, name, pf_ratio, peep, pf_time, peep_time}]}
    """
    from datetime import datetime as dt, timedelta
    from bson import ObjectId

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)

    result = {"total": 0, "patients": []}
    seen_pids = set()

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # Step 1: 取统计期内的血气 P/F ratio (bGATemp + bGATemp1)
            all_bga = []
            for coll_name in ["bGATemp", "bGATemp1"]:
                try:
                    bgas = list(db[coll_name].find(
                        {
                            "deptCode": {"$in": dept_codes},
                            "eventExe.startTime": {
                                "$gte": start_dt,
                                "$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59),
                            },
                            "bedsides": {
                                "$elemMatch": {
                                    "code": "param_bg_P/Fratio",
                                    "valid": "valid",
                                },
                            },
                        },
                        {
                            "eventExe.pid": 1, "mrn": 1, "deptCode": 1,
                            "eventExe.startTime": 1, "bedsides": 1,
                        },
                    ).sort("eventExe.startTime", 1))
                    all_bga.extend(bgas)
                except Exception:
                    continue

            if not all_bga:
                continue

            # Step 2: 逐条血气尝试配对（同 pid 取首次满足条件的配对）
            for bga in all_bga:
                pid = bga["eventExe"]["pid"]
                if pid in seen_pids:
                    continue

                pf_time = bga["eventExe"]["startTime"]
                pf_ratio = None
                for item in bga.get("bedsides", []):
                    if item.get("code") == "param_bg_P/Fratio" and item.get("valid") == "valid":
                        pf_ratio = item.get("fVal")
                        break

                if pf_ratio is None or pf_ratio >= oi_threshold:
                    continue

                window_start = pf_time - timedelta(minutes=time_tolerance_min)

                # 就近配对 PEEP
                peep_doc = db.bedside.find_one(
                    {
                        "pid": pid,
                        "code": "param_vent_peep",
                        "valid": True,
                        "time": {"$gte": window_start, "$lte": pf_time},
                    },
                    {"strVal": 1, "time": 1},
                    sort=[("time", -1)],
                )
                if not peep_doc:
                    continue

                try:
                    peep_val = float(peep_doc.get("strVal", "0"))
                except (ValueError, TypeError):
                    continue

                if peep_val < peep_threshold:
                    continue

                # 查氧疗途径（主判据）
                o2_doc = db.bedside.find_one(
                    {
                        "pid": pid,
                        "code": "param_XiYangTuJing",
                        "valid": True,
                        "time": {"$gte": window_start, "$lte": pf_time},
                    },
                    {"strVal": 1, "time": 1},
                    sort=[("time", -1)],
                )
                o2_raw = o2_doc.get("strVal", "") if o2_doc else ""
                o2_invasive, o2_routes, o2_reason = is_invasive_by_o2route(o2_raw)
                if not o2_invasive:
                    continue  # 无创氧疗途径 → 跳过

                # 首次匹配！纳入分母
                seen_pids.add(pid)
                pat_name = ""
                mrn = bga.get("mrn", "")
                try:
                    pat = db.patient.find_one(
                        {"_id": ObjectId(pid)},
                        {"name": 1, "mrn": 1, "hisBed": 1},
                    )
                    if pat:
                        pat_name = pat.get("name", "")
                        if not mrn:
                            mrn = pat.get("mrn", "") or pat.get("hisPid", "")
                except Exception:
                    pass
                result["patients"].append({
                    "pid": pid,
                    "mrn": mrn,
                    "name": pat_name,
                    "pf_ratio": pf_ratio,
                    "peep": peep_val,
                    "o2_route": o2_raw,
                    "o2_reason": o2_reason,
                    "pf_time": pf_time,
                    "peep_time": peep_doc.get("time"),
                    "o2_time": o2_doc.get("time") if o2_doc else None,
                })

            result["total"] = len(result["patients"])
            break

        except Exception:
            continue

    return result


def get_ards_prone_numerator(den_patients: list, dept_codes: list) -> dict:
    """
    ICU-08 分子：分母患者中，住院期间存在俯卧位记录的住院数。

    判据：bedside 表 code=param_TiWei, strVal 包含"俯卧位",
          valid=true, time 落在该次住院的入科~出科区间内。

    返回: {num_count, num_patients: [{pid, mrn, name, prone_times[]}]}
    """
    from datetime import datetime as dt
    from bson import ObjectId

    result = {"num_count": 0, "num_patients": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            for p in den_patients:
                pid = p.get("pid", "")
                if not pid:
                    continue

                # 查住院区间
                try:
                    pat = db.patient.find_one(
                        {"_id": ObjectId(pid)},
                        {"icuAdmissionTime": 1, "icuDischargeTime": 1},
                    )
                except Exception:
                    continue

                if not pat or not pat.get("icuAdmissionTime"):
                    continue

                admit = pat["icuAdmissionTime"]
                discharge = pat.get("icuDischargeTime") or dt.now()

                # 查俯卧位记录
                prone_records = list(db.bedside.find(
                    {
                        "pid": pid,
                        "code": "param_TiWei",
                        "valid": True,
                        "strVal": {"$regex": "俯卧位"},
                        "time": {"$gte": admit, "$lte": discharge},
                    },
                    {"strVal": 1, "time": 1},
                ).sort("time", 1).limit(50))

                if prone_records:
                    result["num_count"] += 1
                    result["num_patients"].append({
                        "pid": pid,
                        "mrn": p.get("mrn", ""),
                        "name": p.get("name", ""),
                        "prone_times": [r["time"] for r in prone_records[:10]],
                        "prone_count": len(prone_records),
                    })

            break
        except Exception:
            continue

    return result


# ============================================================
# ICU-08 组合：分母+分子一次返回
# ============================================================

def get_icu08_data(dept_codes: list, start_date: str, end_date: str,
                   invasive_pf: float = 150.0, noninvasive_pf: float = 200.0,
                   hfnc_flow_min: float = 30.0, peep_min: float = 5.0,
                   time_tolerance_min: int = 60) -> dict:
    """
    ICU-08（中重度ARDS俯卧位实施率）完整三套分母+分子。

    分母三臂：
      有创: 氧疗途径∈{管辅,切辅,管氧,切氧,管文,切文,管高,切高} 且 PEEP≥5 且 P/F<150
      无创: 氧疗途径=无创 且 PEEP≥5 且 P/F≤200
      高流量: 氧疗途径=高流量 且 吸氧流速≥30L/min 且 P/F≤200
    三臂按 pid 去重取并集。

    分子：分母患者住院期间有 param_TiWei 含"俯卧位"记录。

    返回: {den_count, num_count, den_patients, num_patients}
    """
    from datetime import datetime as dt, timedelta
    from bson import ObjectId

    # 有创氧疗途径
    INVASIVE_ROUTES = {"管辅", "切辅", "管氧", "切氧", "管文", "切文", "管高", "切高", "有创"}

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    den_patients = []
    seen_pids = set()

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # Step 1: 取血气 P/F
            all_bga = []
            for coll_name in ["bGATemp", "bGATemp1"]:
                try:
                    bgas = list(db[coll_name].find(
                        {"deptCode": {"$in": dept_codes},
                         "eventExe.startTime": {"$gte": start_dt, "$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)},
                         "bedsides": {"$elemMatch": {"code": {"$in": ["param_bg_P/Fratio", "param_bg_OI", "param_bg_po2"]}, "valid": "valid"}}},
                        {"eventExe.pid": 1, "eventExe.startTime": 1, "bedsides": 1, "mrn": 1},
                    ).sort("eventExe.startTime", 1))
                    all_bga.extend(bgas)
                except Exception:
                    continue

            for bga in all_bga:
                pid = bga["eventExe"]["pid"]
                if pid in seen_pids:
                    continue
                pf_time = bga["eventExe"]["startTime"]
                pf_ratio = None
                pf_ratio = _pf_ratio_from_bedsides(bga.get("bedsides", []))
                if pf_ratio is None:
                    continue

                win = pf_time - timedelta(minutes=time_tolerance_min)

                # PEEP
                peep_doc = db.bedside.find_one(
                    {"pid": pid, "code": "param_vent_peep", "valid": True,
                     "time": {"$gte": win, "$lte": pf_time}},
                    {"strVal": 1}, sort=[("time", -1)])
                if not peep_doc:
                    continue
                try:
                    peep_val = float(peep_doc.get("strVal", "0"))
                except (ValueError, TypeError):
                    continue

                # 氧疗途径
                o2_doc = db.bedside.find_one(
                    {"pid": pid, "code": "param_XiYangTuJing", "valid": True,
                     "time": {"$gte": win, "$lte": pf_time}},
                    {"strVal": 1}, sort=[("time", -1)])
                o2_raw = o2_doc.get("strVal", "") if o2_doc else ""

                # 判定三臂
                arm = None
                routes = _parse_o2_routes(o2_raw)
                o2_invasive, _, _ = is_invasive_by_o2route(o2_raw)

                if o2_invasive and peep_val >= peep_min and pf_ratio < invasive_pf:
                    arm = "有创"
                elif any("无创" in r for r in routes) and peep_val >= peep_min and pf_ratio <= noninvasive_pf:
                    arm = "无创"
                elif any("高流量" in r for r in routes):
                    # 查流速
                    flow_doc = db.bedside.find_one(
                        {"pid": pid, "code": "param_吸氧流速", "valid": True,
                         "time": {"$gte": win, "$lte": pf_time}},
                        {"strVal": 1}, sort=[("time", -1)])
                    flow_val = 0
                    if flow_doc:
                        try:
                            fv = flow_doc.get("strVal", "0")
                            fv = fv.replace("L/min", "").replace("l/min", "").strip()
                            flow_val = float(fv)
                        except (ValueError, TypeError):
                            pass
                    if flow_val >= hfnc_flow_min and pf_ratio <= noninvasive_pf:
                        arm = "高流量"

                if not arm:
                    continue  # 不入任何分母

                # 匹配！查患者信息
                seen_pids.add(pid)
                pat_name = ""
                mrn = bga.get("mrn", "")
                try:
                    pat = db.patient.find_one({"_id": ObjectId(pid)}, {"name": 1, "mrn": 1, "hisPid": 1})
                    if pat:
                        pat_name = pat.get("name", "")
                        if not mrn: mrn = pat.get("mrn", "") or pat.get("hisPid", "")
                except Exception:
                    pass
                den_patients.append({
                    "pid": pid, "mrn": mrn, "name": pat_name,
                    "pf_ratio": pf_ratio, "peep": peep_val,
                    "o2_route": o2_raw, "arm": arm, "flow_val": flow_val if arm == "高流量" else None,
                    "pf_time": pf_time,
                })

            break
        except Exception:
            continue

    # 分子：住院期间俯卧位
    num_result = get_ards_prone_numerator(den_patients, dept_codes)
    return {
        "den_count": len(den_patients),
        "num_count": num_result["num_count"],
        "den_patients": den_patients,
        "num_patients": num_result["num_patients"],
    }


# ============================================================
# ICU-07：DVT预防率 — 从 DataCenter.VI_ICU_ZYYZ 取数
# ============================================================

# ---- 可配置关键词列表 ----

# 药物预防：抗凝药词根（正则 contains，不区分大小写）
DRUG_DVT_KEYWORDS = [
    "肝素", "heparin",           # 肝素类（含依诺肝素/enoxaparin、达肝素/dalteparin、那屈肝素/nadroparin等）
    "磺达肝癸", "fondaparinux",  # 戊聚糖类
    "沙班", "xaban",             # Xa因子抑制剂（利伐沙班/rivaroxaban、阿哌沙班/apixaban等）
    "达比加群", "dabigatran",
    "华法林", "warfarin",
    "比伐芦定", "bivalirudin",
    "阿加曲班", "argatroban",
]

# 封管/冲管排除词（肝素+这些=导管维护,非DVT预防）
FLUSH_EXCLUDE_KEYWORDS = [
    "封管", "冲管", "封管液", "flush", "lock",
    "有创压用", "创压用", "动脉压用",  # 有创血压管路维护
]

# 机械预防关键词
MECH_DVT_KEYWORDS = [
    "间歇充气加压", "IPC",
    "充气加压", "加压泵", "抗栓泵",
    "弹力袜", "压力袜", "梯度压力袜", "抗血栓袜",
    "足底静脉泵", "足底泵", "VFP", "足底脉冲",
]

# 滤器关键词（单独标记，不直接计入分子 — 待质控医生确认）
FILTER_KEYWORDS = [
    "静脉滤器", "滤器植入", "IVC滤器",
]


def get_dvt_prevention_patients(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-07 分子：采取了DVT预防措施的患者。
    数据源：DataCenter.VI_ICU_ZYYZ.orderName（医嘱名称包含匹配）。

    返回: {drug_patients, mech_patients, filter_patients, all_patients}
    每个患者列表: [{pid, mrn, name, matched_orders: [orderName]}]
    """
    from datetime import datetime as dt
    import re

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)

    result = {
        "drug_pids": set(), "mech_pids": set(), "filter_pids": set(),
        "drug_patients": [], "mech_patients": [], "filter_patients": [],
    }

    try:
        db = get_datacenter_db()

        # 构建正则
        drug_pattern = _keyword_regex(DRUG_DVT_KEYWORDS)
        mech_pattern = _keyword_regex(MECH_DVT_KEYWORDS)
        filter_pattern = _keyword_regex(FILTER_KEYWORDS)
        flush_pattern = _keyword_regex(FLUSH_EXCLUDE_KEYWORDS)
        all_pattern = _keyword_regex(DRUG_DVT_KEYWORDS + MECH_DVT_KEYWORDS + FILTER_KEYWORDS)

        # Step 1: 从 VI_ICU_ZYBR 获取指定科室和时间段的住院记录 → {pid: {mrn, name, deptCode}}
        zybr_docs = list(db["VI_ICU_ZYBR"].find(
            {
                "deptCode": {"$in": dept_codes},
                "admitTime": {"$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)},
                "$or": [
                    {"dischargeTime": {"$gte": start_dt}},
                    {"dischargeTime": None},
                    {"dischargeTime": ""},
                ],
            },
            {"pid": 1, "mrn": 1, "name": 1, "deptCode": 1},
        ))
        zybr_by_pid = {d["pid"]: d for d in zybr_docs if d.get("pid")}
        valid_pids = set(zybr_by_pid.keys())
        print(f"[ICU-07] VI_ICU_ZYBR matched {len(valid_pids)} patients in dept={dept_codes}")

        if not valid_pids:
            return result

        # Step 2: 查 VI_ICU_ZYYZ 医嘱（只查这些 pid）
        orders = list(db["VI_ICU_ZYYZ"].find(
            {
                "pid": {"$in": list(valid_pids)},
                "orderName": {"$regex": all_pattern, "$options": "i"},
                "orderTime": {
                    "$gte": start_dt,
                    "$lte": dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59),
                },
                "status": {"$in": EXECUTED_ORDER_STATUSES},
            },
            {"pid": 1, "orderName": 1, "orderTime": 1},
        ).limit(50000))

        # Step 3: 分类匹配
        drug_by_pid = {}
        mech_by_pid = {}
        filter_by_pid = {}

        for o in orders:
            name = o.get("orderName", "")
            pid = o.get("pid", "")
            if not pid or not name:
                continue

            if re.search(drug_pattern, name, re.IGNORECASE):
                if re.search(flush_pattern, name, re.IGNORECASE):
                    continue
                drug_by_pid.setdefault(pid, []).append(name)

            if re.search(mech_pattern, name, re.IGNORECASE):
                mech_by_pid.setdefault(pid, []).append(name)

            if re.search(filter_pattern, name, re.IGNORECASE):
                filter_by_pid.setdefault(pid, []).append(name)

        all_pids = set(drug_by_pid.keys()) | set(mech_by_pid.keys())
        result["drug_pids"] = set(drug_by_pid.keys())
        result["mech_pids"] = set(mech_by_pid.keys())
        result["filter_pids"] = set(filter_by_pid.keys())

        # 通过 mrn 桥接 SmartCare patient 表，取 hisPid 和 name
        dc_mrns = [zybr_by_pid[pid].get("mrn", "") for pid in all_pids if zybr_by_pid.get(pid, {}).get("mrn")]
        smart_pat_map = {}  # mrn → {hisPid, name}
        for db_name in BED_DB_NAMES:
            try:
                smart_db = get_client(db_name)[db_name]
                docs = list(smart_db.patient.find(
                    {"mrn": {"$in": dc_mrns}},
                    {"mrn": 1, "hisPid": 1, "name": 1, "_id": 0},
                ))
                for d in docs:
                    smart_pat_map[d["mrn"]] = {"hisPid": d.get("hisPid", ""), "name": d.get("name", "")}
                if smart_pat_map:
                    break
            except Exception:
                continue

        def build_list(by_pid):
            out = []
            for pid, olist in by_pid.items():
                zybr = zybr_by_pid.get(pid, {})
                mrn = zybr.get("mrn", "")
                sp = smart_pat_map.get(mrn, {})
                out.append({
                    "pid": pid,
                    "patient_id": sp.get("hisPid", mrn),  # 住院号 = hisPid
                    "name": sp.get("name") or zybr.get("name", ""),
                    "matched_orders": olist[:5],
                    "order_count": len(olist),
                })
            return out

        result["drug_patients"] = build_list(drug_by_pid)
        result["mech_patients"] = build_list(mech_by_pid)
        result["filter_patients"] = build_list(filter_by_pid)
        result["all_count"] = len(all_pids)

    except Exception as e:
        print(f"[ICU-07] Error: {e}")

    return result


# ============================================================
# ICU-06：抗菌药物治疗前病原学送检率（治疗/预防三层判定）
# ============================================================

# ---- 可配置阈值常量 ----
FEVER_TEMP = 38.5               # 发热体温阈值 (℃)
WBC_HIGH = 10.0                 # WBC 升高阈值 (×10⁹/L)
WBC_LOW = 4.0                   # WBC 降低阈值 (×10⁹/L)
CRP_HIGH = 10.0                 # CRP 升高阈值 (mg/L)
PCT_HIGH = 0.5                  # PCT 升高阈值 (ng/mL)
INFLAM_WINDOW_H = 24            # 炎症指标时间窗口 (小时, 首剂前后)
PERIOP_PRE_H = 2                # 围术期术前窗口 (小时)
PERIOP_POST_H = 48              # 围术期术后/总疗程阈值 (小时)
SHORT_COURSE_H = 24             # 短疗程总跨度阈值 (小时)
SHORT_COURSE_MAX_DOSES = 2      # 短疗程最多给药次数
AI_CONFIDENCE_THRESHOLD = 0.6   # AI 低置信度阈值
CRP_AS_PATHOGEN = False         # CRP 默认不计入病原学送检

# ---- 治疗目的诊断关键词（A1 信号） ----
TREATMENT_DIAG_KEYWORDS = [
    "肺炎", "脓毒", "感染", "败血", "菌血", "腹膜炎", "脓肿", "化脓",
    "尿路感染", "胆管炎", "脑膜炎", "蜂窝织炎", "感染性休克",
]

# ---- 特殊使用级抗菌药关键词（A7 信号） ----
# ⚠️ configDrug 表无抗菌药物分级字段，只能用关键词硬编码清单
# 覆盖碳青霉烯类、糖肽类、噁唑烷酮类、环脂肽类、多黏菌素类、抗真菌类、四代头孢等
SPECIAL_GRADE_KEYWORDS = [
    # 碳青霉烯类
    "亚胺培南", "美罗培南", "比阿培南", "帕尼培南", "厄他培南",
    # 糖肽类
    "万古霉素", "去甲万古", "替考拉宁",
    # 噁唑烷酮类
    "利奈唑胺",
    # 甘氨酰环素类
    "替加环素",
    # 多黏菌素类
    "多黏菌素", "多粘菌素",
    # 抗真菌类 (三唑/棘白菌素/多烯)
    "两性霉素", "伏立康唑", "泊沙康唑", "卡泊芬净", "米卡芬净",
    # 环脂肽类
    "达托霉素",
    # 四代头孢
    "头孢吡肟",
    # 其他特殊级
    "夫西地酸",
]

# ---- 病原学送检关键词（源A：VI_ICU_ZYYZ, yaoType='检验'） ----
# ⚠️ 不含宽泛"培养"兜底，避免误命中非病原学检验
CULTURE_KEYWORDS_FULL = [
    "血培养", "痰培养", "尿培养", "细菌培养", "真菌培养",
    "分泌物培养", "引流液培养", "胸水培养", "腹水培养", "脑脊液培养",
    "导管培养", "涂片", "革兰染色", "抗酸染色", "G试验", "GM试验", "药敏",
    "内毒素", "隐球菌", "曲霉", "半乳甘露聚糖", "结核",
    "核酸", "微生物", "细菌",
]
PATHOGEN_REGEX = "|".join(CULTURE_KEYWORDS_FULL)

# ---- 检验结果清洗 ----
def _clean_test_value(raw) -> float | None:
    """
    清洗检验结果值。
    - 去除 > < ≥ ≤ 前缀
    - 跳过 "阴性" "未检出" "正常" "未见异常" 等非数值
    - 返回 float 或 None
    """
    if raw is None:
        return None
    s = str(raw).strip()
    non_numeric = {"", "阴性", "未检出", "正常", "未见异常", "-", "—", "无", "弱阳性",
                   "阴性(-)", "阴性（-）", "(-)", "neg", "negative", "Neg"}
    if s in non_numeric:
        return None
    # 去除比较符号 (含组合如 >=, <=, ≥, ≤ 等)
    for ch in (">=", "<=", "≥", "≤", ">", "<", "="):
        s = s.replace(ch, "")
    # 去除常见单位后缀
    for suffix in ("℃", "°C", "mg/L", "ng/mL", "×10⁹/L", "x10⁹/L",
                   "g/L", "mmol/L", "μmol/L", "U/L", "%", "mm/h"):
        if s.endswith(suffix):
            s = s[:-len(suffix)].strip()
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return None


# ---- 炎症指标查询 ----
def get_inflammation_signals(pat_pid: str, pat_hispid: str, first_dose,
                             db_sc, db_dc) -> dict:
    """
    查询首剂±INFLAM_WINDOW_H 内的炎症指标。

    数据源：
      - 体温: SmartCare.bedside, code='param_T', strVal 取数值
      - WBC/CRP/PCT: DataCenter.VI_ICU_EXAM (主表) + VI_ICU_EXAM_ITEM (子表)
        主表 collectTime 为检验时间，子表 itemCode 精确匹配取值。

    ⚠️ 字段陷阱：
      - PCT: 只认 itemCode=='PCT1' 或 itemName=='降钙素原'，itemCode='PCT' 是血小板比容
      - WBC: 只认 itemCode in {'WBC','WBCJS'}，不可用 itemName 模糊（会误命中尿白细胞 NYWBC）

    返回 {fever, fever_val, wbc_high, wbc_low, wbc_val,
           crp_high, crp_val, pct_high, pct_val, has_any_abnormal, details}
    """
    from datetime import timedelta

    window_start = first_dose - timedelta(hours=INFLAM_WINDOW_H)
    window_end = first_dose + timedelta(hours=INFLAM_WINDOW_H)

    result = {
        "fever": False, "fever_val": None,
        "wbc_high": False, "wbc_low": False, "wbc_val": None,
        "crp_high": False, "crp_val": None,
        "pct_high": False, "pct_val": None,
        "has_any_abnormal": False,
        "details": [],
    }

    # ---- 体温 (SmartCare.bedside) ----
    try:
        temp_docs = list(db_sc.bedside.find(
            {"pid": pat_pid, "code": "param_T", "valid": True,
             "time": {"$gte": window_start, "$lte": window_end}},
            {"strVal": 1, "time": 1},
        ).sort("time", -1).limit(5))
        for doc in temp_docs:
            val = _clean_test_value(doc.get("strVal"))
            if val is not None:
                if val >= FEVER_TEMP:
                    result["fever"] = True
                    result["fever_val"] = val
                    result["details"].append(f"体温{val}℃≥{FEVER_TEMP}℃")
                break  # 只取最近一条有效值
    except Exception as e:
        pass  # bedside 不可用则跳过

    # ---- WBC / CRP / PCT (DataCenter.EXAM + EXAM_ITEM) ----
    if pat_hispid and db_dc is not None:
        _query_exam_inflammation(db_dc, pat_hispid, window_start, window_end, result)

    result["has_any_abnormal"] = (
        result["fever"] or result["wbc_high"] or result["wbc_low"]
        or result["crp_high"] or result["pct_high"]
    )
    return result


def _query_exam_inflammation(db_dc, hispid: str, window_start, window_end, result: dict):
    """
    从 DataCenter 查询炎症相关检验指标。
    VI_ICU_EXAM (主表, pid=hisPid, collectTime) + VI_ICU_EXAM_ITEM (子表, itemCode/itemValue)。

    ⚠️ 字段名不确定项（按推测标注，如不匹配需调整）：
      - VI_ICU_EXAM.pid ↔ hisPid
      - VI_ICU_EXAM.examID 或 reportID ↔ VI_ICU_EXAM_ITEM.examID
      - VI_ICU_EXAM.collectTime 为主检验时间
    """
    try:
        # Step 1: 查主表，获取窗口内的检验记录
        exam_docs = list(db_dc["VI_ICU_EXAM"].find(
            {"pid": hispid,
             "collectTime": {"$gte": window_start, "$lte": window_end}},
            {"examID": 1, "reportID": 1, "collectTime": 1},
        ))
        if not exam_docs:
            return

        # 构建 examID 集合 (优先 examID，兜底 reportID)
        exam_ids = []
        exam_time_by_id = {}  # exam_id → collectTime
        for e in exam_docs:
            eid = e.get("examID") or e.get("reportID")
            if eid:
                exam_ids.append(eid)
                exam_time_by_id[str(eid)] = e.get("collectTime")
        if not exam_ids:
            return

        # Step 2: 查子表，精确匹配 itemCode
        WBC_CODES = {"WBC", "WBCJS"}        # 血白细胞 — 绝不可用 itemName 模糊
        CRP_CODES = {"CRP", "sCRP"}          # C反应蛋白
        PCT_CODES = {"PCT1"}                 # ⚠️ 只认 PCT1 — "PCT" 是血小板比容

        target_codes = list(WBC_CODES | CRP_CODES | PCT_CODES)
        items = list(db_dc["VI_ICU_EXAM_ITEM"].find(
            {"examID": {"$in": exam_ids},
             "itemCode": {"$in": target_codes}},
            {"examID": 1, "itemCode": 1, "itemName": 1, "itemValue": 1, "authTime": 1},
        ))

        # Step 3: 逐条判定
        for item in items:
            code = item.get("itemCode", "")
            raw_val = item.get("itemValue")
            val = _clean_test_value(raw_val)
            if val is None:
                continue

            # 时间：优先主表 collectTime，无则子表 authTime
            eid = str(item.get("examID", ""))
            item_time = exam_time_by_id.get(eid) or item.get("authTime")

            if code in WBC_CODES:
                result["wbc_val"] = val
                if val > WBC_HIGH:
                    result["wbc_high"] = True
                    result["details"].append(f"WBC {val}>10×10⁹/L")
                elif val < WBC_LOW:
                    result["wbc_low"] = True
                    result["details"].append(f"WBC {val}<4×10⁹/L")

            elif code in CRP_CODES:
                result["crp_val"] = val
                if val > CRP_HIGH:
                    result["crp_high"] = True
                    result["details"].append(f"CRP {val}>10mg/L")

            elif code in PCT_CODES:
                # 双重保险：itemCode==PCT1 且 itemName 含"降钙素原"才认
                item_name = item.get("itemName", "")
                if "降钙素原" in str(item_name):
                    result["pct_val"] = val
                    if val > PCT_HIGH:
                        result["pct_high"] = True
                        result["details"].append(f"PCT {val}>0.5ng/mL")
                # 纯 itemCode==PCT1 但 itemName 无降钙素原也认（有的系统只存 code）
                elif code == "PCT1" and "血小板" not in str(item_name):
                    result["pct_val"] = val
                    if val > PCT_HIGH:
                        result["pct_high"] = True
                        result["details"].append(f"PCT {val}>0.5ng/mL")

    except Exception:
        pass  # 检验数据不可用则跳过，炎症指标只正向判治疗


# ---- 三层判定：classify_abx_purpose ----
def classify_abx_purpose(pat_doc: dict, first_dose, total_doses: int,
                         total_hours: float, drug_names: list,
                         abx_code_count: int = 0,
                         db_sc=None, db_dc=None,
                         inflammation_signals: dict | None = None) -> dict:
    """
    治疗 vs 预防三层漏斗判定。

    参数：
      pat_doc         - SmartCare.patient 文档 (含 clinicalDiagnosis, patientOperations, hisPid, _id)
      first_dose      - 首剂抗菌药时间 (datetime)
      total_doses     - 总给药次数
      total_hours     - 总疗程跨度 (小时)
      drug_names      - 抗菌药名称列表
      abx_code_count  - 不同抗菌药 code 去重计数 (≥2 即联合用药 A6)
      db_sc, db_dc    - SmartCare / DataCenter 数据库句柄
      inflammation_signals - 预查询的炎症指标 (避免重复查库)

    返回 {purpose: "治疗性"|"预防性", decided_by: "rule"|"ai"|"fallback",
           reason: str, confidence: float, need_review: bool}
    """
    from datetime import timedelta

    hispid = pat_doc.get("hisPid", "")
    pat_pid = str(pat_doc.get("_id", ""))
    diagnosis = pat_doc.get("clinicalDiagnosis", "") or ""
    operations = pat_doc.get("patientOperations") or []

    # ---- 第一层 A: 治疗信号（任一命中即判治疗） ----

    # A1: 临床诊断命中治疗关键词
    for kw in TREATMENT_DIAG_KEYWORDS:
        if kw in diagnosis:
            return {"purpose": "治疗性", "decided_by": "rule",
                    "reason": f"A1-诊断含「{kw}」", "confidence": 1.0,
                    "need_review": False}

    # A2–A5: 炎症指标（预查询结果或现场查询）
    if inflammation_signals is None:
        inflammation_signals = get_inflammation_signals(
            pat_pid, hispid, first_dose, db_sc, db_dc)

    inflam = inflammation_signals

    # A2: 体温 ≥ 38.5℃
    if inflam.get("fever"):
        return {"purpose": "治疗性", "decided_by": "rule",
                "reason": f"A2-首剂±{INFLAM_WINDOW_H}h体温{inflam.get('fever_val')}℃≥{FEVER_TEMP}℃",
                "confidence": 1.0, "need_review": False}

    # A3: WBC 异常 (>10 或 <4)
    if inflam.get("wbc_high"):
        return {"purpose": "治疗性", "decided_by": "rule",
                "reason": f"A3-WBC {inflam.get('wbc_val')}>10×10⁹/L",
                "confidence": 1.0, "need_review": False}
    if inflam.get("wbc_low"):
        return {"purpose": "治疗性", "decided_by": "rule",
                "reason": f"A3-WBC {inflam.get('wbc_val')}<4×10⁹/L",
                "confidence": 1.0, "need_review": False}

    # A4: CRP 升高 >10mg/L
    if inflam.get("crp_high"):
        return {"purpose": "治疗性", "decided_by": "rule",
                "reason": f"A4-CRP {inflam.get('crp_val')}>10mg/L",
                "confidence": 1.0, "need_review": False}

    # A5: PCT 升高 >0.5ng/mL (仅真降钙素原 PCT1)
    if inflam.get("pct_high"):
        return {"purpose": "治疗性", "decided_by": "rule",
                "reason": f"A5-PCT {inflam.get('pct_val')}>0.5ng/mL",
                "confidence": 1.0, "need_review": False}

    # A6: 联合用药（≥2 种不同抗菌药 code）
    if abx_code_count >= 2:
        return {"purpose": "治疗性", "decided_by": "rule",
                "reason": f"A6-联合用药({abx_code_count}种)",
                "confidence": 1.0, "need_review": False}

    # A7: 特殊使用级抗菌药
    for dname in drug_names:
        for kw in SPECIAL_GRADE_KEYWORDS:
            if kw in dname:
                return {"purpose": "治疗性", "decided_by": "rule",
                        "reason": f"A7-特殊级抗菌药:{kw}",
                        "confidence": 1.0, "need_review": False}

    # ---- 第二层 B: 围术期预防 ----
    # 首剂在术前2h~术后 + 总疗程≤48h
    for op in operations:
        op_start = op.get("startTime") or op.get("opTime") or op.get("surgeryTime")
        op_end = op.get("endTime") or op.get("opEndTime")
        if op_start is None:
            continue
        # 术前 2h 窗口
        pre_op = op_start - timedelta(hours=PERIOP_PRE_H)
        # 术后窗口（手术结束时间 or 手术开始+24h）— 用于判断"围术期"范围
        post_op = op_end if op_end else op_start

        if pre_op <= first_dose <= post_op and total_hours <= PERIOP_POST_H:
            return {"purpose": "预防性", "decided_by": "rule",
                    "reason": f"B-围术期预防(术前{PERIOP_PRE_H}h~术后,疗程{total_hours:.0f}h≤{PERIOP_POST_H}h)",
                    "confidence": 1.0, "need_review": False}

    # ---- 第二层 C: 短疗程预防 ----
    # 无 A 信号 + 总跨度≤24h + 次数≤2
    if total_hours <= SHORT_COURSE_H and total_doses <= SHORT_COURSE_MAX_DOSES:
        return {"purpose": "预防性", "decided_by": "rule",
                "reason": f"C-短疗程(跨度{total_hours:.0f}h≤{SHORT_COURSE_H}h, {total_doses}次≤{SHORT_COURSE_MAX_DOSES})",
                "confidence": 1.0, "need_review": False}

    # ---- 第三层: 灰区 AI ----
    # A1-A7 + B + C 均不命中 → AI 判定（结果缓存，不会重复调用）
    try:
        from ai_analyzer import classify_abx_with_ai
        diag = diagnosis[:200] if diagnosis else ""
        ops_summary = ",".join(
            o.get("name", o.get("code", ""))[:40] for o in operations[:3]
        ) if operations else "无"
        drug_summary = ",".join(d[:40] for d in drug_names[:5])
        inflam_summary = ";".join(inflam.get("details", [])) or "无异常"

        ai_result = classify_abx_with_ai({
            "hisPid": hispid,
            "diagnosis": diag,
            "surgery": ops_summary,
            "antibiotics": drug_summary,
            "course_hours": round(total_hours, 1),
            "dose_count": total_doses,
            "inflammation": inflam_summary,
        })
        if ai_result:
            return {
                "purpose": ai_result.get("purpose") or "未判定",
                "decided_by": ai_result.get("by", "ai"),
                "reason": ai_result.get("reason", ""),
                "confidence": ai_result.get("confidence", 0.0),
                "evaluated": ai_result.get("evaluated", ai_result.get("by") != "fallback"),
                "need_review": ai_result.get("need_review", False),
            }
    except Exception:
        pass

    # AI 不可用兜底（仍进 low_confidence 人工复核）
    return {"purpose": "未判定", "decided_by": "fallback",
            "reason": f"规则+AI均不可用兜底(疗程{total_hours:.0f}h/{total_doses}次/{','.join(drug_names[:2])[:30]})",
            "confidence": 0.0, "evaluated": False, "need_review": True}


# ---- 批量预查炎症指标（一次查询覆盖全部患者） ----
def _batch_get_inflammation(abx_by_pid: dict, pat_by_pid: dict,
                            db_sc, db_dc) -> dict:
    """
    批量查询所有候选患者的炎症指标，仅 3~4 次 MongoDB 往返。

    返回: {pid: inflammation_signals_dict}
    """
    from datetime import timedelta

    result = {}
    if not abx_by_pid:
        return result

    # 收集所有患者信息
    pid_hispid_map = {}   # pid → hispid
    pid_first_dose = {}   # pid → first_dose
    for pid in abx_by_pid:
        p = pat_by_pid.get(pid)
        if p:
            pid_hispid_map[pid] = p.get("hisPid", "")
            pid_first_dose[pid] = abx_by_pid[pid]["first_time"]

    if not pid_first_dose:
        return result

    # 计算全局时间窗口（覆盖所有患者）
    all_times = list(pid_first_dose.values())
    global_min = min(all_times) - timedelta(hours=INFLAM_WINDOW_H)
    global_max = max(all_times) + timedelta(hours=INFLAM_WINDOW_H)

    # 初始化空结果
    for pid in abx_by_pid:
        result[pid] = {
            "fever": False, "fever_val": None,
            "wbc_high": False, "wbc_low": False, "wbc_val": None,
            "crp_high": False, "crp_val": None,
            "pct_high": False, "pct_val": None,
            "has_any_abnormal": False, "details": [],
        }

    # ---- Query 1: 批量查 bedside 体温 (SmartCare) — 超时保护 ----
    all_pids = list(pid_first_dose.keys())
    try:
        temp_docs = list(db_sc.bedside.find(
            {"pid": {"$in": all_pids}, "code": "param_T", "valid": True,
             "time": {"$gte": global_min, "$lte": global_max}},
            {"pid": 1, "strVal": 1, "time": 1},
        ).sort("time", -1).max_time_ms(5000))  # 单次查询最多 5 秒

        # 按 pid 分组，取窗口内最高体温
        temp_by_pid = {}
        for doc in temp_docs:
            pid = doc.get("pid", "")
            t = doc.get("time")
            if pid not in pid_first_dose:
                continue
            fd = pid_first_dose[pid]
            if t is None or not (fd - timedelta(hours=INFLAM_WINDOW_H) <= t <= fd + timedelta(hours=INFLAM_WINDOW_H)):
                continue
            val = _clean_test_value(doc.get("strVal"))
            if val is not None:
                if pid not in temp_by_pid or val > temp_by_pid[pid]:
                    temp_by_pid[pid] = val

        for pid, val in temp_by_pid.items():
            if val >= FEVER_TEMP:
                result[pid]["fever"] = True
                result[pid]["fever_val"] = val
                result[pid]["details"].append(f"体温{val}℃≥{FEVER_TEMP}℃")
                result[pid]["has_any_abnormal"] = True
    except Exception:
        pass

    # ---- Query 2-3: 批量查 DataCenter 检验指标 ----
    if db_dc is not None:
        hispids = [h for h in pid_hispid_map.values() if h]
        if hispids:
            try:
                _batch_query_exam_inflammation(
                    db_dc, hispids, pid_hispid_map, pid_first_dose, result)
            except Exception:
                pass

    return result


def _batch_query_exam_inflammation(db_dc, hispids: list,
                                   pid_hispid_map: dict,
                                   pid_first_dose: dict,
                                   result: dict):
    """
    批量查询 DataCenter 检验指标。
    Query 2: VI_ICU_EXAM (主表)
    Query 3: VI_ICU_EXAM_ITEM (子表)
    """
    from datetime import timedelta

    # 计算全局窗口
    all_times = list(pid_first_dose.values())
    global_min = min(all_times) - timedelta(hours=INFLAM_WINDOW_H)
    global_max = max(all_times) + timedelta(hours=INFLAM_WINDOW_H)

    # hispid → pid 反向映射
    hispid_to_pid = {v: k for k, v in pid_hispid_map.items()}

    # Query 2: 批量查主表 — 超时保护 + 结果上限
    try:
        exam_docs = list(db_dc["VI_ICU_EXAM"].find(
            {"pid": {"$in": hispids},
             "collectTime": {"$gte": global_min, "$lte": global_max}},
            {"pid": 1, "examID": 1, "reportID": 1, "collectTime": 1},
        ).max_time_ms(8000).limit(20000))
    except Exception:
        return  # 检验数据不可用则降级，炎症指标只正向判治疗
    if not exam_docs:
        return

    # 构建映射
    exam_ids = []
    exam_info = {}  # exam_id_str → {collectTime, hispid}
    for e in exam_docs:
        eid = e.get("examID") or e.get("reportID")
        if eid:
            eid_str = str(eid)
            exam_ids.append(eid)
            exam_info[eid_str] = {
                "collectTime": e.get("collectTime"),
                "hispid": e.get("pid", ""),
            }

    if not exam_ids:
        return

    # Query 3: 批量查子表
    WBC_CODES = {"WBC", "WBCJS"}
    CRP_CODES = {"CRP", "sCRP"}
    PCT_CODES = {"PCT1"}
    target_codes = list(WBC_CODES | CRP_CODES | PCT_CODES)

    items = list(db_dc["VI_ICU_EXAM_ITEM"].find(
        {"examID": {"$in": exam_ids},
         "itemCode": {"$in": target_codes}},
        {"examID": 1, "itemCode": 1, "itemName": 1, "itemValue": 1, "authTime": 1},
    ).max_time_ms(10000).limit(50000))

    # 按 (pid, itemCode) 分组，取窗口内最异常值
    for item in items:
        code = item.get("itemCode", "")
        raw_val = item.get("itemValue")
        val = _clean_test_value(raw_val)
        if val is None:
            continue

        eid_str = str(item.get("examID", ""))
        info = exam_info.get(eid_str)
        if not info:
            continue

        hispid = info.get("hispid", "")
        pid = hispid_to_pid.get(hispid)
        if pid not in pid_first_dose:
            continue

        # 时间窗口校验
        item_time = info.get("collectTime") or item.get("authTime")
        fd = pid_first_dose[pid]
        if item_time and not (fd - timedelta(hours=INFLAM_WINDOW_H) <= item_time <= fd + timedelta(hours=INFLAM_WINDOW_H)):
            continue

        res = result[pid]

        if code in WBC_CODES:
            res["wbc_val"] = val
            if val > WBC_HIGH:
                res["wbc_high"] = True
                res["has_any_abnormal"] = True
                res["details"].append(f"WBC {val}>10×10⁹/L")
            elif val < WBC_LOW:
                res["wbc_low"] = True
                res["has_any_abnormal"] = True
                res["details"].append(f"WBC {val}<4×10⁹/L")

        elif code in CRP_CODES:
            res["crp_val"] = val
            if val > CRP_HIGH:
                res["crp_high"] = True
                res["has_any_abnormal"] = True
                res["details"].append(f"CRP {val}>10mg/L")

        elif code in PCT_CODES:
            item_name = item.get("itemName", "")
            if "降钙素原" in str(item_name) or ("血小板" not in str(item_name) and code == "PCT1"):
                res["pct_val"] = val
                if val > PCT_HIGH:
                    res["pct_high"] = True
                    res["has_any_abnormal"] = True
                    res["details"].append(f"PCT {val}>0.5ng/mL")


# ---- ICU-06 主取数函数 ----
def get_icu06_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-06：抗菌药物治疗前病原学送检率。

    分母：统计期内本科室以治疗为目的用抗菌药的患者（按人数去重）。
          - 抗菌药：configDrug.classification=='抗生素' 的 code 集合
          - 治疗目的：三层漏斗判定 (A 治疗信号 → B/C 预防 → AI 灰区)
          - 预防性使用剔除出分母

    分子：分母中首剂抗菌药给药前完成病原学送检的患者（送检时间 ≤ 首剂时间）。
          - 源A：DataCenter.VI_ICU_ZYYZ, yaoType='检验', orderName 含培养类关键词
          - 首剂时间回溯全程（含入 ICU 前），不限统计窗口
          - 时间用 orderTime

    跨库对齐：SmartCare patient.hisPid ↔ DataCenter VI_ICU_ZYYZ.pid

    返回：{den_count, num_count, den_patients, num_patients,
           excluded_prophylaxis, low_confidence}
    """
    from datetime import datetime as dt, timedelta

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)

    result = {
        "den_count": 0, "num_count": 0,
        "den_patients": [], "num_patients": [],
        "excluded_prophylaxis": [],
        "low_confidence": [],
    }

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # ---- 1. 取抗生素 drug codes (configDrug.classification='抗生素') ----
            abx_codes = [d["code"] for d in db.configDrug.find(
                {"classification": "抗生素"}, {"code": 1}
            )]
            if not abx_codes:
                continue

            # ---- 2. 在科患者 (统计期内在 ICU 的患者) ----
            patients = list(db.patient.find(
                {"deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"},
                 "icuAdmissionTime": {"$lte": end_dt_wide},
                 "$or": [{"icuDischargeTime": {"$gte": start_dt}}, {"icuDischargeTime": None},
                         {"icuDischargeTime": {"$exists": False}}]},
                {"_id": 1, "hisPid": 1, "mrn": 1, "name": 1,
                 "clinicalDiagnosis": 1, "patientOperations": 1},
            ))
            pid_set = {str(p["_id"]) for p in patients}
            pat_by_pid = {str(p["_id"]): p for p in patients}
            if not pid_set:
                continue

            # ---- 3. 分母候选：drugExe 统计期内有抗菌药执行记录 ----
            abx_docs = list(db.drugExe.find(
                {"pid": {"$in": list(pid_set)}, "status": "finished",
                 "drugList.code": {"$in": abx_codes},
                 "startTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                {"pid": 1, "startTime": 1, "drugList.code": 1, "drugList.name": 1},
            ).sort("startTime", 1))

            if not abx_docs:
                continue

            # 按 pid 聚合首剂时间、总次数、总跨度、用药名称
            abx_by_pid = {}  # pid → {first_time, last_time, doses, drug_names}
            for d in abx_docs:
                pid = d.get("pid", "")
                t = d.get("startTime")
                if not pid or not t:
                    continue
                if pid not in abx_by_pid:
                    abx_by_pid[pid] = {"first_time": t, "last_time": t, "doses": 0,
                                       "drug_names": set(), "drug_codes": set()}
                entry = abx_by_pid[pid]
                if t < entry["first_time"]:
                    entry["first_time"] = t
                if t > entry["last_time"]:
                    entry["last_time"] = t
                entry["doses"] += 1
                for dl in d.get("drugList", []):
                    if dl.get("code") in abx_codes:
                        entry["drug_names"].add(dl.get("name", "")[:60])
                        entry["drug_codes"].add(dl.get("code"))

            # 回溯全程首剂：对每个候选患者，查统计期前的 drugExe 找真正首剂
            for pid in list(abx_by_pid.keys()):
                earliest = abx_by_pid[pid]["first_time"]
                earlier = list(db.drugExe.find(
                    {"pid": pid, "status": "finished",
                     "drugList.code": {"$in": abx_codes},
                     "startTime": {"$lt": earliest}},
                    {"startTime": 1, "drugList.code": 1, "drugList.name": 1},
                ).sort("startTime", 1).limit(1))
                if earlier:
                    abx_by_pid[pid]["first_time"] = earlier[0]["startTime"]
                    for dl in earlier[0].get("drugList", []):
                        if dl.get("code") in abx_codes:
                            abx_by_pid[pid]["drug_names"].add(dl.get("name", "")[:60])
                            abx_by_pid[pid]["drug_codes"].add(dl.get("code"))

            # ---- 4. 连接 DataCenter ----
            dc_db = None
            try:
                dc_db = get_datacenter_db()
            except Exception:
                pass

            empty_inflam = {"fever": False, "fever_val": None,
                           "wbc_high": False, "wbc_low": False, "wbc_val": None,
                           "crp_high": False, "crp_val": None,
                           "pct_high": False, "pct_val": None,
                           "has_any_abnormal": False, "details": []}

            # ---- 5. Pass 1: A1 诊断关键词 (纯内存, 零DB查询) ----
            den_patients = []
            excluded_prophylaxis = []
            low_confidence = []
            need_inflam_pids = set()  # A1 未命中, 需炎症查询

            for pid, info in abx_by_pid.items():
                p = pat_by_pid.get(pid)
                if not p:
                    continue
                diagnosis = p.get("clinicalDiagnosis", "") or ""
                a1_hit = any(kw in diagnosis for kw in TREATMENT_DIAG_KEYWORDS)
                if not a1_hit:
                    need_inflam_pids.add(pid)

            # ---- 5b. Pass 2: 批量查炎症 (仅 A1 未命中者) ----
            inflam_cache = {}
            if need_inflam_pids:
                need_abx = {pid: abx_by_pid[pid] for pid in need_inflam_pids}
                need_pat = {pid: pat_by_pid[pid] for pid in need_inflam_pids
                           if pid in pat_by_pid}
                inflam_cache = _batch_get_inflammation(need_abx, need_pat, db, dc_db)

            # ---- 5c. Pass 3: 逐患者 classify ----
            for pid, info in abx_by_pid.items():
                p = pat_by_pid.get(pid)
                if not p:
                    continue

                first_dose = info["first_time"]
                total_doses = info["doses"]
                total_hours = (info["last_time"] - info["first_time"]).total_seconds() / 3600.0
                drug_names = list(info["drug_names"])[:10]
                abx_code_count = len(info.get("drug_codes", set()))
                hispid = p.get("hisPid", "")
                inflam = inflam_cache.get(pid, empty_inflam)

                classification = classify_abx_purpose(
                    p, first_dose, total_doses, total_hours, drug_names,
                    abx_code_count=abx_code_count,
                    db_sc=None, db_dc=None,  # 炎症已批量预查，不放句柄防逐条查库
                    inflammation_signals=inflam,
                )

                pat_entry = {
                    "pid": pid,
                    "mrn": p.get("mrn", "") or hispid,
                    "name": p.get("name", ""),
                    "patient_id": hispid,
                    "abx_time": first_dose,
                    "abx_drug": ", ".join(drug_names[:3]),
                    "total_doses": total_doses,
                    "total_hours": round(total_hours, 1),
                    "purpose": classification["purpose"],
                    "decided_by": classification["decided_by"],
                    "reason": classification["reason"],
                    "confidence": classification.get("confidence", 1.0),
                    "evaluated": classification.get("evaluated", classification.get("decided_by") != "fallback"),
                    "need_review": classification.get("need_review", False),
                    "inflammation": inflam.get("details", []),
                }

                if classification.get("decided_by") == "fallback":
                    low_confidence.append(pat_entry)
                    continue

                if classification["purpose"] == "治疗性":
                    den_patients.append(pat_entry)
                else:
                    excluded_prophylaxis.append(pat_entry)

                # 低置信度 / fallback / need_review → 待人工复核
                if (classification.get("need_review")
                        or classification.get("decided_by") == "fallback"
                        or (classification.get("decided_by") == "ai"
                            and classification.get("confidence", 0) < AI_CONFIDENCE_THRESHOLD)):
                    low_confidence.append(pat_entry)

            result["den_count"] = len(den_patients)
            result["den_patients"] = den_patients
            result["excluded_prophylaxis"] = excluded_prophylaxis
            result["low_confidence"] = low_confidence

            if not den_patients:
                continue

            den_pids = {p["pid"] for p in den_patients}

            # ---- 6. 分子：病原学送检 (源A: VI_ICU_ZYYZ) ----
            # hisPid 映射
            smart_pid_by_hispid = {}
            for pid in den_pids:
                p = pat_by_pid.get(pid)
                if p and p.get("hisPid"):
                    smart_pid_by_hispid[p["hisPid"]] = pid

            test_time = {}   # pid → earliest test time
            test_detail = {} # pid → {time, source, name}

            if dc_db is not None and smart_pid_by_hispid:
                hispids = list(smart_pid_by_hispid.keys())
                # 源A: VI_ICU_ZYYZ (培养类医嘱, yaoType='检验')
                culture_orders = list(dc_db["VI_ICU_ZYYZ"].find(
                    {"pid": {"$in": hispids}, "status": {"$in": EXECUTED_ORDER_STATUSES},
                     "yaoType": {"$in": LAB_ORDER_TYPES},
                     "orderName": {"$regex": _keyword_regex(CULTURE_KEYWORDS_FULL), "$options": "i"},
                     "orderTime": {"$lte": end_dt_wide}},  # 回溯全程，时间上限宽松
                    {"pid": 1, "orderTime": 1, "orderName": 1},
                ).sort("orderTime", 1))

                for o in culture_orders:
                    hp = o.get("pid", "")
                    t = o.get("orderTime")
                    spid = smart_pid_by_hispid.get(hp)
                    if spid and t and (spid not in test_time or t < test_time[spid]):
                        test_time[spid] = t
                        test_detail[spid] = {
                            "time": t, "source": "检验医嘱",
                            "name": o.get("orderName", "")[:80],
                        }

            # ---- 7. 计算分子：送检时间 ≤ 首剂时间 ----
            num_pids = set()
            for p in den_patients:
                pid = p["pid"]
                tt = test_time.get(pid)
                first_dose_t = abx_by_pid.get(pid, {}).get("first_time")
                if tt and first_dose_t and tt <= first_dose_t:
                    num_pids.add(pid)

            result["num_count"] = min(len(num_pids), result["den_count"])

            result["num_patients"] = [
                {"pid": pid,
                 "mrn": pat_by_pid[pid].get("mrn", "") or pat_by_pid[pid].get("hisPid", ""),
                 "name": pat_by_pid[pid].get("name", ""),
                 "patient_id": pat_by_pid[pid].get("hisPid", ""),
                 "test_time": test_detail.get(pid, {}).get("time"),
                 "test_source": test_detail.get(pid, {}).get("source", ""),
                 "test_name": test_detail.get(pid, {}).get("name", ""),
                 "abx_time": abx_by_pid.get(pid, {}).get("first_time"),
                 }
                for pid in num_pids
            ]

            break  # 拿到数据即退出库名循环

        except Exception as e:
            print(f"[ICU-06] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-09：镇痛评估率
# ============================================================

# ---- 镇痛评估量表白名单 ----
# bedside: pain-related codes (strVal 直接存评分结果如 CPOT-8)
BEDSIDE_PAIN_CODES = {"param_tengTong_score", "param_painscore_nicu_newborn"}

# bedside strVal 合规镇痛量表前缀白名单（提取 - 之前的部分）
# CPOT/NRS/BPS/VAS 为规范镇痛评估工具；其他前缀（如FRS/RASS等）非镇痛，已排除
PAIN_SCALE_PREFIXES = {"CPOT", "NRS", "BPS", "VAS", "FLACC", "PAIN"}

# score: 合规镇痛评估量表 scoreType
# ⚠️ nrs2002 / nrs2002Score 是营养风险筛查 NRS-2002，非镇痛评估，已排除
SCORE_PAIN_TYPES = {
    "bps", "cpotScore", "cpotScoreV2", "nrsScore",
    "painScore", "newBornPain", "xinShengErTengTong",
}

PAIN_SCALE_CN = {
    "BPS": "行为疼痛量表(BPS)",
    "CPOT": "重症监护疼痛观察工具(CPOT)",
    "FLACC": "FLACC疼痛评估量表",
    "NRS": "数字疼痛评分(NRS)",
    "PAIN": "疼痛评分",
    "VAS": "视觉模拟疼痛评分(VAS)",
    "bps": "行为疼痛量表(BPS)",
    "cpotScore": "重症监护疼痛观察工具(CPOT)",
    "cpotScoreV2": "重症监护疼痛观察工具(CPOT)",
    "nrsScore": "数字疼痛评分(NRS)",
    "painScore": "疼痛评分",
    "newBornPain": "新生儿疼痛评分",
    "xinShengErTengTong": "新生儿疼痛评分",
}

SEDATION_SCALE_CN = {
    "RASS": "Richmond躁动-镇静评分(RASS)",
    "rass": "Richmond躁动-镇静评分(RASS)",
}


def _split_scale_value(raw):
    text = str(raw or "").strip()
    if not text:
        return "", ""
    if "-" in text:
        name, value = text.split("-", 1)
        return name.strip(), value.strip()
    return text, ""


def _score_total(doc):
    for key in ("total", "score", "value", "fVal", "iVal", "strVal"):
        val = doc.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return ""


def get_icu09_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-09：镇痛评估率。

    分母 = 统计期内本科室 ICU 患者总人数（按 _id 去重，无排除）。
    分子 = 分母中住 ICU 期间进行过 ≥1 次镇痛评估的患者数。

    分子源 A（优先）：bedside 表，code ∈ BEDSIDE_PAIN_CODES 且 valid=True。
          命中患者不再回查源 B。
    分子源 B（兜底）：score 表，scoreType ∈ SCORE_PAIN_TYPES 且 valid=True。
          仅对源 A 未命中的患者补判。

    关联键：bedside.pid / score.pid ↔ str(patient._id)
      ⚠️ patient._id 是 ObjectId，bedside.pid/score.pid 是字符串，
         匹配时统一用 str(patient._id)。

    返回：{den_count, num_count, den_patients, num_patients}
    """
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)

    result = {"den_count": 0, "num_count": 0,
              "den_patients": [], "num_patients": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # ---- 1. 分母：在科患者 ----
            patients = list(db.patient.find(
                {"deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"},
                 "icuAdmissionTime": {"$lte": end_dt_wide},
                 "$or": [{"icuDischargeTime": {"$gte": start_dt}},
                         {"icuDischargeTime": None},
                         {"icuDischargeTime": {"$exists": False}}]},
                {"_id": 1, "hisPid": 1, "mrn": 1, "name": 1, "hisBed": 1,
                 "icuAdmissionTime": 1, "icuDischargeTime": 1},
            ))
            if not patients:
                continue

            # pid 映射：ObjectId → str (统一为字符串用于关联)
            den_pids_obj = set()
            pat_by_strpid = {}
            for p in patients:
                oid = p["_id"]
                spid = str(oid)
                den_pids_obj.add(spid)
                pat_by_strpid[spid] = p

            result["den_count"] = len(den_pids_obj)
            if not den_pids_obj:
                continue

            # ---- 2. 分子源 A：bedside 批量查 ----
            # 一次性查出所有分母患者中、命中镇痛 code 的 distinct pid
            den_pids_list = list(den_pids_obj)
            a_pids = set()
            a_detail = {}  # strpid → {scale_name, time}

            try:
                # 批量查 bedside，只取需要的字段
                bedside_docs = list(db.bedside.find(
                    {"pid": {"$in": den_pids_list},
                     "code": {"$in": list(BEDSIDE_PAIN_CODES)},
                     "valid": True,
                     "time": {"$gte": start_dt, "$lte": end_dt_wide}},
                    {"pid": 1, "strVal": 1, "history": 1, "time": 1},
                ).max_time_ms(10000).limit(100000))

                for doc in bedside_docs:
                    spid = doc.get("pid", "")
                    if spid not in den_pids_obj:
                        continue

                    # 时间窗口：评估必须在本次 ICU 住院期间
                    p = pat_by_strpid.get(spid)
                    at = doc.get("time")
                    if p and at:
                        admit = p.get("icuAdmissionTime")
                        discharge = p.get("icuDischargeTime") or end_dt_wide
                        if at < admit or at > discharge:
                            continue

                    # 取评分值：优先 strVal，无则 history[].desc
                    score_val = (doc.get("strVal") or "").strip()
                    if not score_val:
                        hist = doc.get("history") or []
                        if hist:
                            score_val = (hist[0].get("desc") or "").strip()

                    # 前缀白名单校验：仅 CPOT/NRS/BPS/VAS/FLACC/PAIN 等合规量表
                    if score_val:
                        prefix, score_num = _split_scale_value(score_val)
                        if prefix not in PAIN_SCALE_PREFIXES:
                            continue  # 非镇痛量表脏值，跳过

                    if score_val:
                        if spid not in a_pids:
                            a_pids.add(spid)
                            a_detail[spid] = {
                                "source": "床旁评估记录",
                                "scale": PAIN_SCALE_CN.get(prefix, prefix),
                                "score_value": score_num,
                                "time": doc.get("time"),
                            }
            except Exception as e:
                print(f"[ICU-09] bedside query error: {e}")

            # ---- 3. 分子源 B：score 补判（仅 A 未命中者） ----
            b_pids = set()
            b_detail = {}  # strpid → {scale_name, time}

            need_b = [spid for spid in den_pids_list if spid not in a_pids]
            if need_b:
                try:
                    score_docs = list(db.score.find(
                        {"pid": {"$in": need_b},
                         "scoreType": {"$in": list(SCORE_PAIN_TYPES)},
                         "valid": True,
                         "time": {"$gte": start_dt, "$lte": end_dt_wide}},
                        {"pid": 1, "scoreType": 1, "total": 1, "score": 1,
                         "value": 1, "fVal": 1, "iVal": 1, "strVal": 1, "time": 1},
                    ).max_time_ms(10000).limit(50000))

                    for doc in score_docs:
                        spid = doc.get("pid", "")
                        if spid not in den_pids_obj:
                            continue
                        # 时间窗口
                        p = pat_by_strpid.get(spid)
                        at = doc.get("time")
                        if p and at:
                            admit = p.get("icuAdmissionTime")
                            discharge = p.get("icuDischargeTime") or end_dt_wide
                            if at < admit or at > discharge:
                                continue
                        stype = doc.get("scoreType", "painScore")
                        if spid not in b_pids:
                            b_pids.add(spid)
                            b_detail[spid] = {
                                "source": "量表评分记录",
                                "scale": PAIN_SCALE_CN.get(stype, stype),
                                "score_value": _score_total(doc),
                                "time": doc.get("time"),
                            }
                except Exception as e:
                    print(f"[ICU-09] score query error: {e}")

            # ---- 4. 分子 = A ∪ B ----
            num_pids = a_pids | b_pids
            result["num_count"] = min(len(num_pids), result["den_count"])

            # ---- 5. 构建明细 ----
            result["den_patients"] = [
                {"pid": spid,
                 "mrn": pat_by_strpid[spid].get("mrn", "") or pat_by_strpid[spid].get("hisPid", ""),
                 "name": pat_by_strpid[spid].get("name", ""),
                 "patient_id": pat_by_strpid[spid].get("hisPid", ""),
                 "hisBed": pat_by_strpid[spid].get("hisBed", ""),
                 "icu_admit": pat_by_strpid[spid].get("icuAdmissionTime"),
                 }
                for spid in den_pids_obj
            ]

            result["num_patients"] = []
            for spid in num_pids:
                p = pat_by_strpid[spid]
                detail = a_detail.get(spid) or b_detail.get(spid) or {}
                result["num_patients"].append({
                    "pid": spid,
                    "mrn": p.get("mrn", "") or p.get("hisPid", ""),
                    "name": p.get("name", ""),
                    "patient_id": p.get("hisPid", ""),
                    "assess_source": detail.get("source", ""),
                    "assess_scale": detail.get("scale", ""),
                    "assess_value": detail.get("score_value", ""),
                    "assess_time": detail.get("time"),
                })

            break  # 拿到数据即退出库名循环

        except Exception as e:
            print(f"[ICU-09] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-10：镇静评估率
# ============================================================

# bedside: RASS 镇静评分 code
BEDSIDE_SEDATION_CODE = "param_score_rass_obs"

# score: 镇静评估量表 scoreType
SCORE_SEDATION_TYPES = {"rass"}


def get_icu10_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-10：镇静评估率。

    分母 = 统计期内本科室 ICU 患者总人数（按 _id 去重，无排除）。
    分子 = 分母中住 ICU 期间进行过 ≥1 次镇静评估（RASS）的患者数。

    分子源 A（优先）：bedside 表，code='param_score_rass_obs' 且 valid=True。
    分子源 B（兜底）：score 表，scoreType='rass' 且 valid=True。
          仅对源 A 未命中的患者补判。

    关联键：bedside.pid / score.pid ↔ str(patient._id)

    返回：{den_count, num_count, den_patients, num_patients}
    """
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)

    result = {"den_count": 0, "num_count": 0,
              "den_patients": [], "num_patients": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # ---- 1. 分母 ----
            patients = list(db.patient.find(
                {"deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"},
                 "icuAdmissionTime": {"$lte": end_dt_wide},
                 "$or": [{"icuDischargeTime": {"$gte": start_dt}},
                         {"icuDischargeTime": None},
                         {"icuDischargeTime": {"$exists": False}}]},
                {"_id": 1, "hisPid": 1, "mrn": 1, "name": 1, "hisBed": 1,
                 "icuAdmissionTime": 1, "icuDischargeTime": 1},
            ))
            if not patients:
                continue

            den_pids_obj = set()
            pat_by_strpid = {}
            for p in patients:
                spid = str(p["_id"])
                den_pids_obj.add(spid)
                pat_by_strpid[spid] = p

            result["den_count"] = len(den_pids_obj)
            if not den_pids_obj:
                continue
            den_pids_list = list(den_pids_obj)

            # ---- 2. 源 A：bedside ----
            a_pids = set()
            a_detail = {}

            try:
                bedside_docs = list(db.bedside.find(
                    {"pid": {"$in": den_pids_list},
                     "code": BEDSIDE_SEDATION_CODE,
                     "valid": True,
                     "time": {"$gte": start_dt, "$lte": end_dt_wide}},
                    {"pid": 1, "strVal": 1, "fVal": 1, "time": 1},
                ).max_time_ms(10000).limit(100000))

                for doc in bedside_docs:
                    spid = doc.get("pid", "")
                    if spid not in den_pids_obj:
                        continue
                    # 时间窗口：评估必须在本次 ICU 住院期间
                    p = pat_by_strpid.get(spid)
                    at = doc.get("time")
                    if p and at:
                        admit = p.get("icuAdmissionTime")
                        discharge = p.get("icuDischargeTime") or end_dt_wide
                        if at < admit or at > discharge:
                            continue
                    # RASS 值: strVal="-4"~"+4", fVal=-4.0~4.0
                    val = (doc.get("strVal") or "").strip()
                    if not val and doc.get("fVal") not in (None, ""):
                        val = str(doc.get("fVal")).strip()
                    if val and spid not in a_pids:
                        a_pids.add(spid)
                        a_detail[spid] = {
                            "source": "床旁评估记录",
                            "scale": SEDATION_SCALE_CN["RASS"],
                            "score_value": val,
                            "time": doc.get("time"),
                        }
            except Exception as e:
                print(f"[ICU-10] bedside query error: {e}")

            # ---- 3. 源 B：score 补判 ----
            b_pids = set()
            b_detail = {}

            need_b = [spid for spid in den_pids_list if spid not in a_pids]
            if need_b:
                try:
                    score_docs = list(db.score.find(
                        {"pid": {"$in": need_b},
                         "scoreType": {"$in": list(SCORE_SEDATION_TYPES)},
                         "valid": True,
                         "time": {"$gte": start_dt, "$lte": end_dt_wide}},
                        {"pid": 1, "scoreType": 1, "total": 1, "score": 1,
                         "value": 1, "fVal": 1, "iVal": 1, "strVal": 1, "time": 1},
                    ).max_time_ms(10000).limit(50000))

                    for doc in score_docs:
                        spid = doc.get("pid", "")
                        if spid not in den_pids_obj:
                            continue
                        # 时间窗口
                        p = pat_by_strpid.get(spid)
                        at = doc.get("time")
                        if p and at:
                            admit = p.get("icuAdmissionTime")
                            discharge = p.get("icuDischargeTime") or end_dt_wide
                            if at < admit or at > discharge:
                                continue
                        if spid not in b_pids:
                            b_pids.add(spid)
                            b_detail[spid] = {
                                "source": "量表评分记录",
                                "scale": SEDATION_SCALE_CN["rass"],
                                "score_value": _score_total(doc),
                                "time": doc.get("time"),
                            }
                except Exception as e:
                    print(f"[ICU-10] score query error: {e}")

            # ---- 4. 分子 = A ∪ B ----
            num_pids = a_pids | b_pids
            result["num_count"] = min(len(num_pids), result["den_count"])

            # ---- 5. 构建明细 ----
            result["den_patients"] = [
                {"pid": spid,
                 "mrn": pat_by_strpid[spid].get("mrn", "") or pat_by_strpid[spid].get("hisPid", ""),
                 "name": pat_by_strpid[spid].get("name", ""),
                 "patient_id": pat_by_strpid[spid].get("hisPid", ""),
                 "hisBed": pat_by_strpid[spid].get("hisBed", ""),
                 "icu_admit": pat_by_strpid[spid].get("icuAdmissionTime"),
                 }
                for spid in den_pids_obj
            ]

            result["num_patients"] = []
            for spid in num_pids:
                p = pat_by_strpid[spid]
                detail = a_detail.get(spid) or b_detail.get(spid) or {}
                result["num_patients"].append({
                    "pid": spid,
                    "mrn": p.get("mrn", "") or p.get("hisPid", ""),
                    "name": p.get("name", ""),
                    "patient_id": p.get("hisPid", ""),
                    "assess_source": detail.get("source", ""),
                    "assess_scale": detail.get("scale", ""),
                    "assess_value": detail.get("score_value", ""),
                    "assess_time": detail.get("time"),
                })

            break

        except Exception as e:
            print(f"[ICU-10] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-11：ICU患者标化病死指数(SMR)
# ============================================================

def _as_float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_icu11_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-11：ICU患者标化病死指数(SMR)。

    分母人群 = 同期出科且 dischargedType 为“死亡/出院/非医嘱离院”，并有入科
    24h 内首次 APACHE II 评分的完整病例。
    分母数值 = 每例首次 APACHE II apacheII.calDead.score 之和。
    分子 = 同一人群中 dischargedType 为“死亡/非医嘱离院”的人数。

    返回 {den_count, num_count, value, den_patients, num_patients}
    """
    from datetime import datetime as dt, timedelta

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)

    result = {
        "den_count": 0.0,
        "num_count": 0,
        "value": 0.0,
        "den_patients": [],
        "num_patients": [],
    }

    death_types = {"死亡", "非医嘱离院"}
    closed_types = {"出院", *death_types}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            patients = list(db.patient.find(
                {
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                    "icuDischargeTime": {"$gte": start_dt, "$lte": end_dt_wide},
                    "dischargedType": {"$in": list(closed_types)},
                },
                {
                    "_id": 1, "hisPid": 1, "mrn": 1, "name": 1,
                    "deptCode": 1, "icuAdmissionTime": 1, "icuDischargeTime": 1,
                    "dischargeTime": 1, "dischargedType": 1,
                },
            ).max_time_ms(10000).limit(200000))

            if not patients:
                continue

            pat_by_pid = {str(p["_id"]): p for p in patients}
            pids = list(pat_by_pid.keys())

            score_docs = list(db.score.find(
                {
                    "pid": {"$in": pids},
                    "scoreType": "apacheII",
                    "valid": True,
                },
                {
                    "pid": 1, "time": 1, "total": 1,
                    "apacheII.calDead.score": 1,
                },
            ).sort("time", 1).max_time_ms(15000).limit(300000))

            first_score_by_pid = {}
            for doc in score_docs:
                spid = doc.get("pid")
                if spid in first_score_by_pid:
                    continue
                pat = pat_by_pid.get(spid)
                if not pat:
                    continue
                score_time = doc.get("time")
                admit_time = pat.get("icuAdmissionTime")
                if not score_time or not admit_time:
                    continue
                if score_time < admit_time or score_time > admit_time + timedelta(hours=24):
                    continue
                cal_dead = (((doc.get("apacheII") or {}).get("calDead") or {}).get("score"))
                cal_dead = _as_float_or_none(cal_dead)
                if cal_dead is None or cal_dead < 0 or cal_dead > 1:
                    continue
                first_score_by_pid[spid] = {
                    "time": score_time,
                    "total": doc.get("total"),
                    "cal_dead": cal_dead,
                }

            den_patients = []
            num_patients = []
            expected_deaths = 0.0
            actual_deaths = 0

            for spid, score in first_score_by_pid.items():
                pat = pat_by_pid[spid]
                discharged_type = pat.get("dischargedType", "")
                expected_deaths += score["cal_dead"]
                if discharged_type in death_types:
                    actual_deaths += 1

                item = {
                    "pid": spid,
                    "mrn": pat.get("mrn", "") or pat.get("hisPid", ""),
                    "patient_id": pat.get("hisPid", "") or pat.get("mrn", ""),
                    "name": pat.get("name", ""),
                    "dept_code": pat.get("deptCode", ""),
                    "icu_admit": pat.get("icuAdmissionTime"),
                    "icu_discharge": pat.get("icuDischargeTime") or pat.get("dischargeTime"),
                    "dischargedType": discharged_type,
                    "apache_time": score["time"],
                    "apache_total": score.get("total"),
                    "apache_calDead": score["cal_dead"],
                }
                den_patients.append(item)
                if discharged_type in death_types:
                    num_patients.append(item)

            result["den_count"] = round(expected_deaths, 4)
            result["num_count"] = actual_deaths
            result["value"] = round(actual_deaths / expected_deaths, 2) if expected_deaths > 0 else 0.0
            result["den_patients"] = den_patients
            result["num_patients"] = num_patients
            break

        except Exception as e:
            print(f"[ICU-11] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-12/13：人工气道非计划拔管与48小时再置管
# ============================================================

AIRWAY_TUBE_TYPES = {"气管插管", "气插管", "气切套管"}


def _is_true(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _fmt_dt(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16] if value else ""


def _get_airway_tube_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    共用取数：
    - 分母：统计期内拔除的气管插管/气插管/气切套管，排除 replace=true 换管。
    - ICU-12 分子：分母中 unPlannedEndTube 为 true 的非计划拔管。
    - ICU-13 分子：分母拔管后48小时内同患者再次气管插管/气插管/气切套管，
      再置管记录 replace=true 时不计；气管插管转气切套管计入。
    """
    from datetime import datetime as dt, timedelta

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    reinsert_until = end_dt_wide + timedelta(hours=48)

    result = {
        "den_count": 0,
        "icu12_num_count": 0,
        "icu13_num_count": 0,
        "den_patients": [],
        "icu12_num_patients": [],
        "icu13_num_patients": [],
    }

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            patients = list(db.patient.find(
                {"deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"}},
                {"_id": 1, "hisPid": 1, "mrn": 1, "name": 1, "deptCode": 1},
            ).max_time_ms(10000).limit(200000))
            if not patients:
                continue

            pat_by_pid = {str(p["_id"]): p for p in patients}
            pids = list(pat_by_pid.keys())

            ended_docs = list(db.tubeExe.find(
                {
                    "pid": {"$in": pids},
                    "type": {"$in": list(AIRWAY_TUBE_TYPES)},
                    "endTime": {"$gte": start_dt, "$lte": end_dt_wide},
                },
                {
                    "_id": 1, "pid": 1, "type": 1, "startTime": 1, "endTime": 1,
                    "unPlannedEndTube": 1, "replace": 1,
                },
            ).sort("endTime", 1).max_time_ms(15000).limit(300000))

            den_docs = [d for d in ended_docs if not _is_true(d.get("replace")) and d.get("endTime")]
            if not den_docs:
                result["den_patients"] = []
                break

            reinsert_docs = list(db.tubeExe.find(
                {
                    "pid": {"$in": pids},
                    "type": {"$in": list(AIRWAY_TUBE_TYPES)},
                    "startTime": {"$gte": start_dt, "$lte": reinsert_until},
                },
                {
                    "_id": 1, "pid": 1, "type": 1, "startTime": 1, "endTime": 1,
                    "replace": 1,
                },
            ).sort("startTime", 1).max_time_ms(15000).limit(300000))

            starts_by_pid = {}
            for doc in reinsert_docs:
                if _is_true(doc.get("replace")):
                    continue
                starts_by_pid.setdefault(doc.get("pid"), []).append(doc)

            den_patients = []
            icu12_num_patients = []
            icu13_num_patients = []

            for doc in den_docs:
                pid = doc.get("pid")
                pat = pat_by_pid.get(pid, {})
                end_time = doc.get("endTime")
                base_item = {
                    "pid": pid,
                    "mrn": pat.get("mrn", "") or pat.get("hisPid", ""),
                    "patient_id": pat.get("hisPid", "") or pat.get("mrn", ""),
                    "name": pat.get("name", ""),
                    "dept_code": pat.get("deptCode", ""),
                    "tube_id": str(doc.get("_id", "")),
                    "tube_type": doc.get("type", ""),
                    "tube_start": doc.get("startTime"),
                    "tube_end": end_time,
                    "unplanned": _is_true(doc.get("unPlannedEndTube")),
                    "replace": _is_true(doc.get("replace")),
                }
                den_patients.append(base_item)

                if base_item["unplanned"]:
                    icu12_num_patients.append(base_item)

                reinsert = None
                for next_doc in starts_by_pid.get(pid, []):
                    next_start = next_doc.get("startTime")
                    if not next_start or next_doc.get("_id") == doc.get("_id"):
                        continue
                    if end_time < next_start <= end_time + timedelta(hours=48):
                        reinsert = next_doc
                        break

                if reinsert:
                    item = dict(base_item)
                    item.update({
                        "reinsert_type": reinsert.get("type", ""),
                        "reinsert_start": reinsert.get("startTime"),
                        "reinsert_tube_id": str(reinsert.get("_id", "")),
                    })
                    icu13_num_patients.append(item)

            result["den_count"] = len(den_patients)
            result["icu12_num_count"] = len(icu12_num_patients)
            result["icu13_num_count"] = len(icu13_num_patients)
            result["den_patients"] = den_patients
            result["icu12_num_patients"] = icu12_num_patients
            result["icu13_num_patients"] = icu13_num_patients
            break

        except Exception as e:
            print(f"[ICU-12/13] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


def get_icu12_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    data = _get_airway_tube_data(dept_codes, start_date, end_date)
    return {
        "den_count": data["den_count"],
        "num_count": data["icu12_num_count"],
        "den_patients": data["den_patients"],
        "num_patients": data["icu12_num_patients"],
    }


def get_icu13_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    data = _get_airway_tube_data(dept_codes, start_date, end_date)
    return {
        "den_count": data["den_count"],
        "num_count": data["icu13_num_count"],
        "den_patients": data["den_patients"],
        "num_patients": data["icu13_num_patients"],
    }


# ============================================================
# ICU-14：非计划转入ICU率
# ============================================================

def _first_operation_name(patient: dict) -> str:
    operations = patient.get("patientOperations") or []
    if not operations or not isinstance(operations[0], dict):
        return ""
    return operations[0].get("name", "") or ""


def get_icu14_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    分母：同期转入ICU的手术患者，admissionType 同时包含“手术”和“转入”。
    分子：分母患者中 admissionPlan == “非计划转入”。
    空值/缺失/其他 admissionPlan 默认不计入分子。
    """
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)

    result = {
        "den_count": 0,
        "num_count": 0,
        "value": 0.0,
        "den_patients": [],
        "num_patients": [],
    }

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            query = {
                "deptCode": {"$in": dept_codes},
                "status": {"$ne": "invalid"},
                "icuAdmissionTime": {"$gte": start_dt, "$lte": end_dt_wide},
                "$and": [
                    {"admissionType": {"$regex": "手术"}},
                    {"admissionType": {"$regex": "转入"}},
                ],
            }
            projection = {
                "_id": 1,
                "hisPid": 1,
                "mrn": 1,
                "name": 1,
                "deptCode": 1,
                "icuAdmissionTime": 1,
                "admissionType": 1,
                "admissionPlan": 1,
                "patientOperations.name": 1,
            }

            patients = list(
                db.patient.find(query, projection)
                .sort("icuAdmissionTime", 1)
                .max_time_ms(15000)
                .limit(200000)
            )
            if not patients:
                continue

            den_patients = []
            num_patients = []
            seen = set()
            for patient in patients:
                pid = str(patient.get("_id"))
                if pid in seen:
                    continue
                seen.add(pid)

                item = {
                    "pid": pid,
                    "mrn": patient.get("mrn", "") or patient.get("hisPid", ""),
                    "patient_id": patient.get("hisPid", "") or patient.get("mrn", "") or pid[-8:],
                    "name": patient.get("name", ""),
                    "dept_code": patient.get("deptCode", ""),
                    "icuAdmissionTime": patient.get("icuAdmissionTime"),
                    "admissionType": patient.get("admissionType", "") or "",
                    "admissionPlan": patient.get("admissionPlan", "") or "",
                    "operation_name": _first_operation_name(patient),
                }
                den_patients.append(item)
                if item["admissionPlan"] == "非计划转入":
                    num_patients.append(item)

            den_count = len(den_patients)
            num_count = len(num_patients)
            result.update({
                "den_count": den_count,
                "num_count": num_count,
                "value": round(num_count / den_count * 100, 1) if den_count > 0 else 0.0,
                "den_patients": den_patients,
                "num_patients": num_patients,
            })
            break

        except Exception as e:
            print(f"[ICU-14] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-16/17/CAUTI：三管院感发病率
# ============================================================

# ============================================================
# ICU-15: 48h readmission after ICU discharge
# ============================================================

def _icu15_patient_identity(patient: dict, fallback_pid: str = "") -> str:
    for key in ("hisPid", "mrn", "patientId", "inHospitalNo"):
        val = patient.get(key)
        if val not in (None, ""):
            return f"{key}:{val}"
    return f"pid:{fallback_pid or str(patient.get('_id', ''))}"


def _icu15_patient_item(patient: dict, pid: str, discharge_time, source: str) -> dict:
    return {
        "pid": pid,
        "mrn": patient.get("mrn", "") or patient.get("hisPid", ""),
        "patient_id": patient.get("hisPid", "") or patient.get("mrn", "") or pid[-8:],
        "name": patient.get("name", ""),
        "dept_code": patient.get("deptCode", ""),
        "icu_admit": patient.get("icuAdmissionTime"),
        "icu_discharge": discharge_time,
        "source": source,
        "basis": "patient ICU discharge in period" if source == "patient" else "patInIcuHistoryList ICU discharge in period",
    }


def _icu15_event_key(identity: str, discharge_time) -> tuple:
    rounded = discharge_time.replace(second=0, microsecond=0) if discharge_time else None
    return identity, rounded


def _icu15_find_merge_key(events: dict, identity: str, discharge_time, merge_hours: int = 2):
    from datetime import timedelta

    if not discharge_time:
        return None
    for key, item in events.items():
        if key[0] != identity:
            continue
        existing_time = item.get("icu_discharge")
        if existing_time and abs(existing_time - discharge_time) <= timedelta(hours=merge_hours):
            return key
    return None


def _icu15_add_event(events: dict, identity: str, item: dict):
    discharge_time = item.get("icu_discharge")
    merge_key = _icu15_find_merge_key(events, identity, discharge_time)
    if merge_key:
        existing = events[merge_key]
        if item.get("history_re_admit") and not existing.get("history_re_admit"):
            existing["history_re_admit"] = item.get("history_re_admit")
        existing["source"] = "patient+patInIcuHistoryList" if existing.get("source") != item.get("source") else existing.get("source")
        existing["basis"] = "patient record and patInIcuHistoryList discharge merged"
        return existing
    key = _icu15_event_key(identity, discharge_time)
    events[key] = item
    return item


def get_icu15_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-15: transfer-out ICU then return to ICU within 48h.

    Denominator is discharge events in the period, including patient ICU discharge
    records and patInIcuHistoryList ICU discharge records. Numerator is the same
    events with a later ICU admission within 48 hours.
    """
    from datetime import datetime as dt, timedelta

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    lookahead_end = end_dt_wide + timedelta(hours=48)

    result = {
        "den_count": 0,
        "num_count": 0,
        "value": 0.0,
        "value_type": "percent",
        "den_patients": [],
        "num_patients": [],
    }

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            projection = {
                "_id": 1, "hisPid": 1, "mrn": 1, "patientId": 1, "inHospitalNo": 1,
                "name": 1, "deptCode": 1, "icuAdmissionTime": 1, "icuDischargeTime": 1,
                "dischargeTime": 1, "patInIcuHistoryList": 1, "status": 1,
            }

            scoped_patients = list(db.patient.find(
                {
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                    "$or": [
                        {"icuDischargeTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                        {"dischargeTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                        {"patInIcuHistoryList.icuDischargeTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                    ],
                },
                projection,
            ).sort("icuDischargeTime", 1).max_time_ms(20000).limit(200000))

            if not scoped_patients:
                continue

            his_pids = [p.get("hisPid") for p in scoped_patients if p.get("hisPid")]
            mrns = [p.get("mrn") for p in scoped_patients if p.get("mrn")]
            patient_ids = [p.get("patientId") for p in scoped_patients if p.get("patientId")]
            identities = {
                _icu15_patient_identity(p, str(p.get("_id", "")))
                for p in scoped_patients
            }

            identity_query = []
            if his_pids:
                identity_query.append({"hisPid": {"$in": list(set(his_pids))}})
            if mrns:
                identity_query.append({"mrn": {"$in": list(set(mrns))}})
            if patient_ids:
                identity_query.append({"patientId": {"$in": list(set(patient_ids))}})

            related_patients = scoped_patients
            if identity_query:
                related_patients = list(db.patient.find(
                    {
                        "status": {"$ne": "invalid"},
                        "$or": identity_query,
                        "icuAdmissionTime": {"$lte": lookahead_end},
                    },
                    projection,
                ).sort("icuAdmissionTime", 1).max_time_ms(20000).limit(300000))

            admissions_by_identity = defaultdict(list)
            for patient in related_patients:
                pid = str(patient.get("_id", ""))
                identity = _icu15_patient_identity(patient, pid)
                if identity not in identities:
                    continue
                admit_time = patient.get("icuAdmissionTime")
                if admit_time:
                    admissions_by_identity[identity].append({
                        "time": admit_time,
                        "pid": pid,
                        "dept_code": patient.get("deptCode", ""),
                        "source": "patient",
                    })
                for hist in patient.get("patInIcuHistoryList") or []:
                    re_time = hist.get("reIcuAdmissionTime")
                    if re_time:
                        admissions_by_identity[identity].append({
                            "time": re_time,
                            "pid": pid,
                            "dept_code": patient.get("deptCode", ""),
                            "source": "patInIcuHistoryList",
                        })

            for admits in admissions_by_identity.values():
                admits.sort(key=lambda x: x["time"])

            events = {}
            for patient in scoped_patients:
                pid = str(patient.get("_id", ""))
                identity = _icu15_patient_identity(patient, pid)
                discharge_time = patient.get("icuDischargeTime") or patient.get("dischargeTime")
                if discharge_time and start_dt <= discharge_time <= end_dt_wide:
                    _icu15_add_event(
                        events,
                        identity,
                        _icu15_patient_item(patient, pid, discharge_time, "patient"),
                    )

                for hist in patient.get("patInIcuHistoryList") or []:
                    hist_discharge = hist.get("icuDischargeTime")
                    if not hist_discharge or not (start_dt <= hist_discharge <= end_dt_wide):
                        continue
                    item = _icu15_add_event(
                        events,
                        identity,
                        _icu15_patient_item(patient, pid, hist_discharge, "patInIcuHistoryList"),
                    )
                    re_time = hist.get("reIcuAdmissionTime")
                    if re_time:
                        item["history_re_admit"] = re_time

            den_patients = []
            num_patients = []
            for (identity, _), item in sorted(events.items(), key=lambda kv: kv[1].get("icu_discharge")):
                discharge_time = item.get("icu_discharge")
                readmit = None
                history_re_admit = item.get("history_re_admit")
                if history_re_admit and discharge_time < history_re_admit <= discharge_time + timedelta(hours=48):
                    readmit = {
                        "time": history_re_admit,
                        "pid": item.get("pid", ""),
                        "dept_code": item.get("dept_code", ""),
                        "source": "patInIcuHistoryList",
                    }
                if not readmit:
                    for admit in admissions_by_identity.get(identity, []):
                        at = admit.get("time")
                        if at and discharge_time < at <= discharge_time + timedelta(hours=48):
                            readmit = admit
                            break
                item["re_icu_admit"] = readmit.get("time") if readmit else None
                item["re_admit_dept_code"] = readmit.get("dept_code", "") if readmit else ""
                item["re_admit_source"] = readmit.get("source", "") if readmit else ""
                item["basis"] = (
                    "ICU discharge followed by ICU readmission within 48h"
                    if readmit else item.get("basis", "")
                )
                den_patients.append(item)
                if readmit:
                    num_patients.append(item)

            den_count = len(den_patients)
            num_count = len(num_patients)
            result.update({
                "den_count": den_count,
                "num_count": num_count,
                "value": round(num_count / den_count * 100, 1) if den_count > 0 else 0.0,
                "den_patients": den_patients,
                "num_patients": num_patients,
            })
            break
        except Exception as e:
            print(f"[ICU-15] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-18: acute brain injury consciousness assessment rate
# ============================================================

PRIMARY_BRAIN_INJURY_ICD_PREFIXES = {
    "S02", "S06", "I60", "I61", "I62", "I63",
    "C70", "C71", "D32", "D33", "D42", "D43",
    "G40", "G41",
    *{f"G0{i}" for i in range(10)},
}
SECONDARY_BRAIN_INJURY_ICD_PREFIXES = {
    "G93.1", "G93.4", "T67.0", "K72",
}
IMAGING_BRAIN_INJURY_ICD_PREFIXES = {"R90"}
CONDITIONAL_BRAIN_INJURY_ICD_PREFIXES = {"I46", "J96", "N18", "N19"}

PRIMARY_BRAIN_KEYWORDS = {
    "颅脑损伤", "脑外伤", "头部外伤", "蛛网膜下腔出血", "蛛血", "脑出血",
    "脑梗", "脑梗死", "脑栓塞", "颅内感染", "脑炎", "脑膜炎", "脑脓肿",
    "脑肿瘤", "颅内占位", "胶质瘤", "脑膜瘤", "癫痫", "惊厥",
}
SECONDARY_BRAIN_KEYWORDS = {
    "心肺复苏后", "复苏后", "缺血缺氧性脑病", "缺氧缺血性脑病", "热射病",
    "代谢性脑病", "肝性脑病", "肺性脑病", "肾性脑病", "尿毒症脑病",
    "中毒性脑病", "脑病",
}
IMAGING_BRAIN_KEYWORDS = {"颅脑", "头颅", "脑"}
IMAGING_ABNORMAL_KEYWORDS = {
    "出血", "梗死", "梗塞", "占位", "肿瘤", "水肿", "挫裂伤", "骨折",
    "蛛网膜下腔", "硬膜下", "硬膜外", "脑疝", "脑积水", "异常密度",
    "异常信号", "缺血", "软化灶",
}
NEGATIVE_IMAGING_KEYWORDS = {"未见明显异常", "未见异常", "无明显异常"}
GCS_BEDSIDE_CODES = {"param_score_gcs_obs"}
FOUR_BEDSIDE_CODES = {"param_score_four", "param_score_four_obs"}
GCS_SCORE_TYPES = {"gcsScore"}
FOUR_SCORE_TYPES = {"fourScore", "FOUR", "four", "FourScore"}


def _normalize_icd(code) -> str:
    return str(code or "").strip().upper()


def _patient_text_diagnoses(patient: dict) -> list[str]:
    texts = []
    for field in ("clinicalDiagnosis", "admissionDiagnosis"):
        val = patient.get(field)
        if val:
            texts.append(str(val))
    for item in patient.get("diagnosisHistoryList") or []:
        val = item.get("diagnosis") if isinstance(item, dict) else None
        if val:
            texts.append(str(val))
    cleaned = []
    for text in texts:
        text = text.replace("[", "|").replace("]", "|")
        for part in text.split("|"):
            part = part.strip()
            if part:
                cleaned.append(part)
    return cleaned


def _match_keyword(texts: list[str], keywords: set[str]):
    for text in texts:
        for keyword in keywords:
            if keyword in text:
                return keyword, text
    return "", ""


def _match_brain_injury_icd(codes: list[str], texts: list[str]) -> tuple[str, str, str]:
    text_joined = "|".join(texts)
    for code in codes:
        icd = _normalize_icd(code)
        if not icd:
            continue
        if any(icd.startswith(prefix) for prefix in PRIMARY_BRAIN_INJURY_ICD_PREFIXES):
            return "原发神经", "icd", icd
        if any(icd.startswith(prefix) for prefix in SECONDARY_BRAIN_INJURY_ICD_PREFIXES):
            return "非原发脑损伤", "icd", icd
        if any(icd.startswith(prefix) for prefix in IMAGING_BRAIN_INJURY_ICD_PREFIXES):
            return "影像异常", "icd", icd
        if any(icd.startswith(prefix) for prefix in CONDITIONAL_BRAIN_INJURY_ICD_PREFIXES):
            kw, _ = _match_keyword([text_joined], SECONDARY_BRAIN_KEYWORDS)
            if kw:
                return "非原发脑损伤", "icd+text", f"{icd}+{kw}"
    return "", "", ""


def _match_brain_injury_text(texts: list[str]) -> tuple[str, str, str]:
    kw, text = _match_keyword(texts, PRIMARY_BRAIN_KEYWORDS)
    if kw:
        return "原发神经", "文本", kw
    kw, text = _match_keyword(texts, SECONDARY_BRAIN_KEYWORDS)
    if kw:
        return "非原发脑损伤", "文本", kw
    return "", "", ""


def _brain_injury_den_item(patient: dict, pid: str, category: str, source: str, evidence: str, confidence=1.0):
    return {
        "pid": pid,
        "mrn": patient.get("mrn", "") or patient.get("hisPid", ""),
        "patient_id": patient.get("hisPid", "") or patient.get("mrn", "") or pid[-8:],
        "name": patient.get("name", ""),
        "dept_code": patient.get("deptCode", ""),
        "icu_admit": patient.get("icuAdmissionTime"),
        "category": category,
        "den_source": source,
        "evidence": evidence,
        "ai_confidence": confidence,
        "assessed": False,
        "first_assess_time": None,
        "assess_source": "",
    }


def _apply_icu18_assessments(db, den_by_pid: dict, start_dt, end_dt_wide):
    if not den_by_pid:
        return
    pids = list(den_by_pid.keys())

    def accept_assessment(doc, source):
        pid = doc.get("pid")
        item = den_by_pid.get(pid)
        if not item:
            return
        assess_time = doc.get("time")
        patient_admit = item.get("icu_admit") or start_dt
        if assess_time and (assess_time < patient_admit or assess_time > end_dt_wide):
            return
        old_time = item.get("first_assess_time")
        if not old_time or (assess_time and assess_time < old_time):
            item["assessed"] = True
            item["first_assess_time"] = assess_time
            item["assess_source"] = source

    bedside_query = {
        "pid": {"$in": pids},
        "valid": True,
        "code": {"$in": list(GCS_BEDSIDE_CODES | FOUR_BEDSIDE_CODES)},
        "time": {"$gte": start_dt, "$lte": end_dt_wide},
    }
    for doc in db.bedside.find(
        bedside_query,
        {"pid": 1, "code": 1, "time": 1, "strVal": 1},
    ).sort("time", 1).max_time_ms(30000).limit(300000):
        code = doc.get("code")
        source = "GCS床旁记录" if code in GCS_BEDSIDE_CODES else "FOUR床旁记录"
        accept_assessment(doc, source)

    score_query = {
        "pid": {"$in": pids},
        "valid": True,
        "scoreType": {"$in": list(GCS_SCORE_TYPES | FOUR_SCORE_TYPES)},
        "time": {"$gte": start_dt, "$lte": end_dt_wide},
    }
    for doc in db.score.find(
        score_query,
        {"pid": 1, "scoreType": 1, "time": 1, "total": 1},
    ).sort("time", 1).max_time_ms(30000).limit(300000):
        stype = doc.get("scoreType")
        source = "GCS量表评分" if stype in GCS_SCORE_TYPES else "FOUR量表评分"
        accept_assessment(doc, source)


def _apply_icu18_image_reports(den_by_pid: dict, patients_by_his_pid: dict, start_dt, end_dt_wide):
    if not patients_by_his_pid:
        return
    try:
        dc = get_client("DataCenter")["DataCenter"]
        if "VI_ICU_REPORT" not in dc.list_collection_names():
            return
        his_pids = list(patients_by_his_pid.keys())
        query = {
            "pid": {"$in": his_pids},
            "$or": [
                {"examTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                {"reportTime": {"$gte": start_dt, "$lte": end_dt_wide}},
            ],
            "$and": [
                {"$or": [
                    {"examName": {"$regex": "颅脑|头颅|脑"}},
                    {"title": {"$regex": "颅脑|头颅|脑"}},
                    {"bodyParts": {"$regex": "颅脑|头颅|脑"}},
                ]},
                {"$or": [
                    {"diagnose": {"$regex": "出血|梗死|梗塞|占位|肿瘤|水肿|挫裂伤|骨折|脑疝|脑积水|异常"}},
                    {"conclusion": {"$regex": "出血|梗死|梗塞|占位|肿瘤|水肿|挫裂伤|骨折|脑疝|脑积水|异常"}},
                    {"reportDesc": {"$regex": "出血|梗死|梗塞|占位|肿瘤|水肿|挫裂伤|骨折|脑疝|脑积水|异常"}},
                ]},
            ],
        }
        for report in dc.VI_ICU_REPORT.find(
            query,
            {"pid": 1, "examName": 1, "title": 1, "diagnose": 1, "conclusion": 1, "reportDesc": 1, "examTime": 1, "reportTime": 1},
        ).sort("examTime", 1).max_time_ms(30000).limit(100000):
            his_pid = report.get("pid")
            patient = patients_by_his_pid.get(his_pid)
            if not patient:
                continue
            text = "|".join(str(report.get(f) or "") for f in ("diagnose", "conclusion", "reportDesc"))
            if any(neg in text for neg in NEGATIVE_IMAGING_KEYWORDS):
                continue
            if not any(kw in text for kw in IMAGING_ABNORMAL_KEYWORDS):
                continue
            pid = str(patient.get("_id"))
            if pid in den_by_pid:
                continue
            evidence = (report.get("examName") or report.get("title") or "颅脑影像") + ":" + text[:40]
            den_by_pid[pid] = _brain_injury_den_item(patient, pid, "影像异常", "影像", evidence, 0.9)
    except Exception as e:
        print(f"[ICU-18] image report query error: {e}")


def get_icu18_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-18: acute brain injury consciousness assessment rate.
    Denominator uses patient diagnosis ICD/text plus image/manual supplements.
    Numerator is distinct denominator patients with at least one GCS or FOUR record.
    """
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    result = {
        "den_count": 0,
        "num_count": 0,
        "value": 0.0,
        "value_type": "percent",
        "den_patients": [],
        "num_patients": [],
        "note": "",
    }

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            patients = list(db.patient.find(
                {
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                    "icuAdmissionTime": {"$gte": start_dt, "$lte": end_dt_wide},
                },
                {
                    "_id": 1, "hisPid": 1, "mrn": 1, "name": 1, "deptCode": 1,
                    "icuAdmissionTime": 1, "clinicalDiagnosisCodeList": 1,
                    "dischargedDiagnosisIcd": 1, "clinicalDiagnosis": 1,
                    "admissionDiagnosis": 1, "diagnosisHistoryList": 1,
                    "patientOperations.name": 1,
                },
            ).sort("icuAdmissionTime", 1).max_time_ms(30000).limit(200000))
            if not patients:
                continue

            den_by_pid = {}
            patients_by_pid = {str(p["_id"]): p for p in patients}
            patients_by_his_pid = {str(p.get("hisPid")): p for p in patients if p.get("hisPid")}

            for patient in patients:
                pid = str(patient["_id"])
                texts = _patient_text_diagnoses(patient)
                codes = []
                for field in ("clinicalDiagnosisCodeList", "dischargedDiagnosisIcd"):
                    value = patient.get(field)
                    if isinstance(value, list):
                        codes.extend(value)
                    elif value:
                        codes.append(value)

                category, source, evidence = _match_brain_injury_icd(codes, texts)
                if not category:
                    category, source, evidence = _match_brain_injury_text(texts)
                if category:
                    den_by_pid[pid] = _brain_injury_den_item(patient, pid, category, source, evidence, 1.0)

            disease_docs = list(db.diseaseDiagnosis.find(
                {
                    "pid": {"$in": list(patients_by_pid.keys())},
                    "$or": [
                        {"brainInjury.primaryNervousDisease": {"$exists": True, "$nin": [None, ""]}},
                        {"brainInjury.notPrimaryNervousDisease": {"$exists": True, "$nin": [None, ""]}},
                        {"brainInjury.luNaoCheckResult": {"$exists": True, "$nin": [None, ""]}},
                    ],
                },
                {"pid": 1, "brainInjury": 1},
            ).max_time_ms(15000).limit(100000))
            for doc in disease_docs:
                pid = doc.get("pid")
                patient = patients_by_pid.get(pid)
                if not patient or pid in den_by_pid:
                    continue
                brain = doc.get("brainInjury") or {}
                evidence = brain.get("primaryNervousDisease") or brain.get("notPrimaryNervousDisease") or brain.get("luNaoCheckResult") or "brainInjury"
                den_by_pid[pid] = _brain_injury_den_item(patient, pid, "人工确认脑损伤", "diseaseDiagnosis", str(evidence), 1.0)

            _apply_icu18_image_reports(den_by_pid, patients_by_his_pid, start_dt, end_dt_wide)
            _apply_icu18_assessments(db, den_by_pid, start_dt, end_dt_wide)

            den_patients = list(den_by_pid.values())
            num_patients = [p for p in den_patients if p.get("assessed")]
            den_count = len(den_patients)
            num_count = len(num_patients)
            result.update({
                "den_count": den_count,
                "num_count": num_count,
                "value": round(num_count / den_count * 100, 2) if den_count > 0 else 0.0,
                "den_patients": den_patients,
                "num_patients": num_patients,
                "note": "" if den_count > 0 else "无急性脑损伤患者",
            })
            break
        except Exception as e:
            print(f"[ICU-18] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return result


# ============================================================
# ICU-19：48h 内肠内营养(EN)启动率
# ============================================================

EN_BEDSIDE_ROUTE_CODES = {"param_肠内营养途径"}
EN_BEDSIDE_START_CODES = {"param_肠内营养措施", "param_营养输注方式"}
EN_BEDSIDE_START_VALUES = {"开始", "启动", "给予", "分次推注", "间接重力滴注", "持续泵入", "顿服"}
EN_ROUTE_KEYWORDS = {"经口", "口服", "胃管", "鼻胃管", "鼻空肠管", "鼻肠管", "造瘘", "空肠造瘘", "胃造瘘"}
EN_METHOD_KEYWORDS = {"口服", "鼻饲", "管饲", "胃管", "鼻胃管", "鼻肠管", "肠内", "经口", "造瘘"}
EN_NAME_WHITELIST = {
    "肠内营养", "能全力", "瑞素", "瑞能", "瑞代", "瑞先", "百普力", "百普素",
    "安素", "康全力", "佳维体", "益菲佳", "维沃", "全安素", "短肽型",
    "整蛋白型", "匀浆膳", "鼻饲营养",
}
PN_NAME_BLACKLIST = {
    "脂肪乳注射液", "中长链脂肪乳", "结构脂肪乳", "复方氨基酸注射液",
    "葡萄糖注射液", "卡文", "卡全", "全合一", "静脉营养", "肠外营养",
}
EN_CONTRAINDICATION_KEYWORDS = {
    "肠梗阻", "肠缺血", "消化道出血", "胃潴留", "肠瘘", "休克未纠正",
    "严重腹胀", "腹腔间隔室综合征",
}


def _first_time_from_drugexe(doc):
    t = doc.get("startTime") or doc.get("exeTime") or doc.get("orderTime")
    if t:
        return t
    his_start = doc.get("hisStartTime")
    if isinstance(his_start, dict):
        return his_start.get("exeTime") or his_start.get("startTime")
    return None


def _drug_names(doc) -> list[str]:
    names = []
    for item in doc.get("drugList", []) or []:
        name = str(item.get("name") or item.get("drugName") or "").strip()
        if name:
            names.append(name)
    for key in ("drugName", "orderName", "name"):
        name = str(doc.get(key) or "").strip()
        if name:
            names.append(name)
    return names


def _drug_codes(doc) -> set:
    codes = set()
    for item in doc.get("drugList", []) or []:
        code = str(item.get("code") or item.get("drugCode") or "").strip()
        if code:
            codes.add(code)
    for key in ("drugCode", "code"):
        code = str(doc.get(key) or "").strip()
        if code:
            codes.add(code)
    return codes


def _is_executed_drugexe(doc) -> bool:
    return (
        doc.get("status") == "finished"
        or doc.get("statusFlag") == "已执行"
        or doc.get("executeStatus") == "已执行"
    )


def _match_enteral_name(names: list[str]) -> tuple[bool, str, str]:
    text = " ".join(names)
    for kw in EN_NAME_WHITELIST:
        if kw in text:
            return True, kw, ""
    for kw in PN_NAME_BLACKLIST:
        if kw in text:
            return False, "", kw
    if ("注射液" in text or "静脉" in text) and "肠内营养" not in text:
        return False, "", "注射液/静脉"
    return False, "", ""


def _match_enteral_route(doc) -> tuple[bool, str]:
    vals = []
    for key in ("methodCode", "methodName", "route", "usage", "useWay"):
        val = str(doc.get(key) or "").strip()
        if val:
            vals.append(val)
    for item in doc.get("drugList", []) or []:
        for key in ("methodCode", "methodName", "route", "usage", "useWay"):
            val = str(item.get(key) or "").strip()
            if val:
                vals.append(val)
    text = " ".join(vals)
    for kw in EN_METHOD_KEYWORDS:
        if kw in text:
            return True, kw
    return False, ""


def _contraindication_evidence(patient: dict) -> list[str]:
    text = " ".join(
        str(patient.get(k) or "")
        for k in ("clinicalDiagnosis", "diagnosis", "admissionDiagnosis")
    )
    return [kw for kw in EN_CONTRAINDICATION_KEYWORDS if kw in text]


def _resolve_en_start_from_bedside(db, pids: list, start_dt, end_dt_wide) -> dict:
    result = {}
    docs = list(db.bedside.find(
        {
            "pid": {"$in": pids},
            "valid": True,
            "code": {"$in": list(EN_BEDSIDE_ROUTE_CODES | EN_BEDSIDE_START_CODES)},
            "time": {"$gte": start_dt, "$lte": end_dt_wide},
        },
        {"_id": 1, "pid": 1, "code": 1, "strVal": 1, "time": 1},
    ).sort("time", 1).max_time_ms(20000).limit(300000))

    latest_route = {}
    for doc in docs:
        pid = doc.get("pid")
        code = doc.get("code")
        val = str(doc.get("strVal") or "").strip()
        t = doc.get("time")
        if not pid or not t:
            continue
        if code in EN_BEDSIDE_ROUTE_CODES and val:
            latest_route[pid] = {"value": val, "time": t}
            continue
        if code not in EN_BEDSIDE_START_CODES:
            continue
        has_start = any(kw in val for kw in EN_BEDSIDE_START_VALUES)
        route = latest_route.get(pid, {})
        route_value = route.get("value", "")
        has_route = any(kw in route_value for kw in EN_ROUTE_KEYWORDS)
        if has_start and (has_route or "肠内" in code or "肠内" in val):
            if pid not in result or t < result[pid]["time"]:
                result[pid] = {
                    "time": t,
                    "source": "bedside",
                    "rule": "en_bedside_start",
                    "hit": val or "开始",
                    "route": route_value,
                    "record_id": str(doc.get("_id", "")),
                }
    return result


def _resolve_en_start_from_drugexe(db, pids: list, start_dt, end_dt_wide) -> dict:
    nutrition_codes = {
        str(d.get("code"))
        for d in db.configDrug.find({"classification": "营养"}, {"code": 1}).max_time_ms(10000)
        if d.get("code")
    }
    docs = list(db.drugExe.find(
        {
            "pid": {"$in": pids},
            "startTime": {"$gte": start_dt, "$lte": end_dt_wide},
            "$or": [
                {"status": "finished"},
                {"statusFlag": "已执行"},
                {"executeStatus": "已执行"},
            ],
        },
        {
            "_id": 1, "pid": 1, "startTime": 1, "exeTime": 1, "hisStartTime": 1,
            "status": 1, "statusFlag": 1, "executeStatus": 1,
            "methodCode": 1, "methodName": 1, "route": 1, "usage": 1, "useWay": 1,
            "drugName": 1, "orderName": 1, "name": 1,
            "drugList.code": 1, "drugList.name": 1, "drugList.methodCode": 1,
            "drugList.methodName": 1, "drugList.route": 1, "drugList.usage": 1,
            "drugList.useWay": 1,
        },
    ).sort("startTime", 1).max_time_ms(30000).limit(500000))

    result = {}
    for doc in docs:
        if not _is_executed_drugexe(doc):
            continue
        pid = doc.get("pid")
        t = _first_time_from_drugexe(doc)
        if not pid or not t:
            continue
        names = _drug_names(doc)
        codes = _drug_codes(doc)
        name_hit, name_kw, pn_kw = _match_enteral_name(names)
        route_hit, route_kw = _match_enteral_route(doc)
        class_hit = bool(nutrition_codes & codes)
        if name_hit:
            evidence = {"source": "name", "rule": "en_name_whitelist", "hit": name_kw}
        elif class_hit and route_hit:
            evidence = {"source": "classification", "rule": "nutrition_enteral", "hit": route_kw}
        elif class_hit and pn_kw:
            continue
        else:
            continue
        if pid not in result or t < result[pid]["time"]:
            result[pid] = {
                **evidence,
                "time": t,
                "route": route_kw,
                "drug_name": ", ".join(names[:3]),
                "record_id": str(doc.get("_id", "")),
            }
    return result


def get_icu19_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """ICU-19: 48h 内肠内营养(EN)启动率。"""
    from datetime import datetime as dt, timedelta

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    result = {"den_count": 0, "num_count": 0, "den_patients": [], "num_patients": []}

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            patients = list(db.patient.find(
                {
                    "deptCode": {"$in": dept_codes},
                    "status": {"$ne": "invalid"},
                    "icuAdmissionTime": {"$gte": start_dt, "$lte": end_dt_wide},
                },
                {
                    "_id": 1, "hisPid": 1, "mrn": 1, "name": 1, "deptCode": 1,
                    "icuAdmissionTime": 1, "icuDischargeTime": 1, "dischargeTime": 1,
                    "clinicalDiagnosis": 1, "diagnosis": 1, "admissionDiagnosis": 1,
                },
            ).sort("icuAdmissionTime", 1).max_time_ms(20000).limit(200000))
            if not patients:
                continue

            den_patients = []
            pat_by_pid = {}
            for p in patients:
                pid = str(p["_id"])
                admit = p.get("icuAdmissionTime")
                if not admit:
                    continue
                stay_end = p.get("icuDischargeTime") or p.get("dischargeTime") or min(dt.now(), end_dt_wide)
                if stay_end < admit:
                    continue
                if (stay_end - admit).total_seconds() <= 48 * 3600:
                    continue
                p["_pid"] = pid
                p["_stay_end"] = stay_end
                pat_by_pid[pid] = p
                den_patients.append(p)

            if not den_patients:
                break

            pids = list(pat_by_pid.keys())
            bedside_starts = _resolve_en_start_from_bedside(db, pids, start_dt, end_dt_wide)
            drug_starts = _resolve_en_start_from_drugexe(db, pids, start_dt, end_dt_wide)

            den_items = []
            num_items = []
            for pid, p in pat_by_pid.items():
                admit = p.get("icuAdmissionTime")
                candidates = [ev for ev in (bedside_starts.get(pid), drug_starts.get(pid)) if ev]
                ev = min(candidates, key=lambda x: x["time"]) if candidates else None
                en_start = ev.get("time") if ev else None
                within_48h = bool(en_start and en_start - admit <= timedelta(hours=48))
                contraindications = _contraindication_evidence(p)
                item = {
                    "pid": pid,
                    "mrn": p.get("mrn", "") or p.get("hisPid", ""),
                    "patient_id": p.get("hisPid", "") or p.get("mrn", "") or pid[-8:],
                    "name": p.get("name", ""),
                    "dept_code": p.get("deptCode", ""),
                    "icu_admit": admit,
                    "icu_discharge": p.get("_stay_end"),
                    "en_start_time": en_start,
                    "within_48h": within_48h,
                    "source": ev.get("source", "none") if ev else "none",
                    "rule": ev.get("rule", "") if ev else "",
                    "hit": ev.get("hit", "") if ev else "",
                    "route": ev.get("route", "") if ev else "",
                    "drug_name": ev.get("drug_name", "") if ev else "",
                    "contraindication": bool(contraindications),
                    "contraindication_hits": contraindications,
                    "basis": (
                        "48h内启动EN" if within_48h else
                        ("已启动EN但超过48h" if en_start else "未检出EN启动记录")
                    ),
                }
                den_items.append(item)
                if within_48h:
                    num_items.append(item)

            result.update({
                "den_count": len(den_items),
                "num_count": len(num_items),
                "den_patients": den_items,
                "num_patients": num_items,
            })
            break
        except Exception as e:
            print(f"[ICU-19] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    return result


TRI_TUBE_CONFIG = {
    "ICU-16": {
        "name": "VAP发病率",
        "diseaseType": "VAP呼吸机相关性肺炎",
        "propertyType": "respirator",
        "denominator": "ventilator",
    },
    "ICU-17": {
        "name": "CRBSI发病率",
        "diseaseType": "CRBSI血管内管道相关血流感染",
        "propertyType": "vascularInfection",
        "denominator": "vascular",
    },
    "CAUTI": {
        "name": "CAUTI尿管相关感染率",
        "diseaseType": "CAUTI尿管相关感染",
        "propertyType": "urinaryTractInfection",
        "denominator": "urinary",
    },
}

TRI_TUBE_EVENT_WINDOW_DAYS = 14
INVASIVE_VENT_VALUES = {"管辅", "切辅", "有创"}
INVASIVE_VENT_KEYWORDS = ("有创呼吸机(气辅)", "有创呼吸机(切辅)")
VASCULAR_TUBE_TYPES = {
    "中心静脉导管", "动脉导管", "PICC管", "PICCO管", "透析管", "血滤管",
    "CRRT管", "中长导管", "输液港",
}
CENTRAL_VASCULAR_TUBE_TYPES = {
    "中心静脉导管", "PICC管", "透析管", "血滤管", "CRRT管",
}
EXCLUDED_VASCULAR_TUBE_TYPES = {
    "动脉导管": "动脉导管-非中心导管",
    "PICCO管": "PICCO管-非中心导管",
    "中长导管": "中长导管-非中心导管",
    "输液港": "输液港-待确认中心属性，默认剔除",
}
URINARY_TUBE_TYPES = {"尿管"}


def _day_range(start_time, end_time):
    from datetime import timedelta

    if not start_time or not end_time:
        return
    day = start_time.date()
    last_day = end_time.date()
    while day <= last_day:
        yield day
        day += timedelta(days=1)


def _is_invasive_vent_value(value) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text in INVASIVE_VENT_VALUES:
        return True
    return any(keyword in text for keyword in INVASIVE_VENT_KEYWORDS)


def _tri_tube_patient_scope(db, dept_codes, start_dt, end_dt_wide):
    patients = list(db.patient.find(
        {
            "deptCode": {"$in": dept_codes},
            "status": {"$ne": "invalid"},
            "icuAdmissionTime": {"$lte": end_dt_wide},
            "$or": [
                {"icuDischargeTime": {"$gte": start_dt}},
                {"dischargeTime": {"$gte": start_dt}},
                {"icuDischargeTime": None},
                {"icuDischargeTime": {"$exists": False}},
            ],
        },
        {
            "_id": 1, "hisPid": 1, "mrn": 1, "name": 1, "deptCode": 1,
            "icuAdmissionTime": 1, "icuDischargeTime": 1, "dischargeTime": 1,
            "clinicalDiagnosis": 1, "diagnosis": 1, "admissionDiagnosis": 1,
            "dischargedDiagnosis": 1, "diagnosisHistoryList": 1,
        },
    ).max_time_ms(15000).limit(200000))
    return {str(p["_id"]): p for p in patients}


def _patient_item(patient, pid: str) -> dict:
    return {
        "pid": pid,
        "mrn": patient.get("mrn", "") or patient.get("hisPid", ""),
        "patient_id": patient.get("hisPid", "") or patient.get("mrn", "") or pid[-8:],
        "name": patient.get("name", ""),
        "dept_code": patient.get("deptCode", ""),
    }


def _dedup_tri_tube_diagnoses(docs: list) -> list:
    from datetime import timedelta

    docs = sorted(docs, key=lambda d: (d.get("pid", ""), d.get("diseaseType", ""), d.get("diagnosisTime")))
    events = []
    current = None
    window = timedelta(days=TRI_TUBE_EVENT_WINDOW_DAYS)
    for doc in docs:
        dtm = doc.get("diagnosisTime")
        key = (doc.get("pid"), doc.get("diseaseType"))
        if not dtm:
            continue
        if (
            current
            and current["key"] == key
            and dtm - current["last_time"] <= window
        ):
            current["last_time"] = dtm
            current["duplicate_count"] += 1
            current["duplicates"].append(doc)
            continue
        current = {
            "key": key,
            "first": doc,
            "last_time": dtm,
            "duplicate_count": 1,
            "duplicates": [doc],
        }
        events.append(current)
    return events


def _tri_tube_numerator(db, pat_by_pid: dict, cfg: dict, start_dt, end_dt_wide) -> list:
    docs = list(db.diseaseDiagnosis.find(
        {
            "pid": {"$in": list(pat_by_pid.keys())},
            "diagnosisTime": {"$gte": start_dt, "$lte": end_dt_wide},
            "$or": [
                {"diseaseType": cfg["diseaseType"]},
                {"propertyType": cfg["propertyType"]},
            ],
        },
        {
            "_id": 1, "pid": 1, "diseaseType": 1, "propertyType": 1,
            "diagnosisTime": 1, "notes": 1, "lastEditUserId": 1,
        },
    ).sort("diagnosisTime", 1).max_time_ms(15000).limit(100000))

    patients = []
    for event in _dedup_tri_tube_diagnoses(docs):
        doc = event["first"]
        pid = doc.get("pid")
        patient = pat_by_pid.get(pid, {})
        item = _patient_item(patient, pid)
        item.update({
            "diagnosis_id": str(doc.get("_id", "")),
            "diseaseType": doc.get("diseaseType", ""),
            "propertyType": doc.get("propertyType", ""),
            "diagnosisTime": doc.get("diagnosisTime"),
            "notes": doc.get("notes", "") or "",
            "lastEditUserId": doc.get("lastEditUserId", "") or "",
            "duplicate_count": event["duplicate_count"],
            "dedup_basis": f"同一患者同一感染类型{TRI_TUBE_EVENT_WINDOW_DAYS}天事件窗内去重",
        })
        patients.append(item)
    return patients


def _ventilator_days(db, pat_by_pid: dict, start_dt, end_dt_wide) -> tuple[int, list]:
    day_rows = {}
    cursor = db.bedside.find(
        {
            "pid": {"$in": list(pat_by_pid.keys())},
            "code": "param_XiYangTuJing",
            "valid": True,
            "time": {"$gte": start_dt, "$lte": end_dt_wide},
            "$or": [
                {"strVal": {"$in": list(INVASIVE_VENT_VALUES)}},
                {"strVal": {"$regex": "有创呼吸机"}},
            ],
        },
        {"_id": 1, "pid": 1, "strVal": 1, "time": 1},
    ).sort("time", 1).max_time_ms(30000).limit(500000)
    for doc in cursor:
        if not _is_invasive_vent_value(doc.get("strVal")):
            continue
        t = doc.get("time")
        pid = doc.get("pid")
        if not t or not pid:
            continue
        key = (pid, t.date())
        if key in day_rows:
            continue
        patient = pat_by_pid.get(pid, {})
        item = _patient_item(patient, pid)
        item.update({
            "device_type": "有创呼吸机",
            "device_value": doc.get("strVal", ""),
            "device_day": t.strftime("%Y-%m-%d"),
            "record_time": t,
            "basis": "当日氧疗途径为有创机械通气",
        })
        day_rows[key] = item
    return len(day_rows), list(day_rows.values())


def _tube_days(db, pat_by_pid: dict, tube_types: set, start_dt, end_dt_wide, label: str) -> tuple[int, list]:
    day_rows = {}
    query = {
        "pid": {"$in": list(pat_by_pid.keys())},
        "type": {"$in": list(tube_types)},
        "startTime": {"$lte": end_dt_wide},
        "$or": [
            {"endTime": {"$gte": start_dt}},
            {"endTime": None},
            {"endTime": {"$exists": False}},
        ],
    }
    cursor = db.tubeExe.find(
        query,
        {"_id": 1, "pid": 1, "type": 1, "startTime": 1, "endTime": 1, "replace": 1},
    ).sort("startTime", 1).max_time_ms(30000).limit(300000)
    for doc in cursor:
        pid = doc.get("pid")
        start_time = doc.get("startTime")
        if not pid or not start_time:
            continue
        patient = pat_by_pid.get(pid, {})
        fallback_end = patient.get("icuDischargeTime") or patient.get("dischargeTime") or end_dt_wide
        end_time = doc.get("endTime") or fallback_end
        span_start = max(start_time, start_dt)
        span_end = min(end_time, end_dt_wide)
        if span_end < span_start:
            continue
        for day in _day_range(span_start, span_end):
            key = (pid, day)
            if key in day_rows:
                continue
            item = _patient_item(patient, pid)
            item.update({
                "tube_id": str(doc.get("_id", "")),
                "device_type": label,
                "tube_type": doc.get("type", ""),
                "device_day": day.strftime("%Y-%m-%d"),
                "tube_start": start_time,
                "tube_end": end_time,
                "basis": f"当日存在{label}留置记录",
            })
            day_rows[key] = item
    return len(day_rows), list(day_rows.values())


def _central_line_days(db, pat_by_pid: dict, start_dt, end_dt_wide) -> tuple[int, list]:
    included = {}
    excluded_by_patient_day = {}
    all_vascular_types = CENTRAL_VASCULAR_TUBE_TYPES | set(EXCLUDED_VASCULAR_TUBE_TYPES)
    query = {
        "pid": {"$in": list(pat_by_pid.keys())},
        "type": {"$in": list(all_vascular_types)},
        "startTime": {"$lte": end_dt_wide},
        "$or": [
            {"endTime": {"$gte": start_dt}},
            {"endTime": None},
            {"endTime": {"$exists": False}},
        ],
    }
    cursor = db.tubeExe.find(
        query,
        {"_id": 1, "pid": 1, "type": 1, "startTime": 1, "endTime": 1, "replace": 1},
    ).sort("startTime", 1).max_time_ms(30000).limit(300000)

    for doc in cursor:
        pid = doc.get("pid")
        tube_type = doc.get("type", "")
        start_time = doc.get("startTime")
        if not pid or not start_time:
            continue
        patient = pat_by_pid.get(pid, {})
        fallback_end = patient.get("icuDischargeTime") or patient.get("dischargeTime") or end_dt_wide
        end_time = doc.get("endTime") or fallback_end
        span_start = max(start_time, start_dt)
        span_end = min(end_time, end_dt_wide)
        if span_end < span_start:
            continue

        is_central = tube_type in CENTRAL_VASCULAR_TUBE_TYPES
        exclude_reason = "" if is_central else EXCLUDED_VASCULAR_TUBE_TYPES.get(tube_type, "非中心血管导管")
        evidence = {
            "tube_id": str(doc.get("_id", "")),
            "tube_type": tube_type,
            "tube_start": start_time,
            "tube_end": end_time,
            "included": is_central,
            "exclude_reason": exclude_reason,
        }
        for day in _day_range(span_start, span_end):
            key = (pid, day)
            if not is_central:
                excluded_by_patient_day.setdefault(key, []).append(evidence)
                continue

            item = included.get(key)
            if not item:
                item = _patient_item(patient, pid)
                item.update({
                    "tube_id": evidence["tube_id"],
                    "device_type": "中心血管导管",
                    "tube_type": tube_type,
                    "device_day": day.strftime("%Y-%m-%d"),
                    "tube_start": start_time,
                    "tube_end": end_time,
                    "included": True,
                    "exclude_reason": "",
                    "tube_ids": [evidence["tube_id"]],
                    "tube_types": [tube_type],
                    "included_segments": [evidence],
                    "excluded_evidence": [],
                    "dedup_basis": "患者-中心导管日：同一患者同一日存在≥1根中心导管计1日",
                    "basis": "当日存在中心血管导管留置记录",
                })
                included[key] = item
                continue

            item["tube_ids"].append(evidence["tube_id"])
            if tube_type not in item["tube_types"]:
                item["tube_types"].append(tube_type)
            item["included_segments"].append(evidence)
            if start_time < item["tube_start"]:
                item["tube_start"] = start_time
            if end_time > item["tube_end"]:
                item["tube_end"] = end_time
            item["tube_type"] = "、".join(item["tube_types"])
            item["tube_id"] = ",".join(item["tube_ids"])
            item["basis"] = f"当日存在{len(item['tube_ids'])}根中心血管导管，按患者-日去重计1日"

    for key, evidence_list in excluded_by_patient_day.items():
        if key in included:
            included[key]["excluded_evidence"].extend(evidence_list)

    return len(included), list(included.values())


def get_tri_tube_infection_data(code: str, dept_codes: list, start_date: str, end_date: str) -> dict:
    from datetime import datetime as dt

    cfg = TRI_TUBE_CONFIG[code]
    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    result = {
        "num_count": 0,
        "den_count": 0,
        "value": 0.0,
        "value_type": "permille",
        "num_patients": [],
        "den_patients": [],
        "note": "",
    }

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            pat_by_pid = _tri_tube_patient_scope(db, dept_codes, start_dt, end_dt_wide)
            if not pat_by_pid:
                continue
            num_patients = _tri_tube_numerator(db, pat_by_pid, cfg, start_dt, end_dt_wide)
            denom = cfg["denominator"]
            if denom == "ventilator":
                den_count, den_patients = _ventilator_days(db, pat_by_pid, start_dt, end_dt_wide)
            elif denom == "vascular":
                den_count, den_patients = _central_line_days(db, pat_by_pid, start_dt, end_dt_wide)
            else:
                den_count, den_patients = _tube_days(db, pat_by_pid, URINARY_TUBE_TYPES, start_dt, end_dt_wide, "导尿管")

            num_count = len(num_patients)
            result.update({
                "num_count": num_count,
                "den_count": den_count,
                "value": round(num_count / den_count * 1000, 2) if den_count > 0 else 0.0,
                "num_patients": num_patients,
                "den_patients": den_patients,
                "note": "" if den_count > 0 else "无导管/通气使用记录",
            })
            break
        except Exception as e:
            print(f"[{code}] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    return result


def get_icu16_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    return get_tri_tube_infection_data("ICU-16", dept_codes, start_date, end_date)


def get_icu17_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    return get_tri_tube_infection_data("ICU-17", dept_codes, start_date, end_date)


def get_cauti_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    return get_tri_tube_infection_data("CAUTI", dept_codes, start_date, end_date)


# ============================================================
# 三管感染疑似预警：仅作为医生确认线索，不计入正式分子
# ============================================================

TRI_TUBE_WARNING_TYPES = {
    "VAP": TRI_TUBE_CONFIG["ICU-16"],
    "CRBSI": TRI_TUBE_CONFIG["ICU-17"],
    "CAUTI": TRI_TUBE_CONFIG["CAUTI"],
}


def _safe_float(value):
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _confirmed_tri_tube_keys(db, pids: list, start_dt, end_dt_wide) -> set:
    docs = db.diseaseDiagnosis.find(
        {
            "pid": {"$in": pids},
            "diagnosisTime": {"$gte": start_dt, "$lte": end_dt_wide},
            "propertyType": {"$in": [cfg["propertyType"] for cfg in TRI_TUBE_WARNING_TYPES.values()]},
        },
        {"pid": 1, "propertyType": 1},
    ).max_time_ms(10000).limit(100000)
    return {(d.get("pid"), d.get("propertyType")) for d in docs}


def _fever_evidence(db, pids: list, start_dt, end_dt_wide) -> dict:
    evidence = {}
    if "temperatureData" not in db.list_collection_names():
        return evidence
    for doc in db.temperatureData.find(
        {
            "pid": {"$in": pids},
            "record_time": {"$gte": start_dt, "$lte": end_dt_wide},
        },
        {"pid": 1, "record_time": 1, "Temperature": 1},
    ).sort("record_time", -1).max_time_ms(15000).limit(200000):
        temp = _safe_float(doc.get("Temperature"))
        if temp is not None and temp >= 38:
            evidence.setdefault(doc.get("pid"), []).append({
                "type": "发热",
                "time": _fmt_dt(doc.get("record_time")),
                "value": f"T={temp}",
            })
    return evidence


def _wbc_evidence(db, pids: list, start_dt, end_dt_wide) -> dict:
    evidence = {}
    if "criticalValue" not in db.list_collection_names():
        return evidence
    patient_id_alias = set(pids)
    for doc in db.criticalValue.find(
        {
            "publishTime": {"$gte": start_dt, "$lte": end_dt_wide},
            "$or": [
                {"pid": {"$in": list(patient_id_alias)}},
                {"lisItem": {"$regex": "白细胞|WBC"}},
                {"bigItemName": {"$regex": "血常规"}},
            ],
        },
        {"pid": 1, "lisItem": 1, "value": 1, "publishTime": 1, "bigItemName": 1},
    ).sort("publishTime", -1).max_time_ms(15000).limit(50000):
        text = f"{doc.get('lisItem', '')} {doc.get('value', '')} {doc.get('bigItemName', '')}"
        if "白细胞" not in text and "WBC" not in text.upper():
            continue
        evidence.setdefault(doc.get("pid"), []).append({
            "type": "WBC异常危急值",
            "time": _fmt_dt(doc.get("publishTime")),
            "value": text[:80],
        })
    return evidence


def _sputum_evidence(db, pids: list, start_dt, end_dt_wide) -> dict:
    evidence = {}
    sputum_codes = ["param_痰液护理", "param_tanColor", "param_tanLiang", "param_tanYeFenJi"]
    param_names = {
        d.get("code"): d.get("name")
        for d in db.configParam.find(
            {"code": {"$in": sputum_codes}},
            {"code": 1, "name": 1, "_id": 0},
        ).max_time_ms(10000)
        if d.get("code") and d.get("name")
    }
    for doc in db.bedside.find(
        {
            "pid": {"$in": pids},
            "valid": True,
            "time": {"$gte": start_dt, "$lte": end_dt_wide},
            "code": {"$in": sputum_codes},
        },
        {"pid": 1, "code": 1, "strVal": 1, "time": 1},
    ).sort("time", -1).max_time_ms(15000).limit(100000):
        text = str(doc.get("strVal") or "").strip()
        if not text:
            continue
        param_name = param_names.get(doc.get("code")) or "痰液护理"
        evidence.setdefault(doc.get("pid"), []).append({
            "type": "痰液护理记录",
            "time": _fmt_dt(doc.get("time")),
            "value": f"{param_name}={text}"[:80],
        })
    return evidence


SEPSIS_INFECTION_KEYWORDS = {
    "感染", "肺炎", "脓毒", "败血", "菌血", "腹膜炎", "脓肿", "化脓",
    "胆管炎", "肾盂肾炎", "尿路感染", "泌尿系感染", "腹腔感染",
}
SEPSIS_BEDSIDE_NAME_RULES = {
    "resp_rate": ("呼吸频率", "呼吸次数", "呼吸"),
    "sbp": ("收缩压", "高压"),
    "map": ("平均动脉压", "MAP"),
    "consciousness": ("意识", "GCS", "格拉斯哥"),
    "urine_output": ("尿量",),
    "vasopressor": ("升压药", "去甲肾上腺素", "多巴胺", "肾上腺素", "血管活性"),
}
SEPSIS_EXAM_CODES = {
    "wbc": {"WBC", "WBCJS"},
    "crp": {"CRP", "sCRP"},
    "pct": {"PCT1"},
    "lactate": {"LAC", "LACT", "LAC1", "LAC2"},
}


def _patient_diagnosis_text(patient: dict) -> str:
    parts = []
    for key in ("clinicalDiagnosis", "diagnosis", "admissionDiagnosis", "dischargedDiagnosis"):
        if patient.get(key):
            parts.append(str(patient.get(key)))
    for item in patient.get("diagnosisHistoryList") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("diagnosis") or item.get("name") or ""))
        elif item:
            parts.append(str(item))
    return "；".join(p for p in parts if p)


def _latest_numeric_bedside(db, pids: list, codes: list, start_dt, end_dt_wide) -> dict:
    result = {}
    if not codes:
        return result
    for doc in db.bedside.find(
        {
            "pid": {"$in": pids},
            "code": {"$in": codes},
            "valid": True,
            "time": {"$gte": start_dt, "$lte": end_dt_wide},
        },
        {"pid": 1, "strVal": 1, "time": 1},
    ).sort("time", -1).max_time_ms(20000).limit(200000):
        pid = doc.get("pid")
        if pid in result:
            continue
        val = _safe_float(doc.get("strVal"))
        if val is not None:
            result[pid] = {"value": val, "time": doc.get("time")}
    return result


def _latest_text_bedside(db, pids: list, codes: list, start_dt, end_dt_wide) -> dict:
    result = {}
    if not codes:
        return result
    for doc in db.bedside.find(
        {
            "pid": {"$in": pids},
            "code": {"$in": codes},
            "valid": True,
            "time": {"$gte": start_dt, "$lte": end_dt_wide},
        },
        {"pid": 1, "strVal": 1, "time": 1},
    ).sort("time", -1).max_time_ms(20000).limit(200000):
        pid = doc.get("pid")
        text = str(doc.get("strVal") or "").strip()
        if pid not in result and text:
            result[pid] = {"value": text, "time": doc.get("time")}
    return result


def _sepsis_bedside_codes(db) -> dict:
    codes = {key: [] for key in SEPSIS_BEDSIDE_NAME_RULES}
    for doc in db.configParam.find(
        {},
        {"code": 1, "name": 1, "_id": 0},
    ).max_time_ms(10000).limit(20000):
        code = doc.get("code")
        text = f"{doc.get('name', '')} {code or ''}"
        if not code:
            continue
        for key, keywords in SEPSIS_BEDSIDE_NAME_RULES.items():
            if any(kw.lower() in text.lower() for kw in keywords):
                codes[key].append(code)
    codes["temperature"] = list(set(codes.get("temperature", []) + ["param_T"]))
    codes["consciousness"] = list(set(codes.get("consciousness", []) + ["param_score_gcs_obs"]))
    return codes


def _sepsis_exam_values(db_dc, hispids: list, start_dt, end_dt_wide) -> dict:
    result = {}
    if not hispids:
        return result
    try:
        exams = list(db_dc["VI_ICU_EXAM"].find(
            {"pid": {"$in": hispids}, "collectTime": {"$gte": start_dt, "$lte": end_dt_wide}},
            {"pid": 1, "examID": 1, "reportID": 1, "collectTime": 1},
        ).max_time_ms(20000).limit(200000))
        exam_ids = []
        exam_info = {}
        for e in exams:
            eid = e.get("examID") or e.get("reportID")
            if not eid:
                continue
            exam_ids.append(eid)
            exam_info[str(eid)] = {"hisPid": e.get("pid"), "time": e.get("collectTime")}
        if not exam_ids:
            return result
        target_codes = set().union(*SEPSIS_EXAM_CODES.values())
        for item in db_dc["VI_ICU_EXAM_ITEM"].find(
            {"examID": {"$in": exam_ids}, "itemCode": {"$in": list(target_codes)}},
            {"examID": 1, "itemCode": 1, "itemName": 1, "itemValue": 1, "authTime": 1},
        ).sort("authTime", -1).max_time_ms(20000).limit(300000):
            info = exam_info.get(str(item.get("examID")))
            if not info:
                continue
            hispid = info.get("hisPid")
            val = _clean_test_value(item.get("itemValue"))
            if not hispid or val is None:
                continue
            code = item.get("itemCode")
            item_name = str(item.get("itemName") or "")
            metric = None
            for key, code_set in SEPSIS_EXAM_CODES.items():
                if code in code_set:
                    metric = key
                    break
            if metric == "pct" and "血小板" in item_name:
                continue
            if not metric:
                continue
            patient_values = result.setdefault(str(hispid), {})
            if metric not in patient_values:
                patient_values[metric] = {"value": val, "time": info.get("time") or item.get("authTime")}
    except Exception:
        return result
    return result


def _sepsis_lactate_from_bga(db, pids: list, start_dt, end_dt_wide) -> dict:
    result = {}
    collections = db.list_collection_names()
    coll_name = "BGATemp" if "BGATemp" in collections else "bGATemp"
    if coll_name not in collections:
        return result
    try:
        for doc in db[coll_name].find(
            {
                "eventExe.pid": {"$in": pids},
                "eventExe.startTime": {"$gte": start_dt, "$lte": end_dt_wide},
                "bedsides": {"$elemMatch": {"code": "param_bg_Lac"}},
            },
            {"eventExe.pid": 1, "eventExe.startTime": 1, "bedsides": 1},
        ).sort("eventExe.startTime", -1).max_time_ms(20000).limit(200000):
            pid = (doc.get("eventExe") or {}).get("pid")
            if not pid or pid in result:
                continue
            for item in doc.get("bedsides") or []:
                if item.get("code") != "param_bg_Lac":
                    continue
                val = _clean_test_value(item.get("strVal") or item.get("value") or item.get("val"))
                if val is not None:
                    result[pid] = {
                        "value": val,
                        "time": (doc.get("eventExe") or {}).get("startTime"),
                    }
                    break
    except Exception:
        return result
    return result


def _sepsis_rule_candidate(ctx: dict) -> bool:
    diagnosis = str(ctx.get("diagnosis") or "")
    infection = any(kw in diagnosis for kw in SEPSIS_INFECTION_KEYWORDS)
    temp = _safe_float(ctx.get("temperature"))
    rr = _safe_float(ctx.get("resp_rate"))
    sbp = _safe_float(ctx.get("sbp"))
    lactate = _safe_float(ctx.get("lactate"))
    wbc = _safe_float(ctx.get("wbc"))
    pct = _safe_float(ctx.get("pct"))
    crp = _safe_float(ctx.get("crp"))
    return (
        infection
        or (temp is not None and (temp >= 38.3 or temp < 36))
        or (rr is not None and rr >= 22)
        or (sbp is not None and sbp <= 100)
        or (lactate is not None and lactate >= 2)
        or (wbc is not None and (wbc > WBC_HIGH or wbc < WBC_LOW))
        or (pct is not None and pct > PCT_HIGH)
        or (crp is not None and crp > CRP_HIGH)
    )


def get_sepsis_alert_warnings(dept_codes: list, start_date: str, end_date: str, limit: int = 30) -> list:
    from ai_analyzer import classify_sepsis_alert_with_ai
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    warnings = []

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            pat_by_pid = _tri_tube_patient_scope(db, dept_codes, start_dt, end_dt_wide)
            if not pat_by_pid:
                continue
            pids = list(pat_by_pid.keys())
            hispids = [str(p.get("hisPid")) for p in pat_by_pid.values() if p.get("hisPid")]
            codes = _sepsis_bedside_codes(db)
            temperature = _latest_numeric_bedside(db, pids, codes.get("temperature", []), start_dt, end_dt_wide)
            resp_rate = _latest_numeric_bedside(db, pids, codes.get("resp_rate", []), start_dt, end_dt_wide)
            sbp = _latest_numeric_bedside(db, pids, codes.get("sbp", []), start_dt, end_dt_wide)
            map_values = _latest_numeric_bedside(db, pids, codes.get("map", []), start_dt, end_dt_wide)
            consciousness = _latest_text_bedside(db, pids, codes.get("consciousness", []), start_dt, end_dt_wide)
            urine_output = _latest_text_bedside(db, pids, codes.get("urine_output", []), start_dt, end_dt_wide)
            vasopressor = _latest_text_bedside(db, pids, codes.get("vasopressor", []), start_dt, end_dt_wide)
            lactate_bga = _sepsis_lactate_from_bga(db, pids, start_dt, end_dt_wide)

            exam_values = {}
            try:
                db_dc = get_datacenter_client()["DataCenter"]
                exam_values = _sepsis_exam_values(db_dc, hispids, start_dt, end_dt_wide)
            except Exception:
                exam_values = {}

            scored = []
            for pid, patient in pat_by_pid.items():
                hispid = str(patient.get("hisPid") or "")
                exams = exam_values.get(hispid, {})
                ctx = {
                    "hisPid": hispid or patient.get("mrn") or pid,
                    "sample_time": _fmt_dt(end_dt_wide),
                    "diagnosis": _patient_diagnosis_text(patient) or "未知",
                    "temperature": (temperature.get(pid) or {}).get("value", "?"),
                    "resp_rate": (resp_rate.get(pid) or {}).get("value", "?"),
                    "sbp": (sbp.get(pid) or {}).get("value", "?"),
                    "map": (map_values.get(pid) or {}).get("value", "?"),
                    "consciousness": (consciousness.get(pid) or {}).get("value", "?"),
                    "wbc": (exams.get("wbc") or {}).get("value", "?"),
                    "pct": (exams.get("pct") or {}).get("value", "?"),
                    "crp": (exams.get("crp") or {}).get("value", "?"),
                    "lactate": (lactate_bga.get(pid) or exams.get("lactate") or {}).get("value", "?"),
                    "urine_output": (urine_output.get(pid) or {}).get("value", "?"),
                    "vasopressor": (vasopressor.get(pid) or {}).get("value", "?"),
                }
                if not _sepsis_rule_candidate(ctx):
                    continue
                priority = 0
                for key in ("lactate", "resp_rate", "sbp", "temperature", "wbc", "pct", "crp"):
                    priority += 1 if ctx.get(key) != "?" else 0
                scored.append((priority, pid, patient, ctx))

            for _, pid, patient, ctx in sorted(scored, reverse=True)[:limit]:
                result = classify_sepsis_alert_with_ai(ctx)
                if not result or result.get("risk") == "low":
                    continue
                item = _patient_item(patient, pid)
                qsofa = result.get("qsofa")
                evidence = [{"type": "判定依据", "value": result.get("reason", "")}]
                if qsofa is not None:
                    evidence.insert(0, {"type": "qSOFA", "value": str(qsofa)})
                else:
                    evidence.insert(0, {"type": "qSOFA", "value": "待评估 / 解析失败，请人工复核"})
                evidence.append({"type": "分诊建议", "value": result.get("action", "")})
                item.update({
                    "type": "脓毒症早期预警",
                    "risk": result.get("risk", "unknown"),
                    "qsofa": qsofa,
                    "suspect_sepsis": result.get("suspect_sepsis", False),
                    "basis": result.get("reason", ""),
                    "action": result.get("action", ""),
                    "by": result.get("by", "ai"),
                    "evaluated": result.get("evaluated", result.get("by") != "fallback"),
                    "confidence": 0.9 if result.get("risk") == "high" else 0.7,
                    "evidence": evidence,
                })
                warnings.append(item)
            break
        except Exception as e:
            print(f"[sepsis-alert] Error in db {db_name}: {e}")
            continue

    risk_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(warnings, key=lambda x: (risk_rank.get(x.get("risk"), 9), -float(x.get("confidence", 0))))


def _long_vent_patients(db, pat_by_pid: dict, start_dt, end_dt_wide, hours: int) -> dict:
    records = defaultdict(list)
    for doc in db.bedside.find(
        {
            "pid": {"$in": list(pat_by_pid.keys())},
            "code": "param_XiYangTuJing",
            "valid": True,
            "time": {"$gte": start_dt, "$lte": end_dt_wide},
            "$or": [
                {"strVal": {"$in": list(INVASIVE_VENT_VALUES)}},
                {"strVal": {"$regex": "有创呼吸机"}},
            ],
        },
        {"pid": 1, "strVal": 1, "time": 1},
    ).sort("time", 1).max_time_ms(30000).limit(300000):
        if _is_invasive_vent_value(doc.get("strVal")):
            records[doc.get("pid")].append(doc)
    result = {}
    for pid, docs in records.items():
        first = docs[0].get("time")
        last = docs[-1].get("time")
        if first and last and (last - first).total_seconds() >= hours * 3600:
            result[pid] = {
                "first_time": first,
                "last_time": last,
                "value": docs[0].get("strVal"),
            }
    return result


def _long_tube_patients(db, pat_by_pid: dict, tube_types: set, start_dt, end_dt_wide, hours: int) -> dict:
    result = {}
    for doc in db.tubeExe.find(
        {
            "pid": {"$in": list(pat_by_pid.keys())},
            "type": {"$in": list(tube_types)},
            "startTime": {"$lte": end_dt_wide},
            "$or": [
                {"endTime": {"$gte": start_dt}},
                {"endTime": None},
                {"endTime": {"$exists": False}},
            ],
        },
        {"pid": 1, "type": 1, "startTime": 1, "endTime": 1},
    ).sort("startTime", 1).max_time_ms(30000).limit(200000):
        pid = doc.get("pid")
        st = doc.get("startTime")
        if not pid or not st:
            continue
        patient = pat_by_pid.get(pid, {})
        et = doc.get("endTime") or patient.get("icuDischargeTime") or patient.get("dischargeTime") or end_dt_wide
        if et and (min(et, end_dt_wide) - max(st, start_dt)).total_seconds() >= hours * 3600:
            result.setdefault(pid, {
                "first_time": st,
                "last_time": et,
                "value": doc.get("type", ""),
            })
    return result


def get_tri_tube_suspected_warnings(dept_codes: list, start_date: str, end_date: str, min_hours: int = 48) -> list:
    from datetime import datetime as dt
    from collections import defaultdict

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    warnings = []

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            pat_by_pid = _tri_tube_patient_scope(db, dept_codes, start_dt, end_dt_wide)
            if not pat_by_pid:
                continue
            pids = list(pat_by_pid.keys())
            confirmed = _confirmed_tri_tube_keys(db, pids, start_dt, end_dt_wide)
            fever = _fever_evidence(db, pids, start_dt, end_dt_wide)
            wbc = _wbc_evidence(db, pids, start_dt, end_dt_wide)
            sputum = _sputum_evidence(db, pids, start_dt, end_dt_wide)

            long_vent = _long_vent_patients(db, pat_by_pid, start_dt, end_dt_wide, min_hours)
            long_vascular = _long_tube_patients(db, pat_by_pid, VASCULAR_TUBE_TYPES, start_dt, end_dt_wide, min_hours)
            long_urinary = _long_tube_patients(db, pat_by_pid, URINARY_TUBE_TYPES, start_dt, end_dt_wide, min_hours)

            def append_warning(pid, warn_type, device_info, extra_evidence):
                cfg = TRI_TUBE_WARNING_TYPES[warn_type]
                if (pid, cfg["propertyType"]) in confirmed:
                    return
                patient = pat_by_pid.get(pid, {})
                evidence = [{
                    "type": "装置留置超过阈值",
                    "time": f"{_fmt_dt(device_info.get('first_time'))} ~ {_fmt_dt(device_info.get('last_time'))}",
                    "value": f"{device_info.get('value')} > {min_hours}h",
                }]
                evidence.extend(extra_evidence[:5])
                if len(evidence) < 2:
                    return
                confidence = min(0.95, 0.45 + 0.15 * (len(evidence) - 1))
                item = _patient_item(patient, pid)
                item.update({
                    "suspect_type": warn_type,
                    "diseaseType": cfg["diseaseType"],
                    "propertyType": cfg["propertyType"],
                    "confidence": round(confidence, 2),
                    "evidence": evidence,
                    "suggestion": "AI疑似预警，需医生确认后才写入正式诊断",
                })
                warnings.append(item)

            for pid, info in long_vent.items():
                append_warning(pid, "VAP", info, fever.get(pid, []) + wbc.get(pid, []) + sputum.get(pid, []))
            for pid, info in long_vascular.items():
                append_warning(pid, "CRBSI", info, fever.get(pid, []) + wbc.get(pid, []))
            for pid, info in long_urinary.items():
                append_warning(pid, "CAUTI", info, fever.get(pid, []) + wbc.get(pid, []))
            break
        except Exception as e:
            print(f"[tri-tube-warning] Error in db {db_name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    return sorted(warnings, key=lambda x: x.get("confidence", 0), reverse=True)


def confirm_tri_tube_warning(pid: str, suspect_type: str, diagnosis_time, user_id: str, notes: str = "") -> dict:
    cfg = TRI_TUBE_WARNING_TYPES.get(suspect_type)
    if not cfg:
        raise ValueError("unsupported suspect_type")
    from bson import ObjectId
    for db_name in BED_DB_NAMES:
        db = get_client(db_name)[db_name]
        patient = None
        if len(pid) == 24:
            try:
                patient = db.patient.find_one({"_id": ObjectId(pid)})
            except Exception:
                patient = None
        if not patient:
            patient = db.patient.find_one({"hisPid": pid}) or db.patient.find_one({"mrn": pid})
        if not patient:
            continue
        normalized_pid = str(patient["_id"])
        doc = {
            "pid": normalized_pid,
            "diseaseType": cfg["diseaseType"],
            "propertyType": cfg["propertyType"],
            "diagnosisTime": diagnosis_time,
            "notes": notes or "AI疑似预警经医生确认录入",
            "lastEditUserId": user_id,
        }
        inserted = db.diseaseDiagnosis.insert_one(doc)
        return {"inserted_id": str(inserted.inserted_id), **doc}
    raise ValueError("patient not found")


# ============================================================
# 连接测试
# ============================================================
def test_connections() -> dict:
    """测试所有数据库连接，返回状态"""
    results = {}
    for db_name in ["SmartCare_4y", "SmartCare", "DataCenter", "DataCenter_4y"]:
        try:
            client = get_client(db_name)
            client[db_name].command("ping")
            results[db_name] = "OK"
        except Exception as e:
            results[db_name] = str(e)
    return results
