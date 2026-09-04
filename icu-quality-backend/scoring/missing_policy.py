"""
缺失数据策略。
四种策略:
  - official_day1_normal_imputation: 入ICU 24h 内缺失项用正常默认值填充
  - strict_partial: 仅对有值的器官求和
  - complete_case: 任一器官缺失则总分为 None
  - sequential_locf: 用上一次观测值向前填充 (Last Observation Carried Forward)

铁律: 缺失数据不得静默回退为 0 或空值。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MissingDataPolicy(StrEnum):
    OFFICIAL_DAY1_NORMAL_IMPUTATION = "official_day1_normal_imputation"
    STRICT_PARTIAL = "strict_partial"
    COMPLETE_CASE = "complete_case"
    SEQUENTIAL_LOCF = "sequential_locf"


# 各器官"正常默认值"
_NORMAL_DEFAULTS = {
    "respiratory": 0,
    "coagulation": 0,
    "hemostasis": 0,
    "liver": 0,
    "cardiovascular": 0,
    "central_nervous_system": 0,
    "brain": 0,
    "renal": 0,
    "kidney": 0,
}


def apply_policy(
    policy: str,
    components: Dict[str, Optional[int]],
    data_quality_flags: List[str],
    eval_time: Optional[datetime] = None,
    admission_time: Optional[datetime] = None,
    locf_cache: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    根据策略处理缺失的器官分值。

    Args:
        policy: 策略名称
        components: 各器官分值 (可能含 None)
        data_quality_flags: 缺失标记列表
        eval_time: 评估时间 (day1 imputation 需要)
        admission_time: 入 ICU 时间 (day1 imputation 需要)
        locf_cache: LOCF 缓存 {organ: last_score}

    Returns:
        {
            "components": Dict[str, Optional[int]],
            "total": Optional[int],
            "imputed_organs": List[str],
        }
    """
    imputed: List[str] = []
    result_components: Dict[str, Optional[int]] = dict(components)

    if policy == MissingDataPolicy.OFFICIAL_DAY1_NORMAL_IMPUTATION:
        if eval_time and admission_time:
            if admission_time.tzinfo is None:
                admission_time = admission_time.replace(tzinfo=timezone.utc)
            if eval_time.tzinfo is None:
                eval_time = eval_time.replace(tzinfo=timezone.utc)
            is_day1 = (eval_time - admission_time) < timedelta(hours=24)
        else:
            is_day1 = False

        for organ, score in result_components.items():
            if score is None and is_day1:
                default = _NORMAL_DEFAULTS.get(organ)
                if default is not None:
                    result_components[organ] = default
                    imputed.append(organ)
                    logger.info(f"Day1 imputation: {organ}={default}")

    elif policy == MissingDataPolicy.STRICT_PARTIAL:
        # 不做任何填充，直接用 None 参与总分计算
        pass

    elif policy == MissingDataPolicy.COMPLETE_CASE:
        # 任一缺失则全部置 None
        if any(s is None for s in result_components.values()):
            for organ in result_components:
                result_components[organ] = None
            return {
                "components": result_components,
                "total": None,
                "imputed_organs": [],
            }

    elif policy == MissingDataPolicy.SEQUENTIAL_LOCF:
        if locf_cache:
            for organ, score in result_components.items():
                if score is None and organ in locf_cache:
                    result_components[organ] = locf_cache[organ]
                    imputed.append(organ)
                    logger.info(f"LOCF: {organ}={locf_cache[organ]}")

    # 计算总分
    valid_scores = [s for s in result_components.values() if s is not None]
    total = sum(valid_scores) if valid_scores else None

    return {
        "components": result_components,
        "total": total,
        "imputed_organs": imputed,
    }
