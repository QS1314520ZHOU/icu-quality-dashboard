"""
MongoDB → SOFA 评分器数据适配层。
从原始集合（bGATemp, bedside, drugExe, score, VI_ICU_EXAM_ITEM）提取数据，
转换为 compute_sofa_classic / compute_sofa2 所需的标准化格式。

铁律:
  - 本模块只做数据提取和格式转换，不做评分计算
  - 缺失数据返回空列表，不得编造观测值
  - 所有 datetime 统一为 timezone-aware (UTC)
  - 单位字段如实传递，不做跨单位转换（由评分器负责）
  - 数据库 naive 时间视为 Asia/Shanghai，显式本地化后转 UTC
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 医院时区: 默认 Asia/Shanghai
_HOSPITAL_TZ = ZoneInfo("Asia/Shanghai")


def _aware(dt: datetime) -> datetime:
    """
    确保时区感知。
    数据库 naive 时间视为 Asia/Shanghai，显式本地化后转 UTC。
    禁止直接 replace(tzinfo=UTC) — 那会把本地时间错误地标为 UTC。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # naive 时间 → 假设为 Asia/Shanghai → 转 UTC
        return dt.replace(tzinfo=_HOSPITAL_TZ).astimezone(timezone.utc)
    return dt


def _safe_float(val) -> Optional[float]:
    """安全转 float，失败返回 None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ============================================================
# 观测数据提取
# ============================================================

def _fetch_bga_observations(
    sc, mrn: str, eval_time: datetime, lookback_hours: int = 24
) -> List[dict]:
    """
    从 bGATemp 提取血气分析观测。
    返回标准化观测列表 [{code, value_number, unit, observed_at, item_code, source}]。
    """
    observations = []
    window_start = eval_time - timedelta(hours=lookback_hours)

    # bGATemp 结构: 文档有 mrn 和 bedsides 数组
    # bedsides 中每项: {code, fVal, strVal, time, valid, unit}
    # 注意: param_bg_pAO2 和 param_bg_po2 是同一字段的不同写法
    BGA_CODE_MAP = {
        "param_bg_P/Fratio": "P/F_ratio",
        "param_bg_Lac": "Lactate",
        "param_bg_pAO2": "PaO2",
        "param_bg_po2": "PaO2",   # 小写变体
        "param_bg_FiO2": "FiO2",
        "param_bg_pH": "pH",
        "param_bg_SpO2": "SpO2",
        "param_bg_pCO2": "PaCO2",
    }
    # 单位映射 (bGATemp bedside 条目通常不带 unit 字段，用已知单位)
    BGA_UNIT_MAP = {
        "P/F_ratio": "mmHg",
        "Lactate": "mmol/L",
        "PaO2": "mmHg",
        "FiO2": "%",
        "pH": "",
        "SpO2": "%",
        "PaCO2": "mmHg",
    }

    try:
        bga_docs = list(sc.bGATemp.find(
            {"mrn": mrn,
             "bedsides": {"$elemMatch": {
                 "code": {"$in": list(BGA_CODE_MAP.keys())},
                 "valid": "valid",
                 "time": {"$gte": window_start, "$lte": eval_time},
             }}},
            {"bedsides": 1}
        ).max_time_ms(15000).limit(500))

        for doc in bga_docs:
            for bs in doc.get("bedsides", []):
                code_raw = bs.get("code", "")
                if code_raw not in BGA_CODE_MAP:
                    continue
                if bs.get("valid") != "valid":
                    continue
                ts = bs.get("time")
                if not isinstance(ts, datetime):
                    continue
                # 确保时区一致后再比较
                ts_aware = _aware(ts)
                ws_aware = _aware(window_start)
                ev_aware = _aware(eval_time)
                if ts_aware < ws_aware or ts_aware > ev_aware:
                    continue
                val = _safe_float(bs.get("fVal"))
                if val is None:
                    continue
                std_code = BGA_CODE_MAP[code_raw]
                # 优先使用 bedside 条目自带的 unit，否则使用已知单位映射
                raw_unit = (bs.get("unit") or "").strip()
                unit = raw_unit if raw_unit else BGA_UNIT_MAP.get(std_code, "")
                observations.append({
                    "code": std_code,
                    "value_number": val,
                    "unit": unit,
                    "observed_at": _aware(ts),
                    "item_code": code_raw,       # 原始床旁机代码
                    "source": "bGATemp",
                })
    except Exception as e:
        logger.warning("bGATemp fetch failed for mrn=%s: %s", mrn, e)

    return observations


def _fetch_bedside_observations(
    sc, sc_pid: str, eval_time: datetime, lookback_hours: int = 24
) -> List[dict]:
    """
    从 bedside 提取床旁监测观测。
    包括: GCS, MAP, 尿量, SpO2, 呼吸频率等。

    关键修复: GCS 文本编码(E2V2M3/E2VTM3)必须在 _safe_float 之前识别，
    不能在 val is None 时提前 continue。
    """
    import re

    observations = []
    window_start = eval_time - timedelta(hours=lookback_hours)

    # GCS 相关代码集合
    GCS_CODES = {"param_score_gcs_obs", "gcsScore", "GCS"}

    # bedside 结构: {pid, code, strVal, time, valid}
    BEDSIDE_CODE_MAP = {
        "param_score_gcs_obs": "param_score_gcs_obs",
        "gcsScore": "gcsScore",
        "GCS": "GCS",
        "param_nibp_m": "MAP",
        "param_ibp_m": "MAP",
        "mean_arterial_pressure": "MAP",
        "MAP": "MAP",
        "param_niaoLiang": "urine_output",
        "urineVolume": "urine_output",
        "param_SpO2": "SpO2",
        "SpO2": "SpO2",
        "param_resp": "param_resp",
        "param_vent_resp": "param_vent_resp",
        # 机械通气关键代码 (用于 SOFA 呼吸系统评分判断)
        "param_vent_peep": "param_vent_peep",
        "param_vent_vt": "param_vent_vt",
        "param_vent_pip": "param_vent_pip",
    }

    try:
        bedside_docs = list(sc.bedside.find(
            {"pid": sc_pid,
             "code": {"$in": list(BEDSIDE_CODE_MAP.keys())},
             "valid": True,
             "time": {"$gte": window_start, "$lte": eval_time}},
            {"code": 1, "strVal": 1, "value_number": 1, "time": 1, "unit": 1}
        ).max_time_ms(15000).limit(1000))

        for doc in bedside_docs:
            code_raw = doc.get("code", "")
            if code_raw not in BEDSIDE_CODE_MAP:
                continue
            ts = doc.get("time")
            if not isinstance(ts, datetime):
                continue
            # 确保时区一致后再比较
            ts_aware = _aware(ts)
            ws_aware = _aware(window_start)
            ev_aware = _aware(eval_time)
            if ts_aware < ws_aware or ts_aware > ev_aware:
                continue

            unit = doc.get("unit", "")

            # ---- GCS 特殊处理: 先识别文本编码，再尝试数值 ----
            if code_raw in GCS_CODES:
                raw_text = str(doc.get("strVal", "")).strip()
                # 先检查是否是 E2V2M3 / E2VTM3 编码格式
                # 支持大小写变体和分隔符变体
                gcs_pattern = r"^[Ee]([1-4])[Vv]([Tt1-5])[Mm]([1-6])$"
                m = re.fullmatch(gcs_pattern, raw_text)
                if m:
                    # 合法文本编码: 写入 value_text，数字值设为 None
                    observations.append({
                        "code": BEDSIDE_CODE_MAP[code_raw],
                        "value_number": None,
                        "value_text": raw_text,
                        "unit": "",
                        "observed_at": _aware(ts),
                        "item_code": code_raw,
                        "source": "bedside",
                    })
                    continue
                # 非编码格式: 尝试数值解析
                val = _safe_float(doc.get("value_number"))
                if val is None:
                    val = _safe_float(doc.get("strVal"))
                if val is not None:
                    observations.append({
                        "code": BEDSIDE_CODE_MAP[code_raw],
                        "value_number": val,
                        "unit": unit,
                        "observed_at": _aware(ts),
                        "item_code": code_raw,
                        "source": "bedside",
                    })
                else:
                    # 非法GCS格式: 记录数据质量错误
                    if raw_text and raw_text.lower() not in ("", "null", "none", "nan"):
                        logger.debug("GCS非法格式: code=%s raw_text=%s", code_raw, raw_text)
                continue

            # ---- 非GCS代码: 标准数值解析 ----
            val = _safe_float(doc.get("value_number"))
            if val is None:
                val = _safe_float(doc.get("strVal"))
            if val is None:
                continue

            observations.append({
                "code": BEDSIDE_CODE_MAP[code_raw],
                "value_number": val,
                "unit": unit,
                "observed_at": _aware(ts),
                "item_code": code_raw,
                "source": "bedside",
            })
    except Exception as e:
        logger.warning("bedside fetch failed for sc_pid=%s: %s", sc_pid, e)

    return observations


def _fetch_score_observations(
    sc, sc_pid: str, eval_time: datetime, lookback_hours: int = 24
) -> List[dict]:
    """
    从 score 集合提取评分观测（主要是 GCS total）。
    score 结构: {pid, scoreType, total, time, valid}
    """
    observations = []
    window_start = eval_time - timedelta(hours=lookback_hours)

    try:
        score_docs = list(sc.score.find(
            {"pid": sc_pid, "scoreType": "gcsScore", "valid": True,
             "time": {"$gte": window_start, "$lte": eval_time}},
            {"total": 1, "time": 1}
        ).sort("time", -1).max_time_ms(10000).limit(200))

        for doc in score_docs:
            total = _safe_float(doc.get("total"))
            if total is None:
                continue
            ts = doc.get("time")
            if not isinstance(ts, datetime):
                continue
            observations.append({
                "code": "gcsScore",
                "value_number": total,
                "unit": "",
                "observed_at": _aware(ts),
            })
    except Exception as e:
        logger.warning("score fetch failed for sc_pid=%s: %s", sc_pid, e)

    return observations


def _fetch_lab_observations(
    dc, his_pid: str, eval_time: datetime, lookback_hours: int = 24
) -> List[dict]:
    """
    从 VI_ICU_EXAM (主表) + VI_ICU_EXAM_ITEM (子表) 提取检验观测。
    包括: PLT(血小板), TBIL(胆红素), CREA(肌酐)。

    关键适配:
    1. 主表用 pid=hisPid 定位当前住院事件
    2. 主表用 examID/reportID 关联子表 — 同时支持两种关联
    3. 子表用 itemCode 精确匹配
    4. 数值优先取 itemValue (而非 result)
    5. 时间优先取 collectTime (采样时间)
    6. 处理同一标本重复项目和更正报告
    """
    observations = []
    window_start = eval_time - timedelta(hours=lookback_hours)

    if dc is None:
        return observations

    # itemCode → 标准码映射 (多编码兼容)
    LAB_MAP = {
        "PLT": "PLT",
        "platelet": "PLT",
        "TBIL": "TBIL",
        "sCr": "CREA",
        "Cr": "CREA",
        "CREA": "CREA",
    }

    try:
        hp = str(his_pid)

        # Step 1: 查主表，获取 examID、reportID 和 collectTime
        exam_docs = list(dc.VI_ICU_EXAM.find(
            {"pid": hp,
             "collectTime": {"$gte": window_start, "$lte": eval_time}},
            {"examID": 1, "reportID": 1, "collectTime": 1},
        ).max_time_ms(10000).limit(200))

        if not exam_docs:
            return observations

        # 构建 examID 和 reportID 集合及时间映射
        exam_ids = []
        report_ids = []
        exam_time_by_id = {}
        for e in exam_docs:
            eid = e.get("examID")
            rid = e.get("reportID")
            ct = e.get("collectTime")
            if eid:
                exam_ids.append(eid)
                exam_time_by_id[str(eid)] = ct
            if rid:
                report_ids.append(rid)
                exam_time_by_id[str(rid)] = ct

        if not exam_ids and not report_ids:
            return observations

        # Step 2: 查子表，同时用 examID 和 reportID 关联
        # 优先用 examID，如果子表有 reportID 字段也支持
        for item_code, std_code in LAB_MAP.items():
            # 构建查询: examID 匹配或 reportID 匹配
            or_conditions = []
            if exam_ids:
                or_conditions.append({"examID": {"$in": exam_ids}})
            if report_ids:
                or_conditions.append({"reportID": {"$in": report_ids}})

            if not or_conditions:
                continue

            query = {
                "$or": or_conditions,
                "itemCode": item_code,
            }

            item_docs = list(dc.VI_ICU_EXAM_ITEM.find(
                query,
                {"itemValue": 1, "result": 1, "unit": 1, "itemName": 1,
                 "examID": 1, "reportID": 1}
            ).max_time_ms(10000).limit(100))

            # 去重: 同一标本的重复项目和更正报告
            seen = {}  # key: (exam_id, item_code) → 取最新

            for doc in item_docs:
                # 数值优先取 itemValue，兜底 result
                raw_val = _safe_float(doc.get("itemValue"))
                if raw_val is None:
                    raw_val = _safe_float(doc.get("result"))
                if raw_val is None:
                    continue

                # 时间从主表 collectTime 获取
                doc_exam_id = doc.get("examID")
                doc_report_id = doc.get("reportID")
                ts = None
                if doc_exam_id:
                    ts = exam_time_by_id.get(str(doc_exam_id))
                if ts is None and doc_report_id:
                    ts = exam_time_by_id.get(str(doc_report_id))
                if ts is None:
                    continue
                if not isinstance(ts, datetime):
                    continue
                if ts < window_start or ts > eval_time:
                    continue

                # 去重: 同一 examID + itemCode 只保留一条
                dedup_key = (str(doc_exam_id or doc_report_id), item_code)
                if dedup_key in seen:
                    continue
                seen[dedup_key] = True

                unit = (doc.get("unit") or "").strip()
                observations.append({
                    "code": std_code,
                    "value_number": raw_val,
                    "unit": unit,
                    "observed_at": _aware(ts),
                    "item_name": doc.get("itemName", ""),
                    "source": "VI_ICU_EXAM_ITEM",
                })
    except Exception as e:
        logger.warning("lab fetch failed for his_pid=%s: %s", his_pid, e)

    return observations


def _fetch_ventilator_status(sc, sc_pid: str, eval_time: datetime) -> bool:
    """
    [DEPRECATED] 检查是否有高级呼吸支持（机械通气等）。
    已被 _fetch_ventilator_status_point_in_time 替代。
    此函数使用24h存在检查，会误判已停止的通气。
    """
    window_start = eval_time - timedelta(hours=24)
    try:
        for _doc in sc.bedside.find(
            {"pid": sc_pid, "code": {"$in": ["param_vent_resp", "param_vent_peep"]},
             "valid": True, "time": {"$gte": window_start, "$lte": eval_time}},
            {"_id": 1}
        ).max_time_ms(5000).limit(1):
            return True
    except Exception:
        pass
    return False


# ============================================================
# 用药数据提取
# ============================================================

def _fetch_medications(
    sc, sc_pid: str, eval_time: datetime,
    weight_kg: Optional[float],
    lookback_hours: int = 24
) -> Tuple[List[dict], bool]:
    """
    从 drugExe 提取用药数据，转换为评分器格式。

    关键改进:
    1. 查询范围扩展: startTime <= eval_time (不限于24h，允许更早开始但仍在使用的药物)
    2. 重建活跃区间: 按 drugActionList 时间排序，形成有效区间
    3. 判断评分时点是否正在使用: 药物在 eval_time 时必须处于活跃状态
    4. 支持暂停后恢复、停止后重新启动等复杂场景

    返回:
        (medications, has_vasopressor_wide)
        medications: [{med_name, route, dose_ugkgmin, admin_end, admin_start, active_intervals}]
        has_vasopressor_wide: VASO_WIDE 口径是否有活跃升压药
    """
    from .adapter import canon_drug, ne_ugkgmin as calc_ne_dose
    from .bundle_engine import _classify_vasopressor

    medications = []
    has_vasopressor_wide = False

    try:
        # 查询范围: startTime <= eval_time (允许更早开始但仍在使用的药物)
        drug_docs = list(sc.drugExe.find(
            {"pid": sc_pid, "startTime": {"$lte": eval_time}},
            {"drugList": 1, "drugActionList": 1, "startTime": 1, "weight": 1}
        ).sort("startTime", 1).max_time_ms(15000).limit(500))

        for doc in drug_docs:
            start_time = doc.get("startTime")
            if not start_time:
                continue

            # 从文档获取体重（如果调用方未提供）
            doc_weight = weight_kg
            if doc_weight is None:
                w = doc.get("weight")
                if w and isinstance(w, (int, float)) and 20 < w < 300:
                    doc_weight = float(w)

            # 重建活跃区间
            active_intervals = _reconstruct_active_intervals(
                doc.get("drugActionList") or [], start_time
            )

            # 判断 eval_time 时是否活跃
            is_active_at_eval = _is_active_at(active_intervals, eval_time)

            # 获取最新泵速 (从活跃区间的最后一个动作)
            speed_mlh = 0.0
            admin_end = None
            if is_active_at_eval:
                # 从最近的动作获取泵速
                for action in reversed(doc.get("drugActionList") or []):
                    s = _safe_float(action.get("speed"))
                    if s is not None and s > 0:
                        speed_mlh = s
                        break
            else:
                # 药物已结束，获取结束时间
                for action in reversed(doc.get("drugActionList") or []):
                    at = action.get("type", "")
                    if at in ("停止", "暂停", "取消"):
                        admin_end = action.get("time")
                        break

            for drug in (doc.get("drugList") or []):
                name = str(drug.get("name", ""))
                if not name:
                    continue

                # 判断是否为升压药
                in_wide, in_strict = _classify_vasopressor(name)

                if in_wide and is_active_at_eval:
                    has_vasopressor_wide = True

                # 只处理升压药（SOFA 心血管评分需要）
                if in_strict:
                    # 计算剂量 (体重缺失时仍保留升压药证据)
                    dose_ugkgmin = None
                    dose_status = None
                    if not doc_weight or doc_weight <= 0:
                        dose_status = "weight_missing"
                    elif not is_active_at_eval:
                        dose_status = "not_active"
                    else:
                        try:
                            dose_raw = _safe_float(drug.get("dose"))
                            liquid_raw = _safe_float(drug.get("liquidAmount"))
                            if liquid_raw is None:
                                liquid_raw = _safe_float(doc.get("liquidAmount"))
                            if dose_raw and liquid_raw and speed_mlh > 0:
                                calc_action = {
                                    "dose": dose_raw,
                                    "doseUnit": drug.get("doseUnit", "mg"),
                                    "liquidAmount": liquid_raw,
                                    "liquidUnit": drug.get("liquidUnit", "ml"),
                                    "speed": speed_mlh,
                                }
                                dose_ugkgmin, _ = calc_ne_dose(calc_action, doc_weight)
                            else:
                                dose_status = "calculation_failed"
                        except Exception:
                            dose_status = "calculation_error"

                    # 确定 route
                    route = ""
                    for action in (doc.get("drugActionList") or []):
                        r = action.get("route", "")
                        if r:
                            route = r
                            break

                    med = {
                        "med_name": name,
                        "route": route,
                        "dose_ugkgmin": dose_ugkgmin,
                        "dose_status": dose_status,
                        "admin_end": _aware(admin_end) if admin_end else None,
                        "admin_start": _aware(start_time),
                        "active_intervals": active_intervals,
                        "is_active_at_eval": is_active_at_eval,
                        "is_vasopressor": True,
                        "weight_kg": doc_weight,
                    }
                    medications.append(med)
                elif in_wide and not in_strict:
                    # VASO_WIDE 但非 SOFA 白名单 → 记录但不计算剂量
                    medications.append({
                        "med_name": name,
                        "route": "",
                        "dose_ugkgmin": None,
                        "admin_end": _aware(admin_end) if admin_end else None,
                        "admin_start": _aware(start_time),
                        "active_intervals": active_intervals,
                        "is_active_at_eval": is_active_at_eval,
                    })
    except Exception as e:
        logger.warning("drugExe fetch failed for sc_pid=%s: %s", sc_pid, e)

    return medications, has_vasopressor_wide


def _reconstruct_active_intervals(
    actions: List[dict], start_time: datetime
) -> List[Tuple[datetime, Optional[datetime]]]:
    """
    从 drugActionList 重建活跃区间。

    逻辑:
    1. 按动作时间排序
    2. "开始"动作 → 开启新区间
    3. "停止/暂停/取消"动作 → 关闭当前区间
    4. "恢复"动作 → 开启新区间
    5. 缺时间的动作跳过

    返回: [(start, end), ...] 区间列表，end=None 表示仍在进行中
    """
    intervals = []
    current_start = None

    # 按时间排序
    sorted_actions = sorted(
        [a for a in actions if a.get("time")],
        key=lambda a: a["time"]
    )

    for action in sorted_actions:
        action_type = action.get("type", "")
        action_time = action.get("time")

        if action_type in ("开始", "恢复"):
            if current_start is None:
                current_start = action_time
        elif action_type in ("停止", "暂停", "取消"):
            if current_start is not None:
                intervals.append((current_start, action_time))
                current_start = None

    # 如果最后一个区间未关闭，标记为进行中
    if current_start is not None:
        intervals.append((current_start, None))

    # 如果没有任何动作，使用 startTime 作为开始
    if not intervals and start_time:
        intervals.append((start_time, None))

    return intervals


def _is_active_at(
    intervals: List[Tuple[datetime, Optional[datetime]]],
    eval_time: datetime
) -> bool:
    """
    判断 eval_time 时药物是否处于活跃状态。

    逻辑:
    1. 遍历所有区间
    2. eval_time 在 [start, end) 内 → 活跃
    3. end=None 表示仍在进行中 → eval_time >= start 即活跃
    """
    eval_aware = _aware(eval_time)
    for start, end in intervals:
        start_aware = _aware(start)
        if end is None:
            # 仍在进行中
            if eval_aware >= start_aware:
                return True
        else:
            end_aware = _aware(end)
            if start_aware <= eval_aware < end_aware:
                return True
    return False


def _fetch_ventilator_status_point_in_time(
    sc, sc_pid: str, eval_time: datetime, tolerance_hours: int = 4
) -> bool:
    """
    判断 eval_time 时患者是否正在接受机械通气。

    关键逻辑:
    - 分别获取 PEEP、VT、PIP 在 eval_time 前的最后有效状态
    - 综合多个参数共同判断: PEEP>0 或 VT>0 或 PIP>0 → 机械通气中
    - 不仅取最新一条(可能PEEP=0但VT仍有值)
    - 找不到证据时返回 False (保守)

    返回: True=机械通气中, False=未在机械通气
    """
    window_start = eval_time - timedelta(hours=tolerance_hours)

    try:
        # 分别查询各参数在窗口内的最新值
        vent_params = {}
        for code in ["param_vent_peep", "param_vent_vt", "param_vent_pip"]:
            doc = sc.bedside.find_one(
                {"pid": sc_pid,
                 "code": code,
                 "valid": True,
                 "time": {"$gte": window_start, "$lte": eval_time}},
                sort=[("time", -1)]
            )
            if doc:
                val = _safe_float(doc.get("value_number"))
                if val is None:
                    val = _safe_float(doc.get("strVal"))
                vent_params[code] = val

        # 综合判断: 任一参数 > 0 即认为机械通气中
        peep = vent_params.get("param_vent_peep")
        vt = vent_params.get("param_vent_vt")
        pip = vent_params.get("param_vent_pip")

        if (peep is not None and peep > 0) or \
           (vt is not None and vt > 0) or \
           (pip is not None and pip > 0):
            return True

        return False
    except Exception as e:
        logger.warning("Ventilator status fetch failed for sc_pid=%s: %s", sc_pid, e)
        return False


def _fetch_weight(sc, sc_pid: str) -> Optional[float]:
    """从 patient 集合获取体重。"""
    try:
        from bson import ObjectId
        pat = sc.patient.find_one(
            {"_id": ObjectId(sc_pid) if len(sc_pid) == 24 else sc_pid},
            {"weight": 1}
        )
        if pat:
            w = pat.get("weight")
            if w and isinstance(w, (int, float)) and 20 < w < 300:
                return float(w)
    except Exception:
        pass
    return None


# ============================================================
# 主入口
# ============================================================

def fetch_patient_obs_meds(
    sc_pid: str,
    mrn: str,
    dc_pid: str,
    t0: datetime,
    eval_time: Optional[datetime] = None,
    weight_kg: Optional[float] = None,
) -> dict:
    """
    从 MongoDB 提取患者观测和用药数据，转换为 SOFA 评分器格式。

    Args:
        sc_pid: SmartCare patient _id
        mrn: 病案号 (用于 bGATemp 查询)
        dc_pid: DataCenter VI_ICU_ZYBR pid (用于 VI_ICU_EXAM_ITEM 查询)
        t0: T0 时间
        eval_time: 评估时间，默认 T0+24h
        weight_kg: 体重 (可选，自动从数据库获取)

    Returns:
        {
            "observations": [...],
            "medications": [...],
            "has_advanced_support": bool,
            "weight_kg": float|None,
            "has_vasopressor_wide": bool,
            "data_quality_flags": [...],
            "fetch_meta": {...},
        }
    """
    from db import get_client

    if t0 is None:
        return {"observations": [], "medications": [], "has_advanced_support": False,
                "weight_kg": None, "has_vasopressor_wide": False,
                "data_quality_flags": ["NO_T0"], "fetch_meta": {}}

    # 确保 timezone-aware
    t0 = _aware(t0)
    if eval_time is None:
        eval_time = t0 + timedelta(hours=24)
    eval_time = _aware(eval_time)

    flags = []
    fetch_meta = {}

    # 获取数据库连接
    try:
        sc = get_client("SmartCare")["SmartCare"]
    except Exception as e:
        logger.error("Cannot connect to SmartCare: %s", e)
        return {"observations": [], "medications": [], "has_advanced_support": False,
                "weight_kg": weight_kg, "has_vasopressor_wide": False,
                "data_quality_flags": ["DB_CONNECTION_FAILED"], "fetch_meta": {}}

    try:
        dc = get_client("DataCenter")["DataCenter"]
    except Exception:
        dc = None
        flags.append("DataCenter_unavailable")

    # 1. 获取体重
    if weight_kg is None:
        weight_kg = _fetch_weight(sc, sc_pid)
    if weight_kg is None:
        flags.append("weight_missing")

    # 2. 提取观测数据
    observations = []

    # bGATemp (P/F ratio, 乳酸, PaO2, FiO2)
    bga_obs = _fetch_bga_observations(sc, mrn, eval_time)
    observations.extend(bga_obs)
    fetch_meta["bga_count"] = len(bga_obs)

    # bedside (GCS, MAP, 尿量, SpO2)
    bedside_obs = _fetch_bedside_observations(sc, sc_pid, eval_time)
    observations.extend(bedside_obs)
    fetch_meta["bedside_count"] = len(bedside_obs)

    # score (GCS total)
    score_obs = _fetch_score_observations(sc, sc_pid, eval_time)
    observations.extend(score_obs)
    fetch_meta["score_count"] = len(score_obs)

    # VI_ICU_EXAM_ITEM (PLT, TBIL, CREA)
    lab_obs = _fetch_lab_observations(dc, dc_pid, eval_time)
    observations.extend(lab_obs)
    fetch_meta["lab_count"] = len(lab_obs)

    fetch_meta["total_obs_count"] = len(observations)

    # 3. 提取用药数据
    medications, has_vaso_wide = _fetch_medications(sc, sc_pid, eval_time, weight_kg)
    fetch_meta["med_count"] = len(medications)

    # 4. 判断高级呼吸支持
    has_advanced_support = _fetch_ventilator_status_point_in_time(sc, sc_pid, eval_time)

    # 5. 检查数据完整性 (使用标准化代码)
    obs_codes = set(obs.get("code") for obs in observations)
    # 标准化代码 (与 BGA_CODE_MAP 输出一致)
    critical_codes = {
        "P/F_ratio", "PaO2", "Lactate", "FiO2",
        "PLT", "TBIL", "CREA",
        "param_score_gcs_obs", "gcsScore", "MAP", "urine_output",
    }
    # FiO2 和 P/F 不重复造成假缺失
    has_pf = "P/F_ratio" in obs_codes
    has_pao2 = "PaO2" in obs_codes
    has_fio2 = "FiO2" in obs_codes
    # 如果有 P/F ratio 直接值，PaO2+FiO2 不是必须的
    if has_pf:
        critical_codes.discard("PaO2")
        critical_codes.discard("FiO2")

    missing_critical = critical_codes - obs_codes
    if missing_critical:
        flags.append(f"missing_observations: {len(missing_critical)} critical codes absent: {','.join(sorted(missing_critical))}")

    return {
        "observations": observations,
        "medications": medications,
        "has_advanced_support": has_advanced_support,
        "weight_kg": weight_kg,
        "has_vasopressor_wide": has_vaso_wide,
        "data_quality_flags": flags,
        "fetch_meta": fetch_meta,
    }
