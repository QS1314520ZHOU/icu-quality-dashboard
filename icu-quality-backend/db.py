# db.py - MongoDB 连接 & ICU-01 分母逻辑（从 .env 读取配置）
import os
from pathlib import Path
from pymongo import MongoClient
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


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
    return get_client("DataCenter")


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
    non_inv = routes & O2_ROUTE_NON_INVASIVE
    if non_inv:
        return False, routes, f"无创途径({','.join(non_inv)})"

    # 有创命中 → 纳入
    inv = routes & O2_ROUTE_INVASIVE
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
                         "bedsides": {"$elemMatch": {"code": "param_bg_P/Fratio", "valid": "valid"}}},
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
                for item in bga.get("bedsides", []):
                    if item.get("code") == "param_bg_P/Fratio" and item.get("valid") == "valid":
                        pf_ratio = item.get("fVal"); break
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
                routes = set(o2_raw.replace("、", ",").replace("，", ",").split(","))
                routes = {r.strip() for r in routes if r.strip()}

                inv = routes & INVASIVE_ROUTES
                if inv and peep_val >= peep_min and pf_ratio < invasive_pf:
                    arm = "有创"
                elif "无创" in routes and peep_val >= peep_min and pf_ratio <= noninvasive_pf:
                    arm = "无创"
                elif "高流量" in routes:
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
    "弹力袜", "压力袜", "梯度压力袜", "抗血栓袜", "GCS",
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
        client = get_datacenter_client()
        db = client["DataCenter"]

        # 构建正则
        drug_pattern = "|".join(DRUG_DVT_KEYWORDS)
        mech_pattern = "|".join(MECH_DVT_KEYWORDS)
        filter_pattern = "|".join(FILTER_KEYWORDS)
        flush_pattern = "|".join(FLUSH_EXCLUDE_KEYWORDS)
        all_pattern = "|".join(DRUG_DVT_KEYWORDS + MECH_DVT_KEYWORDS + FILTER_KEYWORDS)

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
                "status": "已执行",
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
# ICU-06：抗菌药物前病原学送检率
# ============================================================

ANTIBIOTIC_KEYWORDS = [
    # β-内酰胺类
    "头孢", "西林", "青霉素", "培南", "曲松", "他啶", "吡肟", "西丁",
    "哌酮", "氨曲南", "头霉素", "碳青霉烯", "亚胺培南", "厄他培南",
    "克拉维酸", "舒巴坦", "他唑巴坦", "巴坦",
    # 氟喹诺酮类
    "沙星",
    # 氨基糖苷类
    "米星", "卡星", "庆大", "妥布",
    # 大环内酯类
    "红霉素", "阿奇", "克拉",
    # 糖肽类/环脂肽类
    "万古", "拉宁", "达托", "替考",
    # 噁唑烷酮类
    "利奈", "唑胺",
    # 四环素类
    "环素",
    # 硝基咪唑类
    "硝唑", "替硝",
    # 抗真菌类
    "康唑", "芬净", "两性霉素",
    # 其他
    "克林", "林可", "磷霉素", "夫西地酸", "莫匹罗星",
]

# 病原学送检关键词（血培养、痰培养、尿培养等）
PATHOGEN_TEST_KEYWORDS = [
    "血培养", "痰培养", "尿培养", "细菌培养", "真菌培养",
    "涂片", "革兰染色", "抗酸染色", "G试验", "GM试验",
    "降钙素原", "PCT", "内毒素", "病原学", "微生物",
]

# VI_ICU_EXAM_ITEM 病原学相关 itemName 关键词
PATHOGEN_ITEM_KEYWORDS = [
    "降钙素原", "内毒素", "真菌", "隐球菌", "革兰",
    "结核分枝杆菌核酸检测", "微生物", "细菌",
    "G试验", "GM试验",
]


