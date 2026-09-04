"""
经典 SOFA 1996 评分内核。
纯函数，不依赖任何 I/O，评估时间由外部传入。
参考文献: Vincent JL, et al. Intensive Care Medicine, 1996;22:707-710.

铁律:
  - 评分核内禁止 DB 访问、禁止 now()
  - 观测时间 > evaluation_time 的数据不得使用
  - 缺失数据返回 None，不得回退为 0 或空值
  - 判定项只返回 True/False/None
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .sofa_rules import (
    CLASSIC_SOFA_THRESHOLDS as _TH,
    _UNIT_CONVERSION,
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# 单位白名单 (经典 SOFA 专用, 需求文档 7.3 第 2、13 条)
# -----------------------------------------------------------
_ALLOWED_UNITS_CLASSIC: Dict[str, set] = {
    "bilirubin": {"umol/l", "μmol/l", "micromol/l", "微摩尔/升"},
    "creatinine": {"umol/l", "μmol/l", "micromol/l", "微摩尔/升"},
}


def _normalize_unit(u: Optional[str]) -> str:
    """单位标准化: strip + lower。"""
    if not u:
        return ""
    return u.strip().lower()


def _convert_to_classic_canonical(
    value: float, unit: str, substance: str
) -> Tuple[Optional[float], Optional[str]]:
    """
    将数值转换为经典 SOFA 的标准单位。
    经典 SOFA: 胆红素 μmol/L, 肌酐 μmol/L。

    返回 (converted_value, error_message)。
    成功时 error_message=None。
    """
    normalized = _normalize_unit(unit)

    if not normalized:
        # 需求文档 7.3 第 2 条: 无单位不可运行
        return None, f"单位缺失, 禁止回退为默认单位. substance={substance}"

    allowed = _ALLOWED_UNITS_CLASSIC.get(substance, set())
    if not allowed:
        return None, f"未知 substance={substance}, 无法校验单位"

    if normalized in allowed:
        # 已经是经典 SOFA 标准单位
        return value, None

    # 尝试转换
    key = (normalized, "umol/l")
    if key in _UNIT_CONVERSION:
        return _UNIT_CONVERSION[key](value), None

    return None, (
        f"单位 '{unit}' 不在经典 SOFA {substance} 白名单 {allowed} 内, "
        f"且无已知转换路径. 禁止静默回退."
    )


# -----------------------------------------------------------
# 分值阈值判定 (半开区间, 需求文档 7.3 第 4 条)
# -----------------------------------------------------------
def _score_from_thresholds(value: float, thresholds: List[dict]) -> int:
    """
    半开区间 [low, high) 匹配分值。
    注意: 经典 SOFA 原文用 <=，这里统一为半开区间以符合需求文档。
    """
    for t in thresholds:
        if t["low"] <= value < t["high"]:
            return int(t["score"])
    # 兜底: 低于最低阈值取最高分，高于最高阈值取最低分
    if value < thresholds[0]["low"]:
        return int(thresholds[-1]["score"])
    return int(thresholds[0]["score"])


# -----------------------------------------------------------
# 辅助: 从观测列表中找窗口内最差值
# -----------------------------------------------------------
def _worst_in_window(
    observations: List[dict],
    codes: List[str],
    eval_time: datetime,
    lookback_hours: int,
    max_staleness_hours: int,
) -> Tuple[Optional[float], Optional[str], Optional[datetime]]:
    """
    在 [eval_time - lookback, eval_time] 窗口内，按 code 匹配观测，
    返回 (worst_value, unit, observed_at)。
    如果 max_staleness > 0，还会检查最近一条是否在 staleness 范围内。

    对于"worst"聚合:
      - 呼吸/凝血/肝/肾肌酐: 取最低值(越低越差)
      - 但对于 PaO2/FiO2 ratio 和 GCS，评分函数会自行处理
    """
    window_start = eval_time - timedelta(hours=lookback_hours)
    cutoff = eval_time - timedelta(hours=max_staleness_hours) if max_staleness_hours else None

    candidates = []
    for obs in observations:
        code = (obs.get("code") or obs.get("item_name") or "").strip()
        if code not in codes:
            continue
        raw_val = obs.get("value_number")
        if raw_val is None:
            # 需求文档 7.3 第 5 条: 不得把 value_number=0 当缺失回退
            continue
        ts = obs.get("observed_at")
        if not isinstance(ts, datetime):
            continue
        # 确保时区感知
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < window_start or ts > eval_time:
            continue
        candidates.append((float(raw_val), obs.get("unit", ""), ts))

    if not candidates:
        return None, None, None

    # 返回最差值(最小值), 同时记录时间用于 staleness 检查
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


# -----------------------------------------------------------
# 呼吸 (需求文档 7.3 第 12 条: 经典 SOFA 需机械通气门控)
# -----------------------------------------------------------
def _calc_respiratory(
    obs: List[dict],
    eval_time: datetime,
    has_advanced_support: bool,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """
    PaO2/FiO2 ratio 评分。
    需求文档 7.3 第 12 条: 经典 SOFA 的 score=3/4 需 has_advanced_support=True。
    """
    info: Dict[str, Any] = {}

    # 找 PaO2 和 FiO2
    codes_pao2 = ["param_PaO2", "PaO2"]
    codes_fio2 = ["param_FiO2", "FiO2"]
    codes_ratio = ["param_bg_P/Fratio"]

    # 先查 ratio 直接值
    val, unit, ts = _worst_in_window(obs, codes_ratio, eval_time, 24, 4)
    if val is not None and val > 0:
        ratio = val
    else:
        val_pao2, _, ts_pao2 = _worst_in_window(obs, codes_pao2, eval_time, 24, 4)
        val_fio2, _, ts_fio2 = _worst_in_window(obs, codes_fio2, eval_time, 24, 4)
        if val_pao2 is None or val_fio2 is None:
            info["respiratory_missing"] = True
            return None, info
        # 需求文档 7.3 第 3 条: PaO2 与 FiO2 配对 30 分钟窗口
        if ts_pao2 and ts_fio2 and abs((ts_pao2 - ts_fio2).total_seconds()) > 1800:
            info["respiratory_pair_mismatch"] = True
            return None, info
        if val_fio2 <= 0:
            info["fio2_zero"] = True
            return None, info
        # FiO2 可能是 0-1 或 0-100
        if val_fio2 > 1.0:
            val_fio2 = val_fio2 / 100.0
        ratio = val_pao2 / val_fio2

    score = _score_from_thresholds(ratio, _TH["respiratory"]["thresholds"])

    # 需求文档 7.3 第 12 条: 经典 SOFA score=3 或 4 需机械通气门控
    if score >= 3 and not has_advanced_support:
        score = 2

    info["pao2_fio2_ratio"] = ratio
    return score, info


# -----------------------------------------------------------
# 凝血 (PLT)
# -----------------------------------------------------------
def _calc_coagulation(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    val, unit, ts = _worst_in_window(
        obs, _TH["coagulation"]["codes"], eval_time,
        _TH["coagulation"]["lookback_hours"],
        _TH["coagulation"]["max_staleness_hours"],
    )
    if val is None:
        info["coagulation_missing"] = True
        return None, info
    # PLT 一般单位一致, 不需要转换
    score = _score_from_thresholds(val, _TH["coagulation"]["thresholds"])
    return score, info


# -----------------------------------------------------------
# 肝脏 (需求文档 7.3 第 2、13 条: 单位白名单)
# -----------------------------------------------------------
def _calc_liver(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    val, unit, ts = _worst_in_window(
        obs, _TH["liver"]["codes"], eval_time,
        _TH["liver"]["lookback_hours"],
        _TH["liver"]["max_staleness_hours"],
    )
    if val is None:
        info["liver_missing"] = True
        return None, info

    # 需求文档 7.3 第 2 条: 单位白名单
    converted, err = _convert_to_classic_canonical(val, unit, "bilirubin")
    if err:
        info["liver_unit_error"] = err
        return None, info

    score = _score_from_thresholds(converted, _TH["liver"]["thresholds"])
    return score, info


# -----------------------------------------------------------
# 心血管 (需求文档 7.3 第 1 条: Vincent 1996 原文逻辑)
# -----------------------------------------------------------
def _calc_cardiovascular(
    obs: List[dict],
    eval_time: datetime,
    pressors: List[dict],
    weight_kg: Optional[float],
) -> Tuple[Optional[int], Dict[str, Any]]:
    """
    经典 SOFA 心血管评分。
    需求文档 7.3 第 1 条:
      - MAP<70 → score=1
      - 多巴胺分档: ≤5→2, >5且≤15→3, >15→4
      - NE/Epi 剂量梯度: ≤5→3, >5→4 (注意: 经典 SOFA 只有 2 个梯度)
      - 第 9 条: has_active_pressor 且剂量未知 → score=max(score,2)
    """
    info: Dict[str, Any] = {}

    # 检查是否有升压药活动
    has_active_pressor = False
    ne_dose_ugkgmin = 0.0
    epi_dose_ugkgmin = 0.0
    dopa_dose_ugkgmin = 0.0
    dose_known = False

    for med in pressors:
        admin_end = med.get("admin_end")
        if admin_end and isinstance(admin_end, datetime):
            if admin_end < eval_time:
                continue  # 已结束

        med_name = (med.get("med_name") or "").lower()
        route = (med.get("route") or "").lower()
        if "iv" not in route and "泵" not in route:
            continue

        has_active_pressor = True

        # 优先取 dose_ugkgmin (已由 adapter 换算)
        dose = med.get("dose_ugkgmin")
        if dose is None or dose <= 0:
            # 降级: 尝试从 med_dose 换算
            raw_dose = med.get("med_dose")
            raw_unit = (med.get("med_unit") or "").lower()
            if raw_dose is not None and raw_dose > 0 and weight_kg and weight_kg > 0:
                if "ug/kg/min" in raw_unit or "μg/kg/min" in raw_unit:
                    dose = raw_dose
                elif "mg" in raw_unit and "min" in raw_unit:
                    dose = raw_dose * 1000 / weight_kg
        if dose is not None and dose > 0:
            dose_known = True
            if "去甲" in med_name or "norepinephrine" in med_name:
                ne_dose_ugkgmin = max(ne_dose_ugkgmin, dose)
            elif "肾上腺" in med_name or "epinephrine" in med_name:
                epi_dose_ugkgmin = max(epi_dose_ugkgmin, dose)
            elif "多巴胺" in med_name or "dopamine" in med_name:
                dopa_dose_ugkgmin = max(dopa_dose_ugkgmin, dose)

    # 检查 MAP
    map_val, _, _ = _worst_in_window(
        obs, ["MAP", "mean_arterial_pressure"], eval_time, 24, 1
    )

    score = 0

    # MAP<70 且无升压药 → score=1
    if map_val is not None and map_val < 70 and not has_active_pressor:
        score = 1

    # 多巴胺分档 (经典 SOFA: ≤5→2, 5-15→3, >15→4)
    if dopa_dose_ugkgmin > 0:
        for t in _TH["cardiovascular"]["dopamine_thresholds"]:
            if t["low"] < dopa_dose_ugkgmin <= t["high"]:
                score = max(score, int(t["score"]))
                break
        else:
            if dopa_dose_ugkgmin > 15:
                score = max(score, 4)

    # NE/Epi 剂量梯度 (经典 SOFA 只有 ≤5→3, >5→4)
    ne_epi_sum = ne_dose_ugkgmin + epi_dose_ugkgmin
    if ne_epi_sum > 0:
        if ne_epi_sum <= 5:
            score = max(score, 3)
        else:
            score = max(score, 4)

    # 需求文档 7.3 第 9 条: has_active_pressor 且剂量未知 → max(score, 2)
    if has_active_pressor and not dose_known:
        score = max(score, 2)

    info["has_active_pressor"] = has_active_pressor
    info["dose_known"] = dose_known
    info["ne_dose_ugkgmin"] = ne_dose_ugkgmin
    info["map_value"] = map_val
    return score, info


# -----------------------------------------------------------
# 中枢神经 (GCS, 需求文档 7.3 第 8 条: 编码解析)
# -----------------------------------------------------------
_GCS_MOTOR_MAP = {
    # 语言/运动映射: V=T → motor fallback
    "t": 4,  # T(气管插管) → 扩展/无反应
}

def _parse_gcs(gcs_val: Any) -> Tuple[Optional[int], Optional[str]]:
    """
    解析 GCS 值。支持:
      - 数值: 直接返回
      - 字符串 "E1VTM1": 解析 E/V/M 分量，V=T→motor fallback
      - 字符串 "15": 解析为数字

    返回 (total_score, error)。
    """
    if gcs_val is None:
        return None, None

    if isinstance(gcs_val, (int, float)):
        return int(gcs_val), None

    if isinstance(gcs_val, str):
        # 尝试数值解析
        try:
            return int(float(gcs_val)), None
        except ValueError:
            pass

        # E1VTM1 格式解析
        pattern = r"[Ee](\d+)[Vv]([Tt\d]+)[Mm](\d+)"
        m = re.search(pattern, gcs_val)
        if m:
            e = int(m.group(1))
            v_raw = m.group(2)
            m_score = int(m.group(3))
            if v_raw.upper() == "T":
                # V=T → motor fallback (用 M 分量)
                total = e + _GCS_MOTOR_MAP["t"] + m_score
            else:
                v = int(v_raw)
                total = e + v + m_score
            return total, None

    return None, f"无法解析 GCS 值: {gcs_val}"


def _calc_cns(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    codes = _TH["central_nervous_system"]["codes"]
    lookback = _TH["central_nervous_system"]["lookback_hours"]
    staleness = _TH["central_nervous_system"]["max_staleness_hours"]

    # 找最新的 GCS 观测
    window_start = eval_time - timedelta(hours=lookback)
    best = None
    best_ts = None
    for o in obs:
        code = (o.get("code") or o.get("item_name") or "").strip()
        if code not in codes:
            continue
        ts = o.get("observed_at")
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < window_start or ts > eval_time:
            continue
        if best_ts is None or ts > best_ts:
            best = o
            best_ts = ts

    if best is None:
        info["cns_missing"] = True
        return None, info

    # 解析 GCS (可能为数值或 E1VTM1 格式)
    raw_gcs = best.get("value_number") or best.get("value_text")
    gcs_total, parse_err = _parse_gcs(raw_gcs)
    if parse_err:
        info["gcs_parse_error"] = parse_err
        return None, info
    if gcs_total is None:
        info["cns_missing"] = True
        return None, info

    score = _score_from_thresholds(gcs_total, _TH["central_nervous_system"]["thresholds"])
    return score, info


# -----------------------------------------------------------
# 肾脏 (需求文档 7.3 第 2、13 条)
# -----------------------------------------------------------
def _calc_renal(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """
    经典 SOFA 肾脏评分。
    肌酐: μmol/L (经典 SOFA 标准单位)
    尿量: mL/24h
    """
    info: Dict[str, Any] = {}
    score_creat = None
    score_urine = None

    # 肌酐
    val, unit, ts = _worst_in_window(
        obs, _TH["renal"]["codes_creatinine"], eval_time,
        _TH["renal"]["lookback_hours"],
        _TH["renal"]["max_staleness_hours"],
    )
    if val is not None:
        converted, err = _convert_to_classic_canonical(val, unit, "creatinine")
        if err:
            info["renal_creatinine_unit_error"] = err
        else:
            score_creat = _score_from_thresholds(
                converted, _TH["renal"]["creatinine_thresholds"]
            )

    # 尿量 (mL/24h)
    val, unit, ts = _worst_in_window(
        obs, _TH["renal"]["codes_urine"], eval_time,
        _TH["renal"]["lookback_hours"],
        _TH["renal"]["max_staleness_hours"],
    )
    if val is not None:
        normalized_u = _normalize_unit(unit)
        if normalized_u in ("ml/24h", "ml/24 hr", "ml/24hr"):
            score_urine = _score_from_thresholds(
                val, _TH["renal"]["urine_thresholds"]
            )
        elif normalized_u in ("ml/h", "ml/hr"):
            # 粗略转换
            score_urine = _score_from_thresholds(
                val * 24, _TH["renal"]["urine_thresholds"]
            )
        else:
            info["renal_urine_unit_error"] = f"未知尿量单位: {unit}"

    if score_creat is None and score_urine is None:
        info["renal_missing"] = True
        return None, info

    # 取两者最高分
    parts = [s for s in (score_creat, score_urine) if s is not None]
    return max(parts) if parts else None, info


# -----------------------------------------------------------
# 主入口
# -----------------------------------------------------------
def compute_sofa_classic(
    observations: List[dict],
    medications: List[dict],
    eval_time: datetime,
    has_advanced_support: bool = False,
    weight_kg: Optional[float] = None,
) -> Dict[str, Any]:
    """
    计算经典 SOFA 1996 总分。

    Args:
        observations: 观测数据列表，每条含 code, value_number, unit, observed_at
        medications: 用药数据列表，每条含 med_name, route, dose_ugkgmin, admin_end
        eval_time: 评估时间 (必须有时区)
        has_advanced_support: 是否有高级呼吸支持 (机械通气等)
        weight_kg: 体重 (用于 NE 剂量换算)

    Returns:
        {
            "sofa_score": int,          # 总分 0-24
            "components": {...},        # 各器官分值
            "data_quality_flags": [...],
            "meta": {...},
        }

    铁律: 缺失数据返回 None，不得回退为 0。
    """
    if eval_time.tzinfo is None:
        raise ValueError("eval_time 必须有时区信息")

    flags: List[str] = {}
    components: Dict[str, Any] = {}
    info: Dict[str, Any] = {}

    # 呼吸
    resp_score, resp_info = _calc_respiratory(observations, eval_time, has_advanced_support)
    info.update(resp_info)
    if resp_score is None:
        flags.append("respiratory_missing")
    components["respiratory"] = resp_score

    # 凝血
    coag_score, coag_info = _calc_coagulation(observations, eval_time)
    info.update(coag_info)
    if coag_score is None:
        flags.append("coagulation_missing")
    components["coagulation"] = coag_score

    # 肝脏
    liver_score, liver_info = _calc_liver(observations, eval_time)
    info.update(liver_info)
    if liver_score is None:
        flags.append("liver_missing")
    components["liver"] = liver_score

    # 心血管
    cv_score, cv_info = _calc_cardiovascular(observations, eval_time, medications, weight_kg)
    info.update(cv_info)
    if cv_score is None:
        flags.append("cardiovascular_missing")
    components["cardiovascular"] = cv_score

    # 中枢神经
    cns_score, cns_info = _calc_cns(observations, eval_time)
    info.update(cns_info)
    if cns_score is None:
        flags.append("cns_missing")
    components["central_nervous_system"] = cns_score

    # 肾脏
    renal_score, renal_info = _calc_renal(observations, eval_time)
    info.update(renal_info)
    if renal_score is None:
        flags.append("renal_missing")
    components["renal"] = renal_score

    # 计算总分 (仅对有值的器官求和)
    valid_scores = [s for s in components.values() if s is not None]
    total = sum(valid_scores) if valid_scores else None

    return {
        "sofa_score": total,
        "components": components,
        "data_quality_flags": flags,
        "meta": info,
    }
