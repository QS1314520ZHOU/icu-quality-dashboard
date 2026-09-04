"""
SOFA-2 2025 评分内核。
纯函数，不依赖任何 I/O，评估时间由外部传入。
参考文献: JAMA. 2025;334(23):2090-2103. DOI: 10.1001/jama.2025.20516.

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

from .sofa_rules import _UNIT_CONVERSION, SOFA2_THRESHOLDS as _TH
from .adapter import ne_ugkgmin as _ne_ugkgmin  # noqa: F401 — 唯一换算点引用
from .missing_policy import apply_policy as _apply_policy
import config.indicator_windows as _cfg

logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# 单位白名单 (SOFA-2 专用, 需求文档 7.3 第 2、13 条)
# -----------------------------------------------------------
_ALLOWED_UNITS_SOFA2: Dict[str, set] = {
    "bilirubin": {"mg/dl"},
    "creatinine": {"mg/dl"},
}


def _normalize_unit(u: Optional[str]) -> str:
    if not u:
        return ""
    return u.strip().lower()


def _convert_to_sofa2_canonical(
    value: float, unit: str, substance: str
) -> Tuple[Optional[float], Optional[str]]:
    """
    将数值转换为 SOFA-2 的标准单位。
    SOFA-2: 胆红素 mg/dL, 肌酐 mg/dL。
    """
    normalized = _normalize_unit(unit)
    if not normalized:
        return None, f"单位缺失, 禁止回退为默认单位. substance={substance}"

    allowed = _ALLOWED_UNITS_SOFA2.get(substance, set())
    if not allowed:
        return None, f"未知 substance={substance}"

    if normalized in allowed:
        return value, None

    # 尝试转换: umol/l → mg/dl
    key = (substance, normalized, "mg/dl")
    if key in _UNIT_CONVERSION:
        return _UNIT_CONVERSION[key](value), None

    return None, (
        f"单位 '{unit}' 不在 SOFA-2 {substance} 白名单 {allowed} 内, "
        f"且无已知转换路径. 禁止静默回退."
    )


# -----------------------------------------------------------
# 阈值匹配 (半开区间)
# -----------------------------------------------------------
def _score_from_thresholds(value: float, thresholds: List[dict]) -> int:
    for t in thresholds:
        if t["low"] <= value < t["high"]:
            return int(t["score"])
    if value < thresholds[0]["low"]:
        return int(thresholds[-1]["score"])
    return int(thresholds[0]["score"])


# -----------------------------------------------------------
# 窗口内最差值
# -----------------------------------------------------------
def _worst_in_window(
    observations: List[dict],
    codes: List[str],
    eval_time: datetime,
    lookback_hours: int,
    max_staleness_hours: int,
    agg: str = "min",
) -> Tuple[Optional[float], Optional[str], Optional[datetime]]:
    """
    agg 聚合方向: min / max / sum / latest
    """
    window_start = eval_time - timedelta(hours=lookback_hours)
    candidates = []
    for obs in observations:
        code = (obs.get("code") or obs.get("item_name") or "").strip()
        if code not in codes:
            continue
        raw_val = obs.get("value_number")
        if raw_val is None:
            continue
        ts = obs.get("observed_at")
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < window_start or ts > eval_time:
            continue
        candidates.append((float(raw_val), obs.get("unit", ""), ts))
    if not candidates:
        return None, None, None
    if agg == "sum":
        total_val = sum(c[0] for c in candidates)
        best_ts = max(c[2] for c in candidates)
        best_unit = [c[1] for c in candidates if c[2] == best_ts][0]
        return total_val, best_unit, best_ts
    elif agg == "max":
        candidates.sort(key=lambda x: x[0], reverse=True)
    elif agg == "latest":
        candidates.sort(key=lambda x: x[2], reverse=True)
    else:
        candidates.sort(key=lambda x: x[0])
    return candidates[0]


# -----------------------------------------------------------
# 呼吸 (SOFA-2: SpO2 替代 + 高级呼吸支持门控)
# -----------------------------------------------------------
def _calc_respiratory(
    obs: List[dict],
    eval_time: datetime,
    has_advanced_support: bool,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}

    # 先查 P/F ratio
    val, unit, ts = _worst_in_window(obs, ["param_bg_P/Fratio"], eval_time, _cfg.RESP_LOOKBACK_H, _cfg.RESP_STALENESS_MAX_H)
    if val is not None and val > 0:
        ratio = val
    else:
        val_pao2, _, ts_pao2 = _worst_in_window(obs, ["param_PaO2", "PaO2"], eval_time, _cfg.RESP_LOOKBACK_H, _cfg.RESP_STALENESS_MAX_H)
        val_fio2, _, ts_fio2 = _worst_in_window(obs, ["param_FiO2", "FiO2"], eval_time, _cfg.RESP_LOOKBACK_H, _cfg.RESP_STALENESS_MAX_H)
        if val_pao2 is not None and val_fio2 is not None and val_fio2 > 0:
            if ts_pao2 and ts_fio2 and abs((ts_pao2 - ts_fio2).total_seconds()) > 1800:
                info["respiratory_pair_mismatch"] = True
                return None, info
            fio2 = val_fio2 / 100.0 if val_fio2 > 1.0 else val_fio2
            ratio = val_pao2 / fio2
        else:
            # SpO2/FiO2 替代路径 (SOFA-2 特有)
            val_spo2, _, _ = _worst_in_window(obs, ["SpO2", "param_SpO2"], eval_time, _cfg.RESP_LOOKBACK_H, _cfg.RESP_STALENESS_MAX_H)
            if val_spo2 is not None and val_fio2 is not None and val_fio2 > 0:
                if val_spo2 >= 98:
                    info["spo2_98_no_fallback"] = True
                    return None, info
                fio2 = val_fio2 / 100.0 if val_fio2 > 1.0 else val_fio2
                sf_ratio = val_spo2 / fio2
                score = _score_from_thresholds(sf_ratio, _TH["respiratory"]["sf_thresholds"])
                # score=3/4 需高级呼吸支持门控
                if score >= 3 and not has_advanced_support:
                    score = 2
                info["spo2_fio2_ratio"] = sf_ratio
                return score, info
            info["respiratory_missing"] = True
            return None, info

    score = _score_from_thresholds(ratio, _TH["respiratory"]["pf_thresholds"])
    # score=3/4 需高级呼吸支持门控
    if score >= 3 and not has_advanced_support:
        score = 2
    info["pao2_fio2_ratio"] = ratio
    return score, info


# -----------------------------------------------------------
# 凝血
# -----------------------------------------------------------
def _calc_hemostasis(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    val, _, _ = _worst_in_window(
        obs, _TH["hemostasis"]["codes"], eval_time,
        _TH["hemostasis"]["lookback_hours"],
        _TH["hemostasis"]["max_staleness_hours"],
    )
    if val is None:
        info["hemostasis_missing"] = True
        return None, info
    return _score_from_thresholds(val, _TH["hemostasis"]["thresholds"]), info


# -----------------------------------------------------------
# 肝脏 (SOFA-2 用 mg/dL)
# -----------------------------------------------------------
def _calc_liver(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    val, unit, _ = _worst_in_window(
        obs, _TH["liver"]["codes"], eval_time,
        _TH["liver"]["lookback_hours"],
        _TH["liver"]["max_staleness_hours"],
        agg="max",
    )
    if val is None:
        info["liver_missing"] = True
        return None, info
    converted, err = _convert_to_sofa2_canonical(val, unit, "bilirubin")
    if err:
        info["liver_unit_error"] = err
        return None, info
    return _score_from_thresholds(converted, _TH["liver"]["thresholds"]), info


# -----------------------------------------------------------
# 脑 (SOFA-2: delirium 治疗 + motor fallback)
# -----------------------------------------------------------
# V=T 时的替代值 (气管插管无法评估语言)
_V_T_SUBSTITUTE = 1

def _parse_gcs(gcs_val: Any) -> Tuple[Optional[int], Optional[str]]:
    """
    解析 GCS 值。需求文档 7.3 第 8 条:
      - re.fullmatch, E/M 只允许一位数字
      - V=T → 返回 None + "V=T_motor_fallback" 错误
      - 范围 3-15
    """
    if gcs_val is None:
        return None, None
    if isinstance(gcs_val, (int, float)):
        total = int(gcs_val)
        if total < 3 or total > 15:
            return None, f"GCS 数值超范围: {total} (有效 3-15)"
        return total, None
    if isinstance(gcs_val, str):
        try:
            total = int(float(gcs_val))
            if total < 3 or total > 15:
                return None, f"GCS 数值超范围: {total} (有效 3-15)"
            return total, None
        except ValueError:
            pass
        pattern = r"^[Ee]([1-5])[Vv]([Tt1-5])[Mm]([1-6])$"
        m = re.fullmatch(pattern, gcs_val.strip())
        if m:
            e = int(m.group(1))
            v_raw = m.group(2)
            m_score = int(m.group(3))
            if v_raw.upper() == "T":
                return None, "V=T_motor_fallback"
            v = int(v_raw)
            total = e + v + m_score
            if total < 3 or total > 15:
                return None, f"GCS 编码计算结果超范围: E{e}V{v}M{m_score}={total}"
            return total, None
    return None, f"无法解析 GCS 值: {gcs_val}"


def _calc_brain(
    obs: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    codes = _TH["brain"]["codes"]
    lookback = _TH["brain"]["lookback_hours"]

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
        info["brain_missing"] = True
        return None, info

    raw_gcs = best.get("value_number") or best.get("value_text")
    gcs_total, parse_err = _parse_gcs(raw_gcs)
    if parse_err == "V=T_motor_fallback":
        # V=T: 走 motor fallback (需求文档 7.3 第 8 条)
        raw_text = str(raw_gcs).strip()
        vt_match = re.fullmatch(r"^[Ee]([1-5])[Vv][Tt][Mm]([1-6])$", raw_text)
        if vt_match:
            m_val = int(vt_match.group(2))
            motor_fallback = _TH["brain"].get("motor_fallback", {})
            fallback_score = motor_fallback.get(m_val)
            if fallback_score is not None:
                info["gcs_vt_motor_fallback"] = {"m": m_val, "fallback_score": fallback_score}
                return fallback_score, info
            else:
                info["gcs_parse_error"] = f"V=T 但 motor_fallback 无 M{m_val} 映射"
                return None, info
        else:
            info["gcs_parse_error"] = parse_err
            return None, info
    elif parse_err:
        info["gcs_parse_error"] = parse_err
        return None, info
    elif gcs_total is None:
        info["brain_missing"] = True
        return None, info
    else:
        # SOFA-2 brain thresholds
        score = _score_from_thresholds(gcs_total, _TH["brain"]["thresholds"])
    return score, info


# -----------------------------------------------------------
# 肾脏 (SOFA-2: mg/dL, mL/kg/h)
# -----------------------------------------------------------
def _calc_kidney(
    obs: List[dict],
    eval_time: datetime,
    weight_kg: Optional[float],
) -> Tuple[Optional[int], Dict[str, Any]]:
    info: Dict[str, Any] = {}
    score_creat = None
    score_urine = None

    # 肌酐 (mg/dL, 取最高值: 越高越差)
    val, unit, _ = _worst_in_window(
        obs, _TH["kidney"]["codes_creatinine"], eval_time,
        _TH["kidney"]["lookback_hours"],
        _TH["kidney"]["max_staleness_hours"],
        agg="max",
    )
    if val is not None:
        converted, err = _convert_to_sofa2_canonical(val, unit, "creatinine")
        if err:
            info["kidney_creatinine_unit_error"] = err
        else:
            score_creat = _score_from_thresholds(
                converted, _TH["kidney"]["creatinine_thresholds"]
            )

    # 尿量 (mL/kg/h, 需求文档 7.3 第 6 条: 粗粒度24h标记, 取总和)
    val, unit, _ = _worst_in_window(
        obs, _TH["kidney"]["codes_urine"], eval_time,
        _TH["kidney"]["lookback_hours"],
        _TH["kidney"]["max_staleness_hours"],
        agg="sum",
    )
    if val is not None and weight_kg and weight_kg > 0:
        normalized_u = _normalize_unit(unit)
        if normalized_u in ("ml/kg/h", "ml/kg/hr"):
            rate_per_kg_h = val
        elif normalized_u in ("ml/h", "ml/hr"):
            rate_per_kg_h = val / weight_kg
        elif normalized_u in ("ml/24h", "ml/24 hr", "ml/24hr"):
            rate_per_kg_h = val / weight_kg / 24.0
            info["urine_coarse_24h"] = True  # 需求文档 7.3 第 6 条
        else:
            info["kidney_urine_unit_error"] = f"未知尿量单位: {unit}"
            rate_per_kg_h = None

        if rate_per_kg_h is not None:
            # SOFA-2 尿量梯度
            if rate_per_kg_h < 0.3:
                score_urine = 3
            elif rate_per_kg_h < 0.5:
                score_urine = 2

    if score_creat is None and score_urine is None:
        info["kidney_missing"] = True
        return None, info

    parts = [s for s in (score_creat, score_urine) if s is not None]
    return max(parts) if parts else None, info


# -----------------------------------------------------------
# 心血管 (SOFA-2: NE+Epi sum, MAP fallback, MCS)
# -----------------------------------------------------------
def _calc_cardiovascular(
    obs: List[dict],
    eval_time: datetime,
    pressors: List[dict],
    weight_kg: Optional[float],
    mcs_present: bool = False,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """
    SOFA-2 心血管评分。
    JAMA 2025:
      - MCS(机械循环支持) → 4 分
      - NE+Epi 总和梯度: >0且≤0.2→2, >0.2且≤0.4→3, >0.4→4
      - 多巴胺独立: ≤20→2, 20-40→3, >40→4
      - other_vasopressor → 至少 2 分
      - MAP<70 且无升压药 → 1 分
    """
    info: Dict[str, Any] = {}

    # MCS → 4 分
    if mcs_present:
        info["mcs_4"] = True
        return 4, info

    has_active_pressor = False
    ne_dose_ugkgmin = 0.0
    epi_dose_ugkgmin = 0.0
    dopa_dose_ugkgmin = 0.0
    has_other_pressor = False
    dose_known = False

    for med in pressors:
        admin_end = med.get("admin_end")
        if admin_end and isinstance(admin_end, datetime):
            if admin_end < eval_time:
                continue
        med_name = (med.get("med_name") or "").lower()
        route = (med.get("route") or "")
        # 白名单: 静脉 静滴 静推 泵入 iv 任一命中即通过
        # route 缺失时不跳过, 照常计入并打 route_unknown 标记
        _IV_KEYWORDS = {"静脉", "静滴", "静推", "泵入", "iv"}
        route_lower = route.strip().lower()
        if route_lower and not any(kw in route_lower for kw in _IV_KEYWORDS):
            continue
        if not route_lower:
            info.setdefault("data_quality_flags", []).append("route_unknown")
        has_active_pressor = True

        # 剂量只能来自 adapter.ne_ugkgmin, 取不到走保底
        dose = med.get("dose_ugkgmin")
        if dose is not None and dose > 0:
            dose_known = True
            if "去甲" in med_name or "norepinephrine" in med_name or med_name == "ne":
                ne_dose_ugkgmin = max(ne_dose_ugkgmin, dose)
            elif "肾上腺" in med_name or "epinephrine" in med_name or med_name == "epi":
                epi_dose_ugkgmin = max(epi_dose_ugkgmin, dose)
            elif "多巴胺" in med_name or "dopamine" in med_name or med_name == "dopa":
                dopa_dose_ugkgmin = max(dopa_dose_ugkgmin, dose)
            else:
                has_other_pressor = True

    score = 0
    ne_epi_sum = ne_dose_ugkgmin + epi_dose_ugkgmin

    # NE+Epi sum 梯度
    if ne_epi_sum > 0:
        if ne_epi_sum <= 0.2:
            score = max(score, 2)
        elif ne_epi_sum <= 0.4:
            score = max(score, 3)
        else:
            score = max(score, 4)

    # 多巴胺独立梯度
    if dopa_dose_ugkgmin > 0:
        if dopa_dose_ugkgmin <= 20:
            score = max(score, 2)
        elif dopa_dose_ugkgmin <= 40:
            score = max(score, 3)
        else:
            score = max(score, 4)

    # other_vasopressor → 至少 2
    if has_other_pressor and score < 2:
        score = max(score, 2)

    # MAP<70 且无升压药 → 1
    map_val = None
    if not has_active_pressor:
        map_val, _, _ = _worst_in_window(obs, ["MAP", "mean_arterial_pressure"], eval_time, _cfg.RESP_LOOKBACK_H, 1)
        info["map_value"] = map_val
        if map_val is not None and map_val < 70:
            score = max(score, 1)

    # 需求文档 7.3 第 9 条: has_active_pressor 且剂量未知 → 读配置策略
    if has_active_pressor and not dose_known:
        policy = _cfg.VASO_DOSE_UNKNOWN_POLICY
        if policy == "min_band_2":
            score = max(score, 2)
        elif policy == "reject":
            info["dose_unknown_rejected"] = True
        # 不许硬编码 max(score, 2)

    info["has_active_pressor"] = has_active_pressor
    info["dose_known"] = dose_known
    info["ne_epi_sum"] = ne_epi_sum

    # 无升压药且无 MAP 数据 → 无法评估心血管
    if not has_active_pressor and map_val is None:
        info["cardiovascular_missing"] = True
        return None, info

    return score, info


# -----------------------------------------------------------
# 主入口
# -----------------------------------------------------------
def compute_sofa2(
    observations: List[dict],
    medications: List[dict],
    eval_time: datetime,
    has_advanced_support: bool = False,
    weight_kg: Optional[float] = None,
    mcs_present: bool = False,
) -> Dict[str, Any]:
    """
    计算 SOFA-2 2025 总分。

    铁律: 缺失数据返回 None，不得回退为 0。
    """
    if eval_time.tzinfo is None:
        raise ValueError("eval_time 必须有时区信息")

    flags: List[str] = []
    components: Dict[str, Any] = {}
    info: Dict[str, Any] = {}

    resp_score, resp_info = _calc_respiratory(observations, eval_time, has_advanced_support)
    info.update(resp_info)
    if resp_score is None:
        flags.append("respiratory_missing")
    components["respiratory"] = resp_score

    hem_score, hem_info = _calc_hemostasis(observations, eval_time)
    info.update(hem_info)
    if hem_score is None:
        flags.append("hemostasis_missing")
    components["hemostasis"] = hem_score

    liver_score, liver_info = _calc_liver(observations, eval_time)
    info.update(liver_info)
    if liver_score is None:
        flags.append("liver_missing")
    components["liver"] = liver_score

    brain_score, brain_info = _calc_brain(observations, eval_time)
    info.update(brain_info)
    if brain_score is None:
        flags.append("brain_missing")
    components["brain"] = brain_score

    kidney_score, kidney_info = _calc_kidney(observations, eval_time, weight_kg)
    info.update(kidney_info)
    if kidney_score is None:
        flags.append("kidney_missing")
    components["kidney"] = kidney_score

    cv_score, cv_info = _calc_cardiovascular(
        observations, eval_time, medications, weight_kg, mcs_present
    )
    info.update(cv_info)
    if cv_score is None:
        flags.append("cardiovascular_missing")
    components["cardiovascular"] = cv_score

    # 应用缺失策略 (SOFA_MISSING_POLICY)
    policy_result = _apply_policy(
        policy=_cfg.SOFA_MISSING_POLICY,
        components=components,
        data_quality_flags=flags,
        eval_time=eval_time,
    )
    components = policy_result["components"]
    total = policy_result["total"]
    if policy_result["imputed_organs"]:
        info["imputed_organs"] = policy_result["imputed_organs"]

    valid_scores = [s for s in components.values() if s is not None]

    # result_status: complete / partial / insufficient
    n_valid = len(valid_scores)
    n_total = len(components)
    completeness = n_valid / n_total if n_total > 0 else 0.0
    if n_valid == n_total:
        result_status = "complete"
    elif n_valid >= 1:
        result_status = "partial"
    else:
        result_status = "insufficient"

    return {
        "sofa2_score": total,
        "components": components,
        "data_quality_flags": flags,
        "meta": info,
        "result_status": result_status,
        "completeness": completeness,
    }