def get_icu06_data(dept_codes: list, start_date: str, end_date: str) -> dict:
    """
    ICU-06：抗菌药物前病原学送检率。

    分母：SmartCare.drugExe 统计期内有抗菌药物给药记录的患者。
          抗菌药判定：drugList.code ∈ configDrug.classification='抗生素' 的 code 集合。
          首剂时间取 drugExe.startTime（实际给药时间，比 orderTime 更准）。

    分子：分母患者中，首次送检时间 ≤ 首剂抗菌药时间的人。
          送检源A：DataCenter.VI_ICU_ZYYZ, yaoType='检验', orderName 含培养类关键词, 时间用 orderTime。
          送检源B：DataCenter.VI_ICU_EXAM_ITEM (排除降钙素原) + VI_ICU_EXAM.collectTime。
          首次送检时间 = min(A最早, B最早)。

    跨库对齐：SmartCare patient.hisPid ↔ DataCenter hisPid (已验证 100% 匹配)。
    返回：{den_count, num_count, den_patients, num_patients}
    """
    from datetime import datetime as dt

    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)

    result = {"den_count": 0, "num_count": 0, "den_patients": [], "num_patients": []}

    # 培养类关键词（源A）
    CULTURE_KEYWORDS = "血培养|痰培养|尿培养|细菌培养|真菌培养|涂片|革兰染色|抗酸染色|G试验|GM试验"
    # 源B 排除项
    EXCLUDE_ITEM = "降钙素原"

    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]

            # ---- 1. 取抗生素 drug codes ----
            abx_codes = [d["code"] for d in db.configDrug.find(
                {"classification": "抗生素"}, {"code": 1}
            )]
            if not abx_codes:
                continue

            # ---- 2. 在科患者 ----
            patients = list(db.patient.find(
                {"deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"},
                 "icuAdmissionTime": {"$lte": end_dt_wide},
                 "$or": [{"icuDischargeTime": {"$gte": start_dt}}, {"icuDischargeTime": None},
                         {"icuDischargeTime": {"$exists": False}}]},
                {"_id": 1, "hisPid": 1, "mrn": 1, "name": 1},
            ))
            pid_set = {str(p["_id"]) for p in patients}
            pat_by_pid = {str(p["_id"]): p for p in patients}
            if not pid_set:
                continue

            # ---- 3. 分母：drugExe 抗菌药执行记录，取首剂 startTime ----
            abx_docs = list(db.drugExe.find(
                {"pid": {"$in": list(pid_set)}, "status": "finished",
                 "drugList.code": {"$in": abx_codes},
                 "startTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                {"pid": 1, "startTime": 1},
            ).sort("startTime", 1))

            abx_time = {}  # pid -> first antibiotic administration time
            for d in abx_docs:
                pid = d.get("pid", "")
                t = d.get("startTime")
                if pid and t and pid not in abx_time:
                    abx_time[pid] = t

            result["den_count"] = len(abx_time)
            if not abx_time:
                continue

            # ---- 4. 分子：送检时间 < 首剂抗生素时间 ----
            test_time = {}  # pid -> earliest test time

            # hisPid 映射（跨库对齐键）
            smart_pid_by_hispid = {}
            for spid, p in pat_by_pid.items():
                hp = p.get("hisPid", "")
                if hp:
                    smart_pid_by_hispid[hp] = spid

            try:
                dc = get_datacenter_client()["DataCenter"]
                hispids = list(smart_pid_by_hispid.keys())
                if not hispids:
                    continue

                # 源A: VI_ICU_ZYYZ (培养类医嘱, yaoType='检验')
                #   ZYYZ.pid == patient.hisPid (已验证 10/10)
                culture_orders = list(dc["VI_ICU_ZYYZ"].find(
                    {"pid": {"$in": hispids}, "status": "已执行",
                     "yaoType": "检验",
                     "orderName": {"$regex": CULTURE_KEYWORDS, "$options": "i"},
                     "orderTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                    {"pid": 1, "orderTime": 1},
                ).sort("orderTime", 1))
                for o in culture_orders:
                    hp = o.get("pid", "")  # pid 即 hisPid
                    t = o.get("orderTime")
                    spid = smart_pid_by_hispid.get(hp)
                    if spid and t and (spid not in test_time or t < test_time[spid]):
                        test_time[spid] = t

                # 源B: VI_ICU_EXAM_ITEM (排除降钙素原) + VI_ICU_EXAM.collectTime
                exam_items = list(dc["VI_ICU_EXAM_ITEM"].find(
                    {"hisPid": {"$in": hispids},
                     "itemName": {"$not": {"$regex": EXCLUDE_ITEM}},
                     "authTime": {"$gte": start_dt, "$lte": end_dt_wide}},
                    {"hisPid": 1, "examID": 1, "authTime": 1},
                ).sort("authTime", 1))
                if exam_items:
                    eids = list(set(i["examID"] for i in exam_items if i.get("examID")))
                    exam_coll = {}  # examID -> collectTime
                    if eids:
                        for e in dc["VI_ICU_EXAM"].find(
                            {"reportID": {"$in": eids}},
                            {"reportID": 1, "collectTime": 1},
                        ):
                            exam_coll[e["reportID"]] = e.get("collectTime")
                    for item in exam_items:
                        hp = item.get("hisPid", "")
                        ct = exam_coll.get(item.get("examID", "")) or item.get("authTime")
                        spid = smart_pid_by_hispid.get(hp)
                        if spid and ct and (spid not in test_time or ct < test_time[spid]):
                            test_time[spid] = ct

            except Exception:
                pass

            # ---- 5. 计算分子 ----
            num_pids = set()
            for pid, abx_t in abx_time.items():
                tt = test_time.get(pid)
                if tt and tt <= abx_t:
                    num_pids.add(pid)
            result["num_count"] = min(len(num_pids), result["den_count"])

            result["den_patients"] = [
                {"pid": pid, "mrn": pat_by_pid[pid].get("mrn", "") or pat_by_pid[pid].get("hisPid", ""),
                 "name": pat_by_pid[pid].get("name", "")}
                for pid in abx_time
            ]
            result["num_patients"] = [
                {"pid": pid, "mrn": pat_by_pid[pid].get("mrn", "") or pat_by_pid[pid].get("hisPid", ""),
                 "name": pat_by_pid[pid].get("name", "")}
                for pid in num_pids
            ]
            break

        except Exception as e:
            print(f"[ICU-06] Error: {e}")
            continue

    return result


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
