"""
Bundle 判定引擎 — 纯函数。
基于需求文档 ICU-05 §2、§4 实现。

判定项只返回 True / False / None (None 不等于 False)。
缺失数据返回 None + data_quality_flags，不得回退为 0 或空值。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# 常量
# ============================================================

# VASO_WIDE: 所有 IV 泵入升压药
VASO_WIDE_LABELS = {
    "去甲肾上腺素", "norepinephrine", "ne",
    "肾上腺素", "epinephrine", "epi",
    "多巴胺", "dopamine",
    "多巴酚丁胺", "dobutamine",
    "血管加压素", "vasopressin",
    "苯肾上腺素", "phenylephrine",
    "去氧肾上腺素", "phenylephrine",
}

# VASO_STRICT: 仅去甲肾上腺素 + 肾上腺素
VASO_STRICT_LABELS = {
    "去甲肾上腺素", "norepinephrine", "ne",
    "肾上腺素", "epinephrine", "epi",
}

# 晶体液 + 胶体液关键词
CRYSTALLOID_KEYWORDS = {
    "生理盐水", "0.9%氯化钠", "ns", "normal saline",
    "乳酸林格", "林格", "lr", "lactated ringer",
    "醋酸林格", "醋酸", "plasmalyte",
    "复方氯化钠", "氯化钠",
}
COLLOID_KEYWORDS = {
    "白蛋白", "albumin",
    "羟乙基淀粉", "hes", "voluven",
    "明胶", "gelatin",
    "右旋糖酐", "dextran",
}


# ============================================================
# 辅助函数
# ============================================================

def _aware(dt: datetime) -> datetime:
    """确保时区感知。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _in_window(ts: datetime, start: datetime, end: datetime) -> bool:
    """检查时间戳是否在 [start, end] 窗口内。"""
    return start <= _aware(ts) <= end


def _classify_vasopressor(med_name: str) -> Tuple[bool, bool]:
    """
    分类升压药。
    返回 (in_wide, in_strict)。
    """
    name_lower = (med_name or "").strip().lower()
    in_wide = any(label in name_lower for label in VASO_WIDE_LABELS)
    in_strict = any(label in name_lower for label in VASO_STRICT_LABELS)
    return in_wide, in_strict


def _classify_fluid(med_name: str) -> Optional[str]:
    """
    分类液体类型。
    返回 "crystalloid" / "colloid" / None。
    """
    name_lower = (med_name or "").strip().lower()
    if any(kw in name_lower for kw in CRYSTALLOID_KEYWORDS):
        return "crystalloid"
    if any(kw in name_lower for kw in COLLOID_KEYWORDS):
        return "colloid"
    return None


# ============================================================
# T0 解析
# ============================================================

def resolve_septic_shock_t0(
    diagnoses: List[dict],
    eval_time: datetime,
) -> Tuple[Optional[datetime], Optional[str]]:
    """
    解析感染性休克 T0 时间。

    Args:
        diagnoses: 疾病诊断列表 (diseaseDiagnosis 或 VI_ICU_ZYYZ)
        eval_time: 评估时间

    Returns:
        (t0_time, t0_source) 或 (None, None)
        t0_source: "disease_diagnosis" / "vi_zyyz" / None
    """
    eval_time = _aware(eval_time)
    candidates = []

    for dx in diagnoses:
        # 检查诊断名称是否包含感染性休克关键词
        dx_name = (dx.get("diagnosisName") or dx.get("DIAGNOSIS_NAME") or "").strip()
        if not dx_name:
            continue

        is_septic_shock = any(
            kw in dx_name
            for kw in ["感染性休克", "septic shock", "脓毒症休克", "脓毒性休克"]
        )
        if not is_septic_shock:
            continue

        # 取诊断时间
        dx_time = dx.get("diagnosisTime") or dx.get("DIAGNOSIS_TIME") or dx.get("record_time")
        if not isinstance(dx_time, datetime):
            continue
        dx_time = _aware(dx_time)
        if dx_time > eval_time:
            continue

        source = "disease_diagnosis" if "diagnosisName" in dx else "vi_zyyz"
        candidates.append((dx_time, source))

    if not candidates:
        return None, None

    # 取最早的时间
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


# ============================================================
# SOFA 器官功能障碍判定
# ============================================================

def judge_sepsis_organ_dysfunction(
    sofa_score: Optional[int],
    sofa_threshold: int = 2,
) -> Optional[bool]:
    """
    判断是否存在脓毒症相关器官功能障碍。
    SOFA 总分 >= threshold → True。
    """
    if sofa_score is None:
        return None
    return sofa_score >= sofa_threshold


# ============================================================
# 1 小时 Bundle 判定
# ============================================================

