"""
Bundle 排除原因码。
用于三层人工覆盖系统，记录排除/覆盖原因。

原因码格式: "category.sub_reason"

V3 原因码 (18个):
- bundle_judgment: Bundle 判定相关 (8个)
- data_quality: 数据质量相关 (4个)
- clinical: 临床相关 (4个)
- override: 人工覆盖相关 (4个)
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ============================================================
# 原因码定义 (V3 共18个)
# ============================================================

EXCLUSION_REASONS: Dict[str, Dict[str, str]] = {
    # Bundle 判定相关 (8个)
    "bundle_judgment": {
        "not_septic_shock": "非脓毒性休克 (K1/K2未确认)",
        "no_infection_evidence": "无感染证据 (I1/I2/I3均未确认)",
        "a1_not_met": "A1未达标: 乳酸未测量",
        "b3_not_met": "B3未达标: 抗生素未在血培养后使用",
        "c3_fluid_insufficient": "C3未达标: 液体量不足",
        "map_not_triggered": "MAP未触发 (<70mmHg)",
        "lactate_not_triggered": "乳酸未触发 (<4mmol/L)",
        "finish_false": "Bundle未完成",
    },
    # 数据质量相关 (4个)
    "data_quality": {
        "missing_critical": "关键数据缺失",
        "unit_mismatch": "单位不匹配",
        "value_outlier": "数值异常",
        "timestamp_conflict": "时间戳冲突",
    },
    # 临床相关 (4个)
    "clinical": {
        "chronic_organ_dysfunction": "慢性器官功能障碍",
        "contraindication": "治疗禁忌",
        "patient_refusal": "患者/家属拒绝",
        "alternative_diagnosis": "替代诊断",
    },
    # 人工覆盖相关 (4个)
    "override": {
        "clinical_judgment": "临床判断覆盖",
        "quality_improvement": "质量改进排除",
        "research_exclusion": "研究排除",
        "documentation_correction": "文书纠正",
    },
}


def get_reason_text(reason_code: str) -> str:
    """
    获取原因码的文本描述。

    Args:
        reason_code: 原因码，格式 "category.sub_reason"

    Returns:
        原因文本描述
    """
    parts = reason_code.split(".", 1)
    if len(parts) == 2:
        category, sub_reason = parts
        if category in EXCLUSION_REASONS:
            if sub_reason in EXCLUSION_REASONS[category]:
                return EXCLUSION_REASONS[category][sub_reason]
    return reason_code


def get_all_reasons() -> List[Dict[str, str]]:
    """
    获取所有原因码列表。

    Returns:
        [{"code": "data_quality.missing_critical", "text": "关键数据缺失"}, ...]
    """
    result = []
    for category, reasons in EXCLUSION_REASONS.items():
        for sub_reason, text in reasons.items():
            result.append({
                "code": f"{category}.{sub_reason}",
                "text": text,
                "category": category,
            })
    return result


def validate_reason_code(reason_code: str) -> bool:
    """
    验证原因码是否有效。

    Args:
        reason_code: 原因码

    Returns:
        True 如果有效
    """
    parts = reason_code.split(".", 1)
    if len(parts) != 2:
        return False
    category, sub_reason = parts
    return (
        category in EXCLUSION_REASONS
        and sub_reason in EXCLUSION_REASONS[category]
    )


def get_v3_reason_codes(v3_result: dict) -> List[str]:
    """
    从 V3 判定结果中提取原因码列表。

    Args:
        v3_result: judge_bundle_v3 返回的结果字典

    Returns:
        原因码列表，如 ["bundle_judgment.not_septic_shock"]
    """
    reasons = []

    # 检查脓毒性休克确认
    if v3_result.get("k1") != True or v3_result.get("k2") != True:
        reasons.append("bundle_judgment.not_septic_shock")

    # 检查感染证据
    if v3_result.get("i1") != True and v3_result.get("i2") != True and v3_result.get("i3") != True:
        reasons.append("bundle_judgment.no_infection_evidence")

    # 检查 Bundle 完成状态
    if v3_result.get("finish") == False:
        reasons.append("bundle_judgment.finish_false")

    # 检查各组件
    if v3_result.get("a1") == False:
        reasons.append("bundle_judgment.a1_not_met")

    if v3_result.get("b3") == False:
        reasons.append("bundle_judgment.b3_not_met")

    if v3_result.get("c3") == False:
        reasons.append("bundle_judgment.c3_fluid_insufficient")

    # 检查触发项
    if v3_result.get("c1") == False and v3_result.get("c2") == False:
        # C1 和 C2 都未触发
        if v3_result.get("map_min") is not None and v3_result.get("map_min") >= 70:
            reasons.append("bundle_judgment.map_not_triggered")
        if v3_result.get("lactate_max") is not None and v3_result.get("lactate_max") < 4:
            reasons.append("bundle_judgment.lactate_not_triggered")

    return reasons
