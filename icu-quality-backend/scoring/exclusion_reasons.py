"""
Bundle 排除原因码。
用于三层人工覆盖系统，记录排除/覆盖原因。

原因码格式: "category.sub_reason"
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ============================================================
# 原因码定义
# ============================================================

EXCLUSION_REASONS: Dict[str, Dict[str, str]] = {
    "data_quality": {
        "missing_critical": "关键数据缺失",
        "unit_mismatch": "单位不匹配",
        "value_outlier": "数值异常",
        "timestamp_conflict": "时间戳冲突",
    },
    "clinical": {
        "not_septic_shock": "非感染性休克",
        "chronic_organ_dysfunction": "慢性器官功能障碍",
        "contraindication": "治疗禁忌",
        "patient_refusal": "患者/家属拒绝",
    },
    "process": {
        "documentation_error": "文书记录错误",
        "system_error": "系统错误",
        "timing_issue": "时间判定问题",
    },
    "override": {
        "clinical_judgment": "临床判断",
        "quality_improvement": "质量改进",
        "research_exclusion": "研究排除",
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