def judge_1h_bundle(
    t0: Optional[datetime],
    eval_time: datetime,
    blood_culture_done: bool,
    blood_culture_time: Optional[datetime],
    lactate_measured: bool,
    lactate_time: Optional[datetime],
    antibiotic_done: bool,
    antibiotic_time: Optional[datetime],
    has_shock: bool,
) -> Dict[str, Optional[bool]]:
    """
    1 小时 Bundle 判定。

    需求文档 §4: 1h bundle 包含:
      S1: 乳酸测量 (T0后1h内)
      S2: 血培养 (使用抗生素前)
      S3: 抗生素 (T0后1h内)
      S4: 晶体液 30ml/kg (有低血压/乳酸≥4时)
    """
    result: Dict[str, Optional[bool]] = {}

    if t0 is None:
        return {
            "S1_lactate": None,
            "S2_blood_culture": None,
            "S3_antibiotic": None,
            "S4_fluid_resus": None,
        }

    t0 = _aware(t0)
    eval_time = _aware(eval_time)
    window_1h = t0 + timedelta(hours=1)

    # S1: 乳酸测量 (T0后1h内)
    if lactate_measured and lactate_time:
        result["S1_lactate"] = _in_window(lactate_time, t0, window_1h)
    else:
        result["S1_lactate"] = None

    # S2: 血培养 (使用抗生素前完成)
    if blood_culture_done and blood_culture_time:
        if antibiotic_time:
            result["S2_blood_culture"] = blood_culture_time <= antibiotic_time
        else:
            result["S2_blood_culture"] = True  # 已做血培养，无抗生素时间
    else:
        result["S2_blood_culture"] = None

    # S3: 抗生素 (T0后1h内)
    if antibiotic_done and antibiotic_time:
        result["S3_antibiotic"] = _in_window(antibiotic_time, t0, window_1h)
    else:
        result["S3_antibiotic"] = None

    # S4: 晶体液 30ml/kg (有低血压或乳酸≥4时)
    # 此项需要液体数据，暂时由外部传入
    result["S4_fluid_resus"] = None  # 需要液体数据

    return result


# ============================================================
# 3 小时 Bundle 判定
# ============================================================

def judge_3h_bundle(
    t0: Optional[datetime],
    eval_time: datetime,
    lactate_measured: bool,
    lactate_time: Optional[datetime],
    lactate_recheck: bool,
    lactate_recheck_time: Optional[datetime],
    blood_culture_done: bool,
    blood_culture_time: Optional[datetime],
    antibiotic_done: bool,
    antibiotic_time: Optional[datetime],
    fluid_30mlkg_done: bool,
    fluid_30mlkg_time: Optional[datetime],
) -> Dict[str, Optional[bool]]:
    """
    3 小时 Bundle 判定。

    需求文档 §4: 3h bundle 包含:
      I1: 乳酸测量 (T0后3h内)
      I2: 血培养 (使用抗生素前)
      I3: 抗生素 (T0后3h内)
      K1: 晶体液 30ml/kg (T0后3h内)
    """
    result: Dict[str, Optional[bool]] = {}

    if t0 is None:
        return {
            "I1_lactate": None,
            "I2_blood_culture": None,
            "I3_antibiotic": None,
            "K1_fluid_30mlkg": None,
        }

    t0 = _aware(t0)
    eval_time = _aware(eval_time)
    window_3h = t0 + timedelta(hours=3)

    # I1: 乳酸测量 (T0后3h内)
    if lactate_measured and lactate_time:
        result["I1_lactate"] = _in_window(lactate_time, t0, window_3h)
    else:
        result["I1_lactate"] = None

    # I2: 血培养 (使用抗生素前完成)
    if blood_culture_done and blood_culture_time:
        if antibiotic_time:
            result["I2_blood_culture"] = blood_culture_time <= antibiotic_time
        else:
            result["I2_blood_culture"] = True
    else:
        result["I2_blood_culture"] = None

    # I3: 抗生素 (T0后3h内)
    if antibiotic_done and antibiotic_time:
        result["I3_antibiotic"] = _in_window(antibiotic_time, t0, window_3h)
    else:
        result["I3_antibiotic"] = None

    # K1: 晶体液 30ml/kg (T0后3h内)
    if fluid_30mlkg_done and fluid_30mlkg_time:
        result["K1_fluid_30mlkg"] = _in_window(fluid_30mlkg_time, t0, window_3h)
    else:
        result["K1_fluid_30mlkg"] = None

    return result


# ============================================================
# 6 小时 Bundle 判定
# ============================================================

