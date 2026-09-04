"""
Bundle 判定引擎 V3 — 纯函数。
基于需求文档 ICU-05 v3 §2 §4 实现。

判定项只返回 True / False / None (None 不等于 False)。
缺失数据返回 None + data_quality_flags，不得回退为 0 或空值。

v3 判定项:
  器官障碍: S1(氧合指数<300) S2(GCS<13) S3(MAP<70) S4(血管活性药)
  感染证据: I1(诊断关键词) I2(抗生素执行) I3(病原学送检)
  休克确认: K1(乳酸≥2) K2(需要升压)
  第一步:   A1(乳酸测定)
  第二步:   B1(抗生素时间) B2(血培养时间) B3(B1∧B2∧B1晚于B2)
  第三步:   C1(MAP<70触发) C2(乳酸≥4触发) C3(液体达标)
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
    "米力农", "milrinone",
    "异丙肾上腺素", "isoproterenol",
}

# VASO_STRICT: SOFA-2 白名单 8 种
VASO_STRICT_LABELS = {
    "去甲肾上腺素", "norepinephrine", "ne",
    "肾上腺素", "epinephrine", "epi",
    "多巴胺", "dopamine",
    "多巴酚丁胺", "dobutamine",
    "血管加压素", "vasopressin",
    "苯肾上腺素", "phenylephrine",
    "米力农", "milrinone",
    "异丙肾上腺素", "isoproterenol",
}

# 感染诊断关键词
INFECTION_DIAG_KEYWORDS = [
    "脓毒", "败血", "感染性休克", "感染", "肺炎", "腹膜炎",
    "脑膜炎", "蜂窝织炎", "脓肿", "化脓", "尿路感染", "胆管炎",
    "septic", "sepsis", "infection",
]

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
    return start <= _aware(ts) <= _aware(end)


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
# v3 判定项：器官障碍 S1-S4
# ============================================================

def judge_S1_pfratio(pf_ratio: Optional[float]) -> Optional[bool]:
    """S1: 氧合指数 < 300 (窗口内最低值)"""
    if pf_ratio is None:
        return None
    return pf_ratio < 300


def judge_S2_gcs(gcs: Optional[int]) -> Optional[bool]:
    """S2: GCS < 13 (评分表数字总分优先，bedside编码兜底)"""
    if gcs is None:
        return None
    return gcs < 13


def judge_S3_map(map_value: Optional[float]) -> Optional[bool]:
    """S3: 平均动脉压 < 70 mmHg (有创+无创混合，窗口内最低值)"""
    if map_value is None:
        return None
    return map_value < 70


def judge_S4_vasopressor(has_vasopressor: Optional[bool]) -> Optional[bool]:
    """S4: 血管活性药 VASO_WIDE 口径 (存在即成立)"""
    if has_vasopressor is None:
        return False  # 缺失处理: false
    return has_vasopressor


# ============================================================
# v3 判定项：感染证据 I1-I3
# ============================================================

def judge_I1_infection_diag(diagnosis_text: Optional[str]) -> Optional[bool]:
    """I1: 诊断含感染关键词 (入院/入科/病程诊断)"""
    if not diagnosis_text:
        return False  # 缺失处理: false
    text_lower = diagnosis_text.lower()
    return any(kw in text_lower for kw in INFECTION_DIAG_KEYWORDS)


def judge_I2_antibiotic(has_antibiotic: Optional[bool]) -> Optional[bool]:
    """I2: 抗感染治疗执行 (窗口内有执行)"""
    if has_antibiotic is None:
        return False
    return has_antibiotic


def judge_I3_culture(has_culture: Optional[bool]) -> Optional[bool]:
    """I3: 病原学送检 (窗口内有送检)"""
    if has_culture is None:
        return False
    return has_culture


# ============================================================
# v3 判定项：休克确认 K1-K2
# ============================================================

def judge_K1_lactate(lactate: Optional[float]) -> Optional[bool]:
    """K1: 血乳酸 ≥ 2 mmol/L"""
    if lactate is None:
        return None
    return lactate >= 2


def judge_K2_pressor_needed(has_vasopressor: Optional[bool]) -> Optional[bool]:
    """K2: 是否需要升压 VASO_WIDE 口径"""
    if has_vasopressor is None:
        return False
    return has_vasopressor


# ============================================================
# v3 判定项：Bundle 时间窗
# ============================================================

def judge_A1_lactate_measured(lactate_value: Optional[float]) -> Optional[bool]:
    """A1: 乳酸测定 (窗口内最早一条，取到值即达标)"""
    if lactate_value is None:
        return None
    return True


def judge_B1_antibiotic_time(antibiotic_time: Optional[datetime]) -> Optional[bool]:
    """B1: 抗菌药物执行时间 (窗口内倒序取第一条，有值即达标)"""
    if antibiotic_time is None:
        return None
    return True


def judge_B2_culture_time(culture_time: Optional[datetime]) -> Optional[bool]:
    """B2: 血培养执行时间 (窗口内倒序取第一条，有值即达标)"""
    if culture_time is None:
        return None
    return True


def judge_B3_step2(
    b1: Optional[bool], b2: Optional[bool],
    antibiotic_time: Optional[datetime],
    culture_time: Optional[datetime],
) -> Optional[bool]:
    """
    B3: 第二步达标 = B1有值 AND B2有值 AND B1晚于B2
    即：抗生素执行时间晚于血培养执行时间
    """
    if b1 is None or b2 is None:
        return None
    if not b1 or not b2:
        return False
    if antibiotic_time is None or culture_time is None:
        return None
    # 抗生素晚于或等于血培养 → 达标
    return antibiotic_time >= culture_time


def judge_C1_map_trigger(map_value: Optional[float]) -> Optional[bool]:
    """C1: MAP < 70 (触发项)"""
    if map_value is None:
        return None
    return map_value < 70


def judge_C2_lactate_trigger(lactate_max: Optional[float]) -> Optional[bool]:
    """C2: 血乳酸 ≥ 4 (触发项)"""
    if lactate_max is None:
        return None
    return lactate_max >= 4


def judge_C3_1h_fluid(has_fluid_1h: Optional[bool]) -> Optional[bool]:
    """C3-1h: 1h内有液体执行"""
    if has_fluid_1h is None:
        return None
    return has_fluid_1h


def judge_C3_3h_fluid(fluid_3h_ml: Optional[float], threshold: float = 1500) -> Optional[bool]:
    """C3-3h: 液体量 ≥ 1500ml"""
    if fluid_3h_ml is None:
        return None
    return fluid_3h_ml >= threshold


# ============================================================
# v3 完成判定决策树 (§4)
# ============================================================

def judge_bundle_finish_v3(
    a1: Optional[bool],
    b3: Optional[bool],
    c1: Optional[bool],
    c2: Optional[bool],
    c3: Optional[bool],
) -> Dict[str, Any]:
    """
    v3 完成判定决策树。

    第一步达标 = A1
    第二步达标 = B3
    第三步达标 = (C1 或 C2) ? C3 : 视为达标
    finish = 第一步达标 AND 第二步达标 AND 第三步达标
    """
    # 第一步
    step1 = a1

    # 第二步
    step2 = b3

    # 第三步
    c1_or_c2_triggered = (c1 is True) or (c2 is True)
    if c1_or_c2_triggered:
        step3 = c3
    else:
        step3 = True  # 未触发视为达标

    # 总完成
    if step1 is True and step2 is True and step3 is True:
        finish = True
    elif step1 is False or step2 is False or step3 is False:
        finish = False
    else:
        finish = None  # 缺失数据无法判定

    # 原因码
    reasons = []
    if step1 is False:
        reasons.append("A1_NOT_MET")
    if step2 is False:
        if b3 is False:
            reasons.append("BC_AFTER_AB")  # 抗生素早于血培养
        else:
            reasons.append("AB_MISSING")
    if step3 is False:
        if c1_or_c2_triggered:
            reasons.append("FLUID_INSUFFICIENT")
        else:
            reasons.append("MAP_NOT_MET")

    return {
        "finish": finish,
        "step1": step1,
        "step2": step2,
        "step3": step3,
        "finish_path": "triggered" if c1_or_c2_triggered else "not_triggered",
        "reasons": reasons,
    }


# ============================================================
# 完整 Bundle 判定（单个患者）
# ============================================================

def judge_bundle_v3(patient_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    对单个患者执行 v3 全量 Bundle 判定。

    patient_data 需包含:
        - t0: T0 时间
        - eval_time: 评估时间
        - diagnosis_text: 诊断文本 (I1)
        - has_antibiotic: 是否有抗生素执行 (I2)
        - has_culture: 是否有病原学送检 (I3)
        - has_vasopressor: 是否有血管活性药 (S4/K2)
        - lactate_initial: 初始乳酸值 (K1/A1)
        - lactate_max: 最高乳酸值 (C2)
        - map_min: 最低MAP值 (S3/C1)
        - gcs_min: 最低GCS值 (S2)
        - pf_ratio_min: 最低P/F比值 (S1)
        - antibiotic_time: 抗生素执行时间 (B1)
        - culture_time: 血培养执行时间 (B2)
        - has_fluid_1h: 1h内有液体执行 (C3-1h)
        - fluid_3h_ml: 3h液体量 (C3-3h)

    返回完整判定结果。
    """
    t0 = patient_data.get("t0")
    if not t0:
        return {"finish": None, "reason": "NO_T0"}

    # 器官障碍 S1-S4
    s1 = judge_S1_pfratio(patient_data.get("pf_ratio_min"))
    s2 = judge_S2_gcs(patient_data.get("gcs_min"))
    s3 = judge_S3_map(patient_data.get("map_min"))
    s4 = judge_S4_vasopressor(patient_data.get("has_vasopressor"))

    # 感染证据 I1-I3
    i1 = judge_I1_infection_diag(patient_data.get("diagnosis_text"))
    i2 = judge_I2_antibiotic(patient_data.get("has_antibiotic"))
    i3 = judge_I3_culture(patient_data.get("has_culture"))

    # 休克确认 K1-K2
    k1 = judge_K1_lactate(patient_data.get("lactate_initial"))
    k2 = judge_K2_pressor_needed(patient_data.get("has_vasopressor"))

    # 脓毒性休克确认: K1 AND K2
    has_septic_shock = (k1 is True) and (k2 is True)
    if not has_septic_shock:
        return {
            "finish": None,
            "is_septic_shock": False,
            "reason": "NOT_SEPTIC_SHOCK",
            "k1": k1, "k2": k2,
            "s1": s1, "s2": s2, "s3": s3, "s4": s4,
            "i1": i1, "i2": i2, "i3": i3,
        }

    # 感染证据门控: I1/I2/I3 任一
    has_infection = (i1 is True) or (i2 is True) or (i3 is True)
    if not has_infection:
        return {
            "finish": None,
            "is_septic_shock": True,
            "reason": "NO_INFECTION_EVIDENCE",
            "k1": k1, "k2": k2,
            "s1": s1, "s2": s2, "s3": s3, "s4": s4,
            "i1": i1, "i2": i2, "i3": i3,
        }

    # Bundle 时间窗判定
    a1 = judge_A1_lactate_measured(patient_data.get("lactate_initial"))
    b1 = judge_B1_antibiotic_time(patient_data.get("antibiotic_time"))
    b2 = judge_B2_culture_time(patient_data.get("culture_time"))
    b3 = judge_B3_step2(b1, b2, patient_data.get("antibiotic_time"), patient_data.get("culture_time"))
    c1 = judge_C1_map_trigger(patient_data.get("map_min"))
    c2 = judge_C2_lactate_trigger(patient_data.get("lactate_max"))
    c3_1h = judge_C3_1h_fluid(patient_data.get("has_fluid_1h"))
    c3_3h = judge_C3_3h_fluid(patient_data.get("fluid_3h_ml"))

    # C3 = C3-1h (1h窗口) 或 C3-3h (3h窗口)
    c3 = c3_1h if c3_1h is not None else c3_3h

    # 完成判定
    result = judge_bundle_finish_v3(a1, b3, c1, c2, c3)

    # 合并所有判定项
    result.update({
        "s1": s1, "s2": s2, "s3": s3, "s4": s4,
        "i1": i1, "i2": i2, "i3": i3,
        "k1": k1, "k2": k2,
        "a1": a1, "b1": b1, "b2": b2, "b3": b3,
        "c1": c1, "c2": c2, "c3": c3,
        "c3_1h": c3_1h, "c3_3h": c3_3h,
        "is_septic_shock": has_septic_shock,
        "has_infection": has_infection,
        "t0": t0,
    })

    return result
