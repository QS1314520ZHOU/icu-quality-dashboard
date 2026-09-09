"""
脓毒性休克候选提取规则配置。
版本化、配置化，不散落在查询/汇总/前端代码中。

候选通道:
  通道A: 明确诊断 (当前住院/ICU事件存在医师明确脓毒性休克诊断)
  通道B: 强休克证据 (感染 + 升压药 + 乳酸>2)
  通道C: 组合证据 (感染 + 器官功能异常 + 循环衰竭/休克信号)
  通道D: 证据不完整但不能排除 (进入 pending_review)

候选分级:
  high_probability: 感染 + 升压药 + 乳酸>2 + 器官功能异常
  probable: 感染 + 休克信号 + 器官功能异常，但一项关键证据不完整
  pending_review: 存在明确诊断或强组合信号，但数据不足
  not_candidate: 数据充分且不满足任何候选通道
"""

# 规则版本 (修改规则时 +1)
CANDIDATE_RULE_VERSION = "1.0.0"

# 乳酸阈值 (与 LACTATE_STRICT_GT 相同，供 candidate_engine 使用)
LACTATE_THRESHOLD = 2.0
LACTATE_BORDERLINE = 2.0  # 边界值

# 候选通道优先级 (高优先级通道覆盖低优先级)
CHANNEL_PRIORITY = {
    "diagnosis": 1,       # 通道A: 明确诊断
    "strong_shock": 2,    # 通道B: 强休克证据
    "composite": 3,       # 通道C: 组合证据
    "pending_incomplete": 4,  # 通道D: 证据不完整
    "sofa2_supplement": 5,    # SOFA-2 补充发现
}

# 通道A: 明确诊断关键词 (必须排除否定/不确定文本)
DIAGNOSIS_POSITIVE_KEYWORDS = [
    "脓毒性休克", "感染性休克", "septic shock", "septic_shock",
    "脓毒症休克", "败血症休克",
    "脓毒症", "败血症", "sepsis",
]

DIAGNOSIS_NEGATIVE_KEYWORDS = [
    "排除脓毒症", "排除感染", "脓毒症待排", "感染待排",
    "不支持脓毒症", "非脓毒性", "非感染性休克",
    "排除", "待排", "否认", "不考虑",
]

# 脓毒症诊断关键词 (正向/否定) - 别名
SEPSIS_DIAG_POSITIVE_KEYWORDS = DIAGNOSIS_POSITIVE_KEYWORDS
SEPSIS_DIAG_NEGATIVE_KEYWORDS = DIAGNOSIS_NEGATIVE_KEYWORDS

# 通道B: 强休克证据阈值
LACTATE_STRICT_GT = 2.0  # 乳酸严格 >2 mmol/L

# 通道C: 器官功能异常信号来源
ORGAN_DYSFUNCTION_SOURCES = [
    "s1_s4",              # 现有 S1-S4 门控
    "sofa2_current_ge2",  # 当前 SOFA-2 >= 2
    "delta_sofa2_ge2",    # ΔSOFA-2 >= 2
    "delta_classic_ge2",  # 经典 SOFA 急性增加 >= 2
    "lab_abnormal",       # 血小板/胆红素/肌酐/尿量异常
    "respiratory_support", # 呼吸支持
    "circulatory_support", # 循环支持
    "cns_abnormal",       # 中枢神经系统异常
]

# 循环衰竭/休克信号
SHOCK_SIGNALS = [
    "vasopressor_active",  # 评估时点实际使用升压药
    "map_below_65",        # MAP < 65 mmHg
    "lactate_gt_2",        # 乳酸 > 2
]

# 候选分级规则
def classify_candidate(
    has_diagnosis: bool,
    has_infection: bool,
    has_vasopressor: bool,
    lactate_gt_2: bool,
    has_organ_dysfunction: bool,
    has_shock_signal: bool,
    evidence_complete: bool,
    has_conflicting_evidence: bool,
) -> tuple[str, list[str]]:
    """
    根据证据分类候选等级。

    Returns:
        (candidate_status, candidate_pathways)
    """
    pathways = []

    # 通道A: 明确诊断
    if has_diagnosis:
        pathways.append("diagnosis")

    # 通道B: 强休克证据
    if has_infection and has_vasopressor and lactate_gt_2:
        pathways.append("strong_shock")

    # 通道C: 组合证据
    if has_infection and has_organ_dysfunction and has_shock_signal:
        pathways.append("composite")

    # 通道D: 证据不完整
    if has_infection and has_vasopressor and not lactate_gt_2:
        # 感染+升压药但乳酸缺失/不满足
        pathways.append("pending_incomplete")
    elif has_diagnosis and not evidence_complete:
        pathways.append("pending_incomplete")

    if not pathways:
        if has_infection and not evidence_complete:
            # 有感染信号但数据不完整，不能排除
            return "pending_review", ["pending_incomplete"]
        return "not_candidate", []

    # 分级
    if "strong_shock" in pathways and has_organ_dysfunction:
        return "high_probability", pathways

    if "strong_shock" in pathways:
        return "probable", pathways

    if "diagnosis" in pathways:
        if has_infection and has_vasopressor and has_organ_dysfunction:
            return "high_probability", pathways
        if evidence_complete:
            return "probable", pathways
        return "pending_review", pathways

    if "composite" in pathways:
        if has_vasopressor and lactate_gt_2:
            return "high_probability", pathways
        return "probable", pathways

    if "pending_incomplete" in pathways:
        return "pending_review", pathways

    return "not_candidate", []


def determine_clinical_confirmation(
    candidate_status: str,
    has_acute_organ_dysfunction: bool | None,
    baseline_known: bool,
    delta_sofa2: float | None,
    sofa2_result_status: str,
    volume_assessed: bool | None,
    lactate_gt_2: bool | None,
    map_below_65_observed: bool | None,
    vasopressor_active: bool,
) -> str:
    """
    临床确认状态 (独立于候选信号)。

    Returns:
        clinical_confirmation_status: confirmed | pending_review | not_confirmed | insufficient
    """
    if candidate_status == "not_candidate":
        return "not_confirmed"

    if candidate_status == "insufficient" or sofa2_result_status == "insufficient":
        return "insufficient"

    # 部分评分或基线未知 → 不能自动确认
    if sofa2_result_status == "partial":
        return "pending_review"

    if not baseline_known:
        return "pending_review"

    # 容量状态未知 → 不能自动确认
    if volume_assessed is None:
        return "pending_review"

    # 容量明确不足 → 不能自动确认
    if volume_assessed is False:
        return "pending_review"

    # 满足所有条件
    if (has_acute_organ_dysfunction is True
        and vasopressor_active
        and lactate_gt_2 is True
        and volume_assessed is True):
        return "confirmed"

    return "pending_review"


# ============================================================
# SOFA 评分阈值
# ============================================================
MAP_THRESHOLD = 65  # MAP 低于此值视为低血压
SOFA2_ORGAN_DYSFUNCTION_THRESHOLD = 2  # SOFA-2 器官功能障碍阈值
SOFA2_DELTA_THRESHOLD = 2  # ΔSOFA-2 急性增加阈值

# ============================================================
# Bundle 6h 状态
# ============================================================
# rule_pending: 6h规则待确认（当前未实现完整6h判定）
# implemented: 6h规则已实现
BUNDLE_6H_STATUS = "rule_pending"