def judge_6h_bundle(
    t0: Optional[datetime],
    eval_time: datetime,
    has_shock: bool,
    map_target_met: bool,
    map_target_met_time: Optional[datetime],
    vasopressor_started: bool,
    vasopressor_start_time: Optional[datetime],
    initial_lactate: Optional[float],
    lactate_recheck_done: bool,
    lactate_recheck_time: Optional[datetime],
    fluid_1500_done: bool,
    fluid_1500_time: Optional[datetime],
) -> Dict[str, Optional[bool]]:
    """
    6 小时 Bundle 判定。

    需求文档 §4: 6h bundle 包含 (有低血压或乳酸≥4时):
      A1: 血管活性药维持 MAP≥65 (T0后6h内)
      B1: 乳酸复测 (T0后6h内，初始乳酸>2时)
      B2: 乳酸正常化
      B3: 乳酸下降率≥10%
      C1: 晶体液 1500ml (T0后6h内)
      C2: 胶体液 (如有)
      C3: 液体负荷后 MAP 变化
    """
    result: Dict[str, Optional[bool]] = {}

    if t0 is None:
        return {
            "A1_map_target": None,
            "B1_lactate_recheck": None,
            "B2_lactate_normal": None,
            "B3_lactate_decline": None,
            "C1_fluid_1500": None,
        }

    t0 = _aware(t0)
    eval_time = _aware(eval_time)
    window_6h = t0 + timedelta(hours=6)

    # A1: 血管活性药维持 MAP≥65 (T0后6h内)
    if has_shock:
        if map_target_met and map_target_met_time:
            result["A1_map_target"] = _in_window(map_target_met_time, t0, window_6h)
        elif vasopressor_started and vasopressor_start_time:
            result["A1_map_target"] = _in_window(vasopressor_start_time, t0, window_6h)
        else:
            result["A1_map_target"] = None
    else:
        result["A1_map_target"] = None  # 无休克不需评

    # B1: 乳酸复测 (初始乳酸>2时)
    if initial_lactate is not None and initial_lactate > 2:
        if lactate_recheck_done and lactate_recheck_time:
            result["B1_lactate_recheck"] = _in_window(lactate_recheck_time, t0, window_6h)
        else:
            result["B1_lactate_recheck"] = None
    else:
        result["B1_lactate_recheck"] = True  # 初始乳酸≤2，不需复测

    # B2: 乳酸正常化 (<2 mmol/L)
    # B3: 乳酸下降率≥10%
    # 这些需要复测乳酸值，由外部传入
    result["B2_lactate_normal"] = None
    result["B3_lactate_decline"] = None

    # C1: 晶体液 1500ml (T0后6h内)
    if fluid_1500_done and fluid_1500_time:
        result["C1_fluid_1500"] = _in_window(fluid_1500_time, t0, window_6h)
    else:
        result["C1_fluid_1500"] = None

    return result


# ============================================================
# Bundle 完成判定决策树 (需求文档 §4)
# ============================================================

def judge_bundle_finish(
    t0: Optional[datetime],
    has_shock: bool,
    judge_1h: Dict[str, Optional[bool]],
    judge_3h: Dict[str, Optional[bool]],
    judge_6h: Dict[str, Optional[bool]],
) -> Dict[str, Any]:
    """
    Bundle 完成判定决策树。

    需求文档 §4:
      1. 有感染性休克诊断 → 进入判定
      2. 1h bundle 完成? (S1+S2+S3 全 True)
      3. 3h bundle 完成? (I1+I2+I3+K1 全 True)
      4. 6h bundle 完成? (A1+B1+B2+B3+C1 全 True，仅休克患者)
      5. 总完成 = 1h完成 AND 3h完成 AND (6h完成 OR 无休克)
    """
    if t0 is None:
        return {
            "bundle_complete": None,
            "reason": "no_t0",
            "1h_complete": None,
            "3h_complete": None,
            "6h_complete": None,
        }

    # 1h 完成判定
    items_1h = ["S1_lactate", "S2_blood_culture", "S3_antibiotic"]
    vals_1h = [judge_1h.get(k) for k in items_1h]
    if all(v is True for v in vals_1h):
        complete_1h = True
    elif any(v is False for v in vals_1h):
        complete_1h = False
    else:
        complete_1h = None

    # 3h 完成判定
    items_3h = ["I1_lactate", "I2_blood_culture", "I3_antibiotic", "K1_fluid_30mlkg"]
    vals_3h = [judge_3h.get(k) for k in items_3h]
    if all(v is True for v in vals_3h):
        complete_3h = True
    elif any(v is False for v in vals_3h):
        complete_3h = False
    else:
        complete_3h = None

    # 6h 完成判定 (仅休克患者)
    if has_shock:
        items_6h = ["A1_map_target", "B1_lactate_recheck", "B2_lactate_normal",
                     "B3_lactate_decline", "C1_fluid_1500"]
        vals_6h = [judge_6h.get(k) for k in items_6h]
        if all(v is True for v in vals_6h):
            complete_6h = True
        elif any(v is False for v in vals_6h):
            complete_6h = False
        else:
            complete_6h = None
    else:
        complete_6h = True  # 无休克视为6h完成

    # 总完成判定
    if complete_1h is True and complete_3h is True and complete_6h is True:
        bundle_complete = True
    elif complete_1h is False or complete_3h is False or complete_6h is False:
        bundle_complete = False
    else:
        bundle_complete = None

    return {
        "bundle_complete": bundle_complete,
        "1h_complete": complete_1h,
        "3h_complete": complete_3h,
        "6h_complete": complete_6h,
        "has_shock": has_shock,
        "reason": None,
    }
