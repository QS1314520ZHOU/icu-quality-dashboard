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
