"""
SOFA 评分桥接层。
将 data_adapter 的输出喂入经典 SOFA 和 SOFA-2 评分器，
返回结构化评分结果，附加版本元数据。

铁律:
  - 本模块只做数据传递和结果包装，不做评分计算
  - 评分器返回 None 的分项如实传递，不得回填 0
  - 版本元数据从 sofa_rules.py 读取，不得硬编码
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def compute_sofa_scores(
    sc_pid: str,
    mrn: str,
    dc_pid: str,
    t0: datetime,
    eval_time: Optional[datetime] = None,
    weight_kg: Optional[float] = None,
) -> dict:
    """
    正式 SOFA 评分入口。
    从 MongoDB 提取数据，运行经典 SOFA 和 SOFA-2 评分器，返回完整结果。

    Args:
        sc_pid: SmartCare patient _id
        mrn: 病案号
        dc_pid: DataCenter pid
        t0: T0 时间
        eval_time: 评估时间，默认 T0+24h
        weight_kg: 体重 (可选)

    Returns:
        {
            "classic": {sofa_score, components, data_quality_flags, meta, result_status, completeness},
            "sofa2": {sofa2_score, components, data_quality_flags, meta, result_status, completeness},
            "eval_time": datetime,
            "t0": datetime,
            "fetch_meta": {...},
            "data_quality_flags": [...],
            "version_meta": {classic: {...}, sofa2: {...}},
        }
    """
    from scoring.data_adapter import fetch_patient_obs_meds
    from scoring.sofa_core import compute_sofa_classic
    from scoring.sofa2_core import compute_sofa2
    from scoring.sofa_rules import CLASSIC_SOFA_META, SOFA2_META

    if t0 is None:
        return _empty_result("NO_T0")

    t0 = _aware(t0)
    if eval_time is None:
        eval_time = t0 + timedelta(hours=24)
    eval_time = _aware(eval_time)

    # 1. 提取数据
    data = fetch_patient_obs_meds(sc_pid, mrn, dc_pid, t0, eval_time, weight_kg)
    observations = data["observations"]
    medications = data["medications"]
    has_advanced_support = data["has_advanced_support"]
    w_kg = data["weight_kg"]
    flags = list(data["data_quality_flags"])
    fetch_meta = data["fetch_meta"]

    # 2. 运行经典 SOFA
    classic_result = None
    try:
        classic_result = compute_sofa_classic(
            observations=observations,
            medications=medications,
            eval_time=eval_time,
            has_advanced_support=has_advanced_support,
            weight_kg=w_kg,
        )
    except Exception as e:
        logger.warning("Classic SOFA computation failed for sc_pid=%s: %s", sc_pid, e)
        flags.append(f"classic_sofa_error: {e}")

    # 3. 运行 SOFA-2
    sofa2_result = None
    try:
        sofa2_result = compute_sofa2(
            observations=observations,
            medications=medications,
            eval_time=eval_time,
            has_advanced_support=has_advanced_support,
            weight_kg=w_kg,
        )
    except Exception as e:
        logger.warning("SOFA-2 computation failed for sc_pid=%s: %s", sc_pid, e)
        flags.append(f"sofa2_error: {e}")

    # 4. 构建返回
    classic_out = classic_result or _empty_classic_result()
    sofa2_out = sofa2_result or _empty_sofa2_result()

    # 附加评分器内部的 data_quality_flags
    if classic_result:
        flags.extend(classic_result.get("data_quality_flags", []))
    if sofa2_result:
        flags.extend(sofa2_result.get("data_quality_flags", []))

    return {
        "classic": classic_out,
        "sofa2": sofa2_out,
        "eval_time": eval_time,
        "t0": t0,
        "fetch_meta": fetch_meta,
        "data_quality_flags": list(set(flags)),
        "version_meta": {
            "classic": CLASSIC_SOFA_META,
            "sofa2": SOFA2_META,
        },
    }


def compute_sofa_scores_from_data(
    observations: List[dict],
    medications: List[dict],
    eval_time: datetime,
    has_advanced_support: bool = False,
    weight_kg: Optional[float] = None,
    t0: Optional[datetime] = None,
) -> dict:
    """
    直接从预构建的观测/用药数据计算 SOFA 评分。
    用于测试或已有数据的场景。

    Args:
        observations: 标准化观测列表
        medications: 标准化用药列表
        eval_time: 评估时间
        has_advanced_support: 是否有高级呼吸支持
        weight_kg: 体重
        t0: T0 时间 (可选)

    Returns:
        与 compute_sofa_scores 相同结构
    """
    from scoring.sofa_core import compute_sofa_classic
    from scoring.sofa2_core import compute_sofa2
    from scoring.sofa_rules import CLASSIC_SOFA_META, SOFA2_META

    eval_time = _aware(eval_time)
    if t0 is not None:
        t0 = _aware(t0)

    flags = []

    # 运行经典 SOFA
    classic_result = None
    try:
        classic_result = compute_sofa_classic(
            observations=observations,
            medications=medications,
            eval_time=eval_time,
            has_advanced_support=has_advanced_support,
            weight_kg=weight_kg,
        )
    except Exception as e:
        logger.warning("Classic SOFA computation failed: %s", e)
        flags.append(f"classic_sofa_error: {e}")

    # 运行 SOFA-2
    sofa2_result = None
    try:
        sofa2_result = compute_sofa2(
            observations=observations,
            medications=medications,
            eval_time=eval_time,
            has_advanced_support=has_advanced_support,
            weight_kg=weight_kg,
        )
    except Exception as e:
        logger.warning("SOFA-2 computation failed: %s", e)
        flags.append(f"sofa2_error: {e}")

    classic_out = classic_result or _empty_classic_result()
    sofa2_out = sofa2_result or _empty_sofa2_result()

    if classic_result:
        flags.extend(classic_result.get("data_quality_flags", []))
    if sofa2_result:
        flags.extend(sofa2_result.get("data_quality_flags", []))

    return {
        "classic": classic_out,
        "sofa2": sofa2_out,
        "eval_time": eval_time,
        "t0": t0,
        "fetch_meta": {},
        "data_quality_flags": list(set(flags)),
        "version_meta": {
            "classic": CLASSIC_SOFA_META,
            "sofa2": SOFA2_META,
        },
    }


# ============================================================
# 临床识别层构建
# ============================================================

def build_clinical_layer(
    sofa_result: dict,
    infection_evidence: Optional[dict] = None,
    has_vasopressor_wide: bool = False,
    lactate_value: Optional[float] = None,
    map_value: Optional[float] = None,
    has_fluid_resuscitation: Optional[bool] = None,
    vaso_name: Optional[str] = None,
) -> dict:
    """
    基于 SOFA 评分结果构建五层临床识别结构。

    Args:
        sofa_result: compute_sofa_scores 返回值
        infection_evidence: {has_infection, i1, i2, i3}
        has_vasopressor_wide: VASO_WIDE 口径升压药
        lactate_value: 乳酸值 (用于休克判定)
        map_value: MAP 值 (用于休克判定)
        has_fluid_resuscitation: 是否有液体复苏
        vaso_name: 升压药名称

    Returns:
        五层临床识别结构
    """
    from config.indicator_windows import SOFA_GATE_MODE

    sofa2 = sofa_result.get("sofa2", {})
    classic = sofa_result.get("classic", {})

    sofa2_score = sofa2.get("sofa2_score")
    sofa2_components = sofa2.get("components", {})
    sofa2_completeness = sofa2.get("completeness", 0.0)
    sofa2_status = sofa2.get("result_status", "insufficient")

    classic_score = classic.get("sofa_score")

    # ---- Layer 1: 感染证据 ----
    if infection_evidence is None:
        infection_evidence = {}
    has_infection = infection_evidence.get("has_infection")
    layer1 = {
        "has_infection": has_infection,
        "i1": infection_evidence.get("i1"),
        "i2": infection_evidence.get("i2"),
        "i3": infection_evidence.get("i3"),
    }

    # ---- Layer 2: 急性器官功能障碍 ----
    # 使用 SOFA-2 总分 ≥ 2 作为判定标准 (Sepsis-3 口径)
    has_acute_organ_dysfunction = None
    organ_dysfunction_basis = "sofa2_total_ge_2"
    if sofa2_score is not None:
        has_acute_organ_dysfunction = sofa2_score >= 2
    elif sofa2_status == "insufficient":
        has_acute_organ_dysfunction = None  # 数据不足，无法判定

    layer2 = {
        "sofa2_total": sofa2_score,
        "sofa2_components": sofa2_components,
        "sofa2_completeness": sofa2_completeness,
        "sofa2_result_status": sofa2_status,
        "classic_total": classic_score,
        "has_acute_organ_dysfunction": has_acute_organ_dysfunction,
        "organ_dysfunction_basis": organ_dysfunction_basis,
        # S1-S4 保留为辅助信号
        "s1_signal": _organ_signal(sofa2_components, "respiratory"),
        "s2_signal": _organ_signal(classic.get("components", {}), "central_nervous_system"),
        "s3_signal": _organ_signal(classic.get("components", {}), "cardiovascular"),
        "s4_signal": has_vasopressor_wide,
    }

    # ---- Layer 3: 脓毒症判定 ----
    is_sepsis = None
    sepsis_basis = "sepsis3_sofa2"
    if has_infection is True and has_acute_organ_dysfunction is True:
        is_sepsis = True
    elif has_infection is False:
        is_sepsis = False
    elif has_acute_organ_dysfunction is False and has_infection is True:
        is_sepsis = False
    # else: 不确定

    layer3 = {
        "is_sepsis": is_sepsis,
        "sepsis_basis": sepsis_basis,
        "gate_mode": SOFA_GATE_MODE,
    }

    # ---- Layer 4: 脓毒性休克判定 ----
    # 独立于 K1∧K2 布尔判定
    shock_criteria = {
        "sepsis_confirmed": is_sepsis,
        "persistent_hypotension": None,
        "vasopressor_required": None,
        "lactate_gt_2": None,
        "volume_assessed": has_fluid_resuscitation,
    }

    # 乳酸判定 (严格 >2, 不是 ≥2)
    lactate_borderline = False
    if lactate_value is not None:
        if lactate_value == 2.0:
            lactate_borderline = True
            shock_criteria["lactate_gt_2"] = False
        else:
            shock_criteria["lactate_gt_2"] = lactate_value > 2

    # MAP 持续低血压
    map_recovered = False
    if map_value is not None:
        shock_criteria["persistent_hypotension"] = map_value < 65
        if map_value >= 65 and has_vasopressor_wide:
            map_recovered = True

    # 升压药需求
    shock_criteria["vasopressor_required"] = has_vasopressor_wide

    # 综合判定
    shock_status = _determine_shock_status(
        is_sepsis=is_sepsis,
        has_vasopressor=has_vasopressor_wide,
        lactate_value=lactate_value,
        lactate_borderline=lactate_borderline,
        map_value=map_value,
        map_recovered=map_recovered,
        has_fluid=has_fluid_resuscitation,
    )

    layer4 = {
        "shock_status": shock_status,
        "criteria": shock_criteria,
        "lactate_value": lactate_value,
        "lactate_borderline": lactate_borderline,
        "map_recovered": map_recovered,
        "vaso_name": vaso_name,
    }

    # ---- Layer 5: Bundle 完成 (由调用方填充) ----
    layer5 = {
        "1h": None,
        "3h": None,
        "6h": None,
    }

    return {
        "layer1_infection": layer1,
        "layer2_organ_dysfunction": layer2,
        "layer3_sepsis": layer3,
        "layer4_shock": layer4,
        "layer5_bundle": layer5,
    }


def _organ_signal(components: dict, organ: str) -> Optional[bool]:
    """将器官分值转换为辅助信号 (≥1 为 True)。"""
    score = components.get(organ)
    if score is None:
        return None
    return score >= 1


def _determine_shock_status(
    is_sepsis: Optional[bool],
    has_vasopressor: bool,
    lactate_value: Optional[float],
    lactate_borderline: bool,
    map_value: Optional[float],
    map_recovered: bool,
    has_fluid: Optional[bool],
) -> str:
    """
    综合判定脓毒性休克状态。
    返回: "confirmed" | "not_confirmed" | "pending_review" | "borderline" | "insufficient_data"
    """
    # 脓毒症未确认 → 不可能是脓毒性休克
    if is_sepsis is False:
        return "not_confirmed"
    if is_sepsis is None:
        return "insufficient_data"

    # 脓毒症已确认，检查休克条件
    # 需要: 升压药 + 乳酸>2 + 低血压
    if not has_vasopressor:
        return "not_confirmed"

    # 乳酸边界值
    if lactate_borderline:
        return "borderline"

    # 乳酸缺失
    if lactate_value is None:
        if has_vasopressor:
            return "pending_review"  # 有升压药但乳酸缺失
        return "insufficient_data"

    # 乳酸 ≤ 2
    if lactate_value <= 2:
        return "not_confirmed"

    # 乳酸 > 2 + 升压药
    # 检查 MAP 状态
    if map_recovered:
        # MAP 已恢复但仍依赖升压药 → 仍算休克
        return "confirmed"

    if map_value is not None and map_value >= 65 and not map_recovered:
        # MAP 正常且无升压药依赖 → 不确定
        return "pending_review"

    # 液体复苏状态
    if has_fluid is None:
        return "pending_review"  # 液体复苏状态未知

    # 满足所有条件
    return "confirmed"


def _empty_result(reason: str) -> dict:
    """返回空评分结果。"""
    return {
        "classic": _empty_classic_result(),
        "sofa2": _empty_sofa2_result(),
        "eval_time": None,
        "t0": None,
        "fetch_meta": {},
        "data_quality_flags": [reason],
        "version_meta": {},
    }


def _empty_classic_result() -> dict:
    return {
        "sofa_score": None,
        "components": {
            "respiratory": None, "coagulation": None, "liver": None,
            "cardiovascular": None, "central_nervous_system": None, "renal": None,
        },
        "data_quality_flags": ["no_data"],
        "meta": {},
        "result_status": "insufficient",
        "completeness": 0.0,
    }


def _empty_sofa2_result() -> dict:
    return {
        "sofa2_score": None,
        "components": {
            "respiratory": None, "hemostasis": None, "liver": None,
            "brain": None, "kidney": None, "cardiovascular": None,
        },
        "data_quality_flags": ["no_data"],
        "meta": {},
        "result_status": "insufficient",
        "completeness": 0.0,
    }
