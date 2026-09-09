"""
脓毒性休克候选提取引擎。
高召回提取候选患者，与临床确认状态分离。

设计原则:
  - 高召回: 不确定状态不提前删除
  - 候选信号与临床确认分开
  - 候选通道、阈值和优先级配置化、版本化
  - 原始证据可追溯
  - 假阳性可以人工排除
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config.candidate_rules import (
    CANDIDATE_RULE_VERSION,
    CHANNEL_PRIORITY,
    DIAGNOSIS_POSITIVE_KEYWORDS,
    DIAGNOSIS_NEGATIVE_KEYWORDS,
    SEPTIC_SHOCK_DIAGNOSIS_KEYWORDS,
    SEPSIS_ONLY_DIAGNOSIS_KEYWORDS,
    LACTATE_STRICT_GT,
    classify_candidate,
    determine_clinical_confirmation,
)

logger = logging.getLogger(__name__)


def extract_candidate(
    diagnosis_text: Optional[str] = None,
    infection_evidence: Optional[dict] = None,
    has_vasopressor_wide: bool = False,
    has_vasopressor_strict: bool = False,
    vasopressor_status: Optional[str] = None,
    lactate_value: Optional[float] = None,
    map_value: Optional[float] = None,
    sofa2_result: Optional[dict] = None,
    classic_sofa_result: Optional[dict] = None,
    has_fluid_resuscitation: Optional[bool] = None,
    s1_s4_signals: Optional[dict] = None,
    has_advanced_support: bool = False,
    source: str = "unknown",
    *,
    v3_result: Optional[dict] = None,
    clinical_layer: Optional[dict] = None,
) -> dict:
    """
    单患者候选提取。

    支持两种调用方式:
    1. 直接传入各参数 (用于测试和精细控制)
    2. 传入 v3_result + clinical_layer (用于 summary.py 集成)

    Returns:
        候选提取完整结果，包含:
        - is_septic_shock_candidate: bool
        - candidate_status: high_probability | probable | pending_review | not_candidate
        - candidate_pathways: list[str]
        - candidate_reasons: list[str]
        - supporting_evidence: list[str]
        - missing_evidence: list[str]
        - conflicting_evidence: list[str]
        - infection_evidence: dict
        - organ_dysfunction_evidence: dict
        - shock_evidence: dict
        - clinical_confirmation_status: confirmed | pending_review | not_confirmed | insufficient
        - sofa2_current / sofa2_baseline / delta_sofa2
        - classic_sofa_current
        - rule_version: str
    """
    # ---- 适配器: 从 v3_result 提取参数 ----
    if v3_result is not None:
        # 从 v3_result 提取感染证据
        if infection_evidence is None:
            i1 = v3_result.get("i1") or v3_result.get("infection_evidence", {}).get("i1")
            i2 = v3_result.get("i2") or v3_result.get("infection_evidence", {}).get("i2")
            i3 = v3_result.get("i3") or v3_result.get("infection_evidence", {}).get("i3")
            has_infection = (i1 is True) or (i2 is True) or (i3 is True)
            infection_evidence = {
                "has_infection": has_infection,
                "i1": i1, "i2": i2, "i3": i3,
            }

        # 升压药
        if not has_vasopressor_wide:
            has_vasopressor_wide = v3_result.get("k2") or v3_result.get("has_vasopressor") or False
        if not has_vasopressor_strict:
            has_vasopressor_strict = v3_result.get("has_vasopressor_strict") or False
        # 升压药状态: unknown 作为复核信号，不得作为电子确认依据
        if vasopressor_status is None:
            vasopressor_status = v3_result.get("vasopressor_status", "active" if has_vasopressor_wide else "inactive")

        # 乳酸
        if lactate_value is None:
            lac = v3_result.get("lactate_initial") or v3_result.get("lactate_value")
            if lac is not None:
                lactate_value = float(lac)

        # MAP
        if map_value is None:
            m = v3_result.get("map_min") or v3_result.get("map_value")
            if m is not None:
                map_value = float(m)

        # SOFA 结果 — 兼容嵌套结构 v3["sofa"]["sofa2"] 和旧平铺 v3["sofa2"]
        if sofa2_result is None:
            sofa_container = v3_result.get("sofa") or {}
            sofa2_result = (
                sofa_container.get("sofa2")
                or v3_result.get("sofa2")
            )
        if classic_sofa_result is None:
            sofa_container = v3_result.get("sofa") or {}
            classic_sofa_result = (
                sofa_container.get("classic")
                or v3_result.get("classic")
            )

        # S1-S4 信号
        if s1_s4_signals is None:
            s1_s4_signals = {}
            for i in range(1, 5):
                key = f"s{i}"
                val = v3_result.get(key)
                if val is not None:
                    s1_s4_signals[key] = val

        # 液体复苏
        if has_fluid_resuscitation is None:
            has_fluid_resuscitation = v3_result.get("fluid_resuscitated")

        # 诊断文本
        if diagnosis_text is None:
            diagnosis_text = v3_result.get("diagnosis_text") or ""

        # 高级支持
        if not has_advanced_support:
            has_advanced_support = v3_result.get("has_advanced_support") or False
    reasons = []
    supporting = []
    missing = []
    conflicting = []

    # ---- 升压药状态: unknown 作为复核信号 ----
    # unknown 不得作为电子确认依据 (has_vasopressor_wide 仍为 False)
    # 但必须进入 missing_evidence 供人工复核
    if vasopressor_status == "unknown":
        missing.append("升压药状态未知 (无动作记录)，需人工复核")

    # ---- 感染证据 ----
    if infection_evidence is None:
        infection_evidence = {}
    has_infection = infection_evidence.get("has_infection")

    # ---- 明确诊断检查 (通道A) ----
    # 区分脓毒性休克诊断和脓毒症诊断
    # 关键: 先匹配脓毒性休克(更长的词)，再匹配脓毒症(更短的词)
    # 使用"最长匹配优先"避免"脓毒症"误匹配"脓毒性休克"
    has_diagnosis = False
    has_septic_shock_diagnosis = False
    has_sepsis_only_diagnosis = False
    diagnosis_details = {}
    if diagnosis_text:
        diag_lower = diagnosis_text.lower()
        # 检查否定关键词
        has_negative = any(kw in diag_lower for kw in DIAGNOSIS_NEGATIVE_KEYWORDS)
        # 先检查脓毒性休克关键词 (更具体的匹配)
        matched_shock = [kw for kw in SEPTIC_SHOCK_DIAGNOSIS_KEYWORDS if kw in diag_lower]
        # 再检查脓毒症关键词，但排除已匹配的休克关键词的子串
        matched_sepsis = []
        for kw in SEPSIS_ONLY_DIAGNOSIS_KEYWORDS:
            if kw in diag_lower:
                # 检查这个关键词是否是某个已匹配休克关键词的子串
                is_substring_of_shock = any(kw in skw for skw in matched_shock)
                if not is_substring_of_shock:
                    matched_sepsis.append(kw)

        if (matched_shock or matched_sepsis) and not has_negative:
            has_diagnosis = True
            if matched_shock:
                has_septic_shock_diagnosis = True
            if matched_sepsis and not matched_shock:
                has_sepsis_only_diagnosis = True
            diagnosis_details["text"] = diagnosis_text
            diagnosis_details["matched_keywords"] = matched_shock + matched_sepsis
            diagnosis_details["is_septic_shock"] = has_septic_shock_diagnosis
            diagnosis_details["is_sepsis_only"] = has_sepsis_only_diagnosis
            supporting.append("明确诊断: " + ", ".join(matched_shock + matched_sepsis))
            reasons.append("通道A: 明确诊断")
        elif (matched_shock or matched_sepsis) and has_negative:
            conflicting.append("诊断文本同时包含肯定和否定关键词")
        elif has_negative:
            missing.append("诊断文本包含否定关键词")

    # ---- 乳酸判定 (三态: True/False/None) ----
    # True: 乳酸已测且 > 2
    # False: 乳酸已测且 <= 2
    # None: 乳酸缺失或不可用
    lactate_gt_2 = None
    lactate_status = "missing"
    if lactate_value is not None:
        lactate_gt_2 = lactate_value > LACTATE_STRICT_GT
        if lactate_gt_2:
            lactate_status = "met"
            supporting.append(f"乳酸 {lactate_value:.1f} mmol/L > {LACTATE_STRICT_GT}")
        elif lactate_value == LACTATE_STRICT_GT:
            lactate_status = "borderline"
            conflicting.append(f"乳酸恰好等于 {LACTATE_STRICT_GT} mmol/L (边界值)")
        else:
            lactate_status = "measured_not_met"
            # 乳酸 <= 2 不算缺失，只是不满足
    else:
        lactate_status = "missing"
        missing.append("乳酸数据缺失")

    # ---- MAP ----
    map_below_65 = None
    if map_value is not None:
        map_below_65 = map_value < 65
        if map_below_65:
            supporting.append(f"MAP {map_value:.0f} mmHg < 65")
    else:
        missing.append("MAP 数据缺失")

    # ---- SOFA-2 ----
    sofa2_score = None
    sofa2_status = "insufficient"
    sofa2_components = {}
    sofa2_completeness = 0.0
    if sofa2_result:
        sofa2_score = sofa2_result.get("sofa2_score")
        sofa2_status = sofa2_result.get("result_status", "insufficient")
        sofa2_components = sofa2_result.get("components", {})
        sofa2_completeness = sofa2_result.get("completeness", 0.0)

    # ---- 经典 SOFA ----
    classic_score = None
    if classic_sofa_result:
        classic_score = classic_sofa_result.get("sofa_score")

    # ---- 器官功能异常 ----
    has_organ_dysfunction = False
    organ_evidence = {}

    # S1-S4 信号
    if s1_s4_signals:
        for key, val in s1_s4_signals.items():
            if val is True:
                has_organ_dysfunction = True
                organ_evidence[key] = True
                supporting.append(f"器官信号 {key}")

    # SOFA-2 当前 >= 2
    if sofa2_score is not None and sofa2_score >= 2:
        has_organ_dysfunction = True
        organ_evidence["sofa2_current_ge2"] = True
        supporting.append(f"SOFA-2 当前评分 {sofa2_score} >= 2")

    # 部分评分下限
    if sofa2_status == "partial":
        valid_scores = [v for v in sofa2_components.values() if v is not None]
        lower_bound = sum(valid_scores) if valid_scores else 0
        if lower_bound >= 2:
            has_organ_dysfunction = True
            organ_evidence["sofa2_partial_lower_bound_ge2"] = True
            supporting.append(f"SOFA-2 部分评分下限 {lower_bound} >= 2")
        missing.append(f"SOFA-2 部分评分 ({len(valid_scores)}/6 系统有值)")

    if not has_organ_dysfunction:
        missing.append("未检测到器官功能异常信号")

    # ---- 休克信号: 区分 confirmed 和 review ----
    # confirmed_shock_signal: 电子确认依据 (升压药active/乳酸高/MAP低/明确休克诊断)
    # review_shock_signal: 包含 confirmed + 升压药unknown (需人工复核)
    shock_evidence = {}

    confirmed_shock_signal = False
    review_shock_signal = False

    if vasopressor_status == "active":
        confirmed_shock_signal = True
        shock_evidence["vasopressor_active"] = True
        supporting.append("评估时点有升压药使用 (active)")

    if lactate_gt_2:
        confirmed_shock_signal = True
        shock_evidence["lactate_gt_2"] = True

    if map_below_65:
        confirmed_shock_signal = True
        shock_evidence["map_below_65"] = True

    if has_septic_shock_diagnosis:
        confirmed_shock_signal = True
        shock_evidence["explicit_septic_shock_diagnosis"] = True

    # review 包含 confirmed + unknown 升压药
    review_shock_signal = confirmed_shock_signal or (vasopressor_status == "unknown")

    if review_shock_signal:
        shock_evidence["review_signal"] = True
        if not confirmed_shock_signal:
            shock_evidence["vasopressor_unknown_review"] = True
            supporting.append("升压药状态未知，作为复核信号")
    else:
        missing.append("未检测到休克信号")

    # ---- 调用分类函数 ----
    # review_shock_signal 决定是否进入候选池
    # confirmed_shock_signal 决定是否可电子确认
    has_shock_signal = review_shock_signal
    candidate_status, candidate_pathways = classify_candidate(
        has_diagnosis=has_diagnosis,
        has_infection=has_infection is True,
        has_vasopressor=has_vasopressor_wide,
        lactate_gt_2=lactate_gt_2 is True,
        has_organ_dysfunction=has_organ_dysfunction,
        has_shock_signal=has_shock_signal,
        evidence_complete=len(missing) == 0,
        has_conflicting_evidence=len(conflicting) > 0,
        has_septic_shock_diagnosis=has_septic_shock_diagnosis,
        has_sepsis_only_diagnosis=has_sepsis_only_diagnosis,
    )

    # SOFA-2 补充通道
    if (candidate_status == "not_candidate"
        and sofa2_score is not None and sofa2_score >= 2
        and has_infection is True):
        candidate_status = "pending_review"
        candidate_pathways.append("sofa2_supplement")
        reasons.append("SOFA-2 补充发现")

    # 生成通道原因
    for pathway in candidate_pathways:
        if pathway not in ("pending_incomplete",):
            reasons.append(f"通道: {pathway}")

    # ---- 临床确认状态 ----
    # 基线信息 (从 sofa2_result 获取或标记未知)
    baseline_sofa2 = None
    baseline_known = False
    delta_sofa2 = None
    baseline_status = "unknown"
    assumption_applied = False

    if sofa2_result:
        meta = sofa2_result.get("meta", {})
        # 如果有基线信息 (由 build_clinical_layer 补充)
        baseline_sofa2 = sofa2_result.get("baseline_sofa2")
        if baseline_sofa2 is not None:
            baseline_known = True
            baseline_status = "measured"
            if sofa2_score is not None:
                delta_sofa2 = sofa2_score - baseline_sofa2

    # 部分评分时标记假设
    if sofa2_status == "partial" and not baseline_known:
        assumption_applied = True
        baseline_status = "unknown"

    clinical_confirmation = determine_clinical_confirmation(
        candidate_status=candidate_status,
        has_acute_organ_dysfunction=has_organ_dysfunction,
        baseline_known=baseline_known,
        delta_sofa2=delta_sofa2,
        sofa2_result_status=sofa2_status,
        volume_assessed=has_fluid_resuscitation,
        lactate_gt_2=lactate_gt_2,
        map_below_65_observed=map_below_65,
        vasopressor_active=has_vasopressor_wide,
    )

    return {
        "is_septic_shock_candidate": candidate_status != "not_candidate",
        "candidate_status": candidate_status,
        "candidate_pathways": candidate_pathways,
        "candidate_reasons": reasons,
        "supporting_evidence": supporting,
        "missing_evidence": missing,
        "conflicting_evidence": conflicting,
        "infection_evidence": {
            "has_infection": has_infection,
            "i1": infection_evidence.get("i1"),
            "i2": infection_evidence.get("i2"),
            "i3": infection_evidence.get("i3"),
            "diagnosis_details": diagnosis_details,
        },
        "organ_dysfunction_evidence": organ_evidence,
        "shock_evidence": shock_evidence,
        "confirmed_shock_signal": confirmed_shock_signal,
        "review_shock_signal": review_shock_signal,
        "clinical_confirmation_status": clinical_confirmation,
        "sofa2_current": sofa2_score,
        "sofa2_baseline": baseline_sofa2,
        "delta_sofa2": delta_sofa2,
        "sofa2_status": sofa2_status,
        "sofa2_completeness": sofa2_completeness,
        "classic_sofa_current": classic_score,
        "baseline_status": baseline_status,
        "assumption_applied": assumption_applied,
        "has_advanced_support": has_advanced_support,
        "lactate_value": lactate_value,
        "lactate_status": lactate_status,
        "map_value": map_value,
        "has_vasopressor": has_vasopressor_wide,
        "vasopressor_status": vasopressor_status,
        "has_septic_shock_diagnosis": has_septic_shock_diagnosis,
        "has_sepsis_only_diagnosis": has_sepsis_only_diagnosis,
        "rule_version": CANDIDATE_RULE_VERSION,
        "source": source,
    }


def compute_candidate_statistics(candidates: List[dict]) -> dict:
    """
    从候选列表计算统计数据。

    定义:
        evaluated = 所有被评估的事件
        raw_candidate_count = status != "not_candidate"
        not_candidate_count = status == "not_candidate"
        final_candidate_count = raw candidates - excluded candidates

    不变量:
        evaluated = raw_candidates + not_candidates
        raw_candidates = high_probability + probable + pending_review
        final_candidates = raw_candidates - excluded_candidates

    Returns:
        统计数据字典
    """
    evaluated = len(candidates)
    high_prob = sum(1 for c in candidates if c.get("candidate_status") == "high_probability")
    probable = sum(1 for c in candidates if c.get("candidate_status") == "probable")
    pending = sum(1 for c in candidates if c.get("candidate_status") == "pending_review")
    not_candidate = sum(1 for c in candidates if c.get("candidate_status") == "not_candidate")
    excluded = sum(1 for c in candidates
                   if c.get("excluded") is True
                   and c.get("candidate_status") != "not_candidate")

    raw_candidates = high_prob + probable + pending
    final_candidates = raw_candidates - excluded

    # 不变量断言
    assert evaluated == raw_candidates + not_candidate, (
        f"evaluated({evaluated}) != raw_candidates({raw_candidates}) + not_candidate({not_candidate})"
    )
    assert final_candidates >= 0, (
        f"final_candidates({final_candidates}) < 0"
    )

    # 来源统计
    sources = {}
    for c in candidates:
        for pathway in c.get("candidate_pathways", []):
            sources[pathway] = sources.get(pathway, 0) + 1

    return {
        "evaluated_event_count": evaluated,
        "raw_candidate_count": raw_candidates,
        "high_probability_count": high_prob,
        "probable_count": probable,
        "pending_review_count": pending,
        "not_candidate_count": not_candidate,
        "excluded_candidate_count": excluded,
        "final_candidate_count": final_candidates,
        "source_breakdown": sources,
        "rule_version": CANDIDATE_RULE_VERSION,
    }
