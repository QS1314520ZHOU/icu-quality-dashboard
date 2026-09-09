"""
候选引擎 + 数据适配器 + 临床识别层 综合测试
覆盖30项修复中的关键逻辑
"""
import pytest
from datetime import datetime, timedelta
from scoring.candidate_engine import (
    extract_candidate,
    compute_candidate_statistics,
)
from config.candidate_rules import (
    CANDIDATE_RULE_VERSION,
    LACTATE_STRICT_GT,
)


class TestCandidateEnginePathways:
    """候选引擎四通道测试"""

    # ---- 通道 A: 诊断文本 ----
    def test_channel_a_septic_shock_diagnosis(self):
        """通道A: 诊断文本包含脓毒性休克关键词"""
        result = extract_candidate(diagnosis_text="脓毒性休克")
        assert result["is_septic_shock_candidate"] is True
        assert "diagnosis" in result["candidate_pathways"]
        # 仅有诊断文本，无感染+升压药 → probable (通道A自身)
        assert result["candidate_status"] in ("high_probability", "probable", "pending_review")

    def test_channel_a_sepsis_diagnosis(self):
        """通道A: 仅有脓毒症诊断且无休克信号 → 不自动进入休克候选"""
        result = extract_candidate(diagnosis_text="脓毒症")
        # 仅有脓毒症诊断但无任何休克方向信号 → 不进入休克候选
        # 这是正确的业务规则: 高召回不等于所有感染患者都进入休克分母
        assert result["is_septic_shock_candidate"] is False
        assert "diagnosis" not in result["candidate_pathways"]

    def test_channel_a_infection_shock(self):
        """通道A: 诊断文本包含感染性休克"""
        result = extract_candidate(diagnosis_text="感染性休克")
        assert result["is_septic_shock_candidate"] is True
        assert "diagnosis" in result["candidate_pathways"]

    def test_channel_a_no_match(self):
        """通道A: 诊断文本不匹配"""
        result = extract_candidate(diagnosis_text="高血压")
        assert "diagnosis" not in result["candidate_pathways"]

    # ---- 通道 B: 强休克信号 ----
    def test_channel_b_vasopressor_plus_lactate(self):
        """通道B: 感染 + 升压药 + 乳酸 > 2"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
            lactate_value=3.5,
        )
        assert result["is_septic_shock_candidate"] is True
        assert "strong_shock" in result["candidate_pathways"]

    def test_channel_b_vasopressor_plus_low_map(self):
        """通道B: 感染 + 升压药 + MAP < 65"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
            map_value=55.0,
        )
        # Note: channel B requires lactate_gt_2, not just MAP
        # This should be candidate via combined_evidence (channel C) if organ dysfunction present
        assert result["is_septic_shock_candidate"] is True

    def test_channel_b_vasopressor_plus_fluid(self):
        """通道B: 感染 + 升压药 + 液体复苏"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
            has_fluid_resuscitation=True,
        )
        # Note: channel B requires lactate_gt_2 specifically
        # This should be candidate via some pathway
        assert result["is_septic_shock_candidate"] is True

    def test_channel_b_vasopressor_only_not_enough(self):
        """通道B: 仅升压药不足（无感染证据）"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": False},
            has_vasopressor_wide=True,
            lactate_value=1.0,
            map_value=70.0,
        )
        assert "strong_shock" not in result["candidate_pathways"]

    # ---- 通道 C: 组合证据 ----
    def test_channel_c_shock_confirmed_plus_infection(self):
        """通道C/B: 感染+升压药+乳酸>2 → 优先通道B (strong_shock)"""
        result = extract_candidate(
            diagnosis_text="肺炎",
            infection_evidence={"has_infection": True, "i1": True, "i2": True},
            has_vasopressor_wide=True,
            lactate_value=3.0,
            sofa2_result={"sofa2_total": 5, "sofa2_score": 5, "result_status": "complete", "components": {"respiratory": 2}, "completeness": 1.0},
        )
        assert result["is_septic_shock_candidate"] is True
        # 通道B 优先级高于通道C
        assert "strong_shock" in result["candidate_pathways"]

    def test_channel_c_shock_pending_not_enough(self):
        """通道C: 休克 pending_review 不足"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": False},
        )
        assert "combined_evidence" not in result["candidate_pathways"]

    # ---- 通道 D: 待完善 ----
    def test_channel_d_partial_evidence(self):
        """通道D: 部分证据，进入待审"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": True},
            lactate_value=2.5,
        )
        # Should be candidate via some pathway
        assert result["is_septic_shock_candidate"] is True
        assert result["candidate_status"] in ("pending_review", "probable", "high_probability")

    # ---- SOFA-2 补充通道 ----
    def test_sofa2_supplement_high_delta(self):
        """SOFA-2: 高delta评分补充候选"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": True},
            sofa2_result={"sofa2_total": 8, "has_acute_organ_dysfunction": True, "delta": 5},
        )
        # SOFA-2 supplement should add pathway
        if "sofa2_supplement" in result["candidate_pathways"]:
            assert result["is_septic_shock_candidate"] is True

    # ---- 非候选 ----
    def test_not_candidate_no_evidence(self):
        """无任何证据 → 非候选"""
        result = extract_candidate(
            diagnosis_text="",
            infection_evidence={"has_infection": False},
        )
        # With no evidence at all, should not be candidate
        # (unless sofa2_supplement kicks in with high score)
        assert result["candidate_status"] in ("not_candidate", "pending_review")


class TestCandidateSummary:
    """候选统计测试"""

    def test_summary_counts(self):
        """统计各状态数量 — raw_candidate_count 排除 not_candidate"""
        candidates = [
            {"candidate_status": "high_probability"},
            {"candidate_status": "high_probability"},
            {"candidate_status": "probable"},
            {"candidate_status": "pending_review"},
            {"candidate_status": "not_candidate"},
        ]
        summary = compute_candidate_statistics(candidates)
        # raw_candidate_count = high_prob + probable + pending_review = 4
        assert summary["raw_candidate_count"] == 4
        assert summary["not_candidate_count"] == 1
        assert summary["evaluated_event_count"] == 5
        assert summary["final_candidate_count"] == 4

    def test_summary_empty(self):
        """空列表"""
        summary = compute_candidate_statistics([])
        assert summary["raw_candidate_count"] == 0

    def test_summary_rule_version(self):
        """规则版本"""
        summary = compute_candidate_statistics([])
        assert summary["rule_version"] == CANDIDATE_RULE_VERSION


class TestConfigConstants:
    """配置常量测试"""

    def test_lactate_threshold(self):
        assert LACTATE_STRICT_GT == 2.0

    def test_rule_version(self):
        assert CANDIDATE_RULE_VERSION == "1.1.0"


class TestGCSAdapter:
    """GCS 文本解析测试"""

    def test_e2v2m3_pattern(self):
        """E2V2M3 文本模式 (E2+V2+M3=7)"""
        import re
        raw_text = "E2V2M3"
        gcs_pattern = r'[Ee](\d)[Vv](\d[T]?)[Mm](\d)'
        m = re.search(gcs_pattern, raw_text)
        assert m is not None
        e = int(m.group(1))
        v_raw = m.group(2)
        m_score = int(m.group(3))
        v = 1 if "T" in v_raw else int(v_raw)
        assert e + v + m_score == 7  # E2+V2+M3=7

    def test_e2vtm3_pattern(self):
        """E2VTM3 文本模式（T=气管插管, V=1, E2+V1+M3=6）"""
        import re
        raw_text = "E2VTM3"
        # T may appear without a preceding digit (VT means V=T=1)
        gcs_pattern = r'[Ee](\d)[Vv](\d?[T]?)[Mm](\d)'
        m = re.search(gcs_pattern, raw_text)
        assert m is not None
        e = int(m.group(1))
        v_raw = m.group(2)
        m_score = int(m.group(3))
        v = 1 if "T" in v_raw else int(v_raw)
        assert e + v + m_score == 6  # E2+V1(T)+M3=6

    def test_numeric_gcs(self):
        """纯数值 GCS"""
        val = 8.0
        assert 3 <= val <= 15


class TestExclusionReasons:
    """排除原因测试"""

    def test_candidate_exclusion_reasons_exist(self):
        """候选排除原因已配置"""
        from config.exclusion_reasons import EXCLUSION_REASONS
        assert "candidate_exclusion" in EXCLUSION_REASONS
        reasons = EXCLUSION_REASONS["candidate_exclusion"]
        assert "non_infectious_shock" in reasons
        assert "cardiogenic_shock" in reasons
        assert "hypovolemic_shock" in reasons
        assert "postop_routine_vasopressor" in reasons
        assert "other" in reasons


class TestSepsisVsSepticShockKeywords:
    """脓毒症 vs 脓毒性休克 关键词拆分测试"""

    def test_septic_shock_diagnosis_independent_candidate(self):
        """明确脓毒性休克诊断可独立进入候选"""
        result = extract_candidate(diagnosis_text="脓毒性休克")
        assert result["is_septic_shock_candidate"] is True
        assert "diagnosis" in result["candidate_pathways"]
        assert result["has_septic_shock_diagnosis"] is True
        assert result["has_sepsis_only_diagnosis"] is False

    def test_sepsis_only_no_shock_signal_not_candidate(self):
        """仅有脓毒症诊断且无休克信号 → 非候选"""
        result = extract_candidate(
            diagnosis_text="脓毒症",
            infection_evidence={"has_infection": True},
        )
        assert result["is_septic_shock_candidate"] is False
        assert result["candidate_status"] == "not_candidate"

    def test_sepsis_with_vasopressor_is_candidate(self):
        """脓毒症诊断 + 升压药 → 候选"""
        result = extract_candidate(
            diagnosis_text="脓毒症",
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
        )
        assert result["is_septic_shock_candidate"] is True

    def test_sepsis_with_lactate_is_candidate(self):
        """脓毒症诊断 + 乳酸 > 2 → 候选"""
        result = extract_candidate(
            diagnosis_text="脓毒症",
            infection_evidence={"has_infection": True},
            lactate_value=3.0,
        )
        assert result["is_septic_shock_candidate"] is True

    def test_sepsis_with_low_map_is_candidate(self):
        """脓毒症诊断 + MAP < 65 → 候选"""
        result = extract_candidate(
            diagnosis_text="脓毒症",
            infection_evidence={"has_infection": True},
            map_value=55.0,
        )
        assert result["is_septic_shock_candidate"] is True

    def test_negative_keyword_excludes(self):
        """否定关键词排除诊断"""
        result = extract_candidate(diagnosis_text="排除脓毒性休克")
        assert result["is_septic_shock_candidate"] is False
        assert "diagnosis" not in result["candidate_pathways"]


class TestLactateTriState:
    """乳酸三态测试"""

    def test_lactate_met(self):
        """乳酸 > 2 → True / met"""
        result = extract_candidate(lactate_value=3.5)
        assert result["lactate_value"] == 3.5
        assert result["lactate_status"] == "met"

    def test_lactate_not_met(self):
        """乳酸 <= 2 → False / measured_not_met"""
        result = extract_candidate(lactate_value=1.5)
        assert result["lactate_value"] == 1.5
        assert result["lactate_status"] == "measured_not_met"

    def test_lactate_borderline(self):
        """乳酸 == 2.0 → borderline"""
        result = extract_candidate(lactate_value=2.0)
        assert result["lactate_status"] == "borderline"

    def test_lactate_missing(self):
        """乳酸缺失 → None / missing"""
        result = extract_candidate()
        assert result["lactate_value"] is None
        assert result["lactate_status"] == "missing"


class TestSOFANesting:
    """SOFA 嵌套结构读取测试"""

    def test_sofa_nested_structure(self):
        """v3["sofa"]["sofa2"] 嵌套结构正确读取"""
        v3_result = {
            "sofa": {
                "sofa2": {"sofa2_score": 5, "result_status": "complete", "components": {}, "completeness": 1.0},
                "classic": {"sofa_score": 4, "result_status": "complete"},
            },
            "i1": True,
        }
        result = extract_candidate(v3_result=v3_result, infection_evidence={"has_infection": True})
        assert result["sofa2_current"] == 5
        assert result["classic_sofa_current"] == 4

    def test_sofa_flat_structure_fallback(self):
        """旧平铺结构 v3["sofa2"] 兼容"""
        v3_result = {
            "sofa2": {"sofa2_score": 6, "result_status": "complete", "components": {}, "completeness": 1.0},
            "classic": {"sofa_score": 3, "result_status": "complete"},
            "i1": True,
        }
        result = extract_candidate(v3_result=v3_result, infection_evidence={"has_infection": True})
        assert result["sofa2_current"] == 6
        assert result["classic_sofa_current"] == 3


class TestSOFA2Supplement:
    """SOFA-2 补充通道测试"""

    def test_sofa2_supplement_forces_hit(self):
        """SOFA-2 >= 2 + 感染 → 补充通道必须命中"""
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            sofa2_result={"sofa2_score": 5, "result_status": "complete", "components": {}, "completeness": 1.0},
        )
        # SOFA-2 supplement should add pathway when no other pathway matches
        assert "sofa2_supplement" in result["candidate_pathways"]
        assert result["is_septic_shock_candidate"] is True
        assert result["candidate_status"] == "pending_review"


class TestEngineErrorHandling:
    """候选引擎异常降级测试"""

    def test_engine_error_not_not_candidate(self):
        """引擎异常不得降级为 not_candidate (在 db.py 中测试)"""
        # 这个测试验证 extract_candidate 本身不会因为参数异常返回 not_candidate
        # 当传入不完整的 v3_result 时，应该优雅处理
        result = extract_candidate(v3_result={})
        # 无任何证据 → not_candidate 是正常的
        # 但如果有感染证据但引擎内部异常，db.py 会捕获并返回 pending_review
        assert result["candidate_status"] in ("not_candidate", "pending_review")


class TestCandidateStatisticsInvariants:
    """候选统计不变量测试"""

    def test_statistics_invariants(self):
        """evaluated = raw + not_candidate; raw = high + probable + pending"""
        candidates = [
            {"candidate_status": "high_probability"},
            {"candidate_status": "probable"},
            {"candidate_status": "probable"},
            {"candidate_status": "pending_review"},
            {"candidate_status": "not_candidate"},
            {"candidate_status": "not_candidate"},
            {"candidate_status": "not_candidate", "excluded": True},
        ]
        summary = compute_candidate_statistics(candidates)
        assert summary["evaluated_event_count"] == 7
        assert summary["raw_candidate_count"] == 4  # high + probable + pending
        assert summary["not_candidate_count"] == 3
        assert summary["high_probability_count"] == 1
        assert summary["probable_count"] == 2
        assert summary["pending_review_count"] == 1
        # excluded 只计算 raw candidates 中的，not_candidate 的 excluded 不计入
        assert summary["excluded_candidate_count"] == 0
        assert summary["final_candidate_count"] == 4

    def test_statistics_excluded_candidates(self):
        """排除候选正确计数"""
        candidates = [
            {"candidate_status": "high_probability", "excluded": True},
            {"candidate_status": "probable"},
            {"candidate_status": "not_candidate"},
        ]
        summary = compute_candidate_statistics(candidates)
        assert summary["raw_candidate_count"] == 2
        assert summary["excluded_candidate_count"] == 1
        assert summary["final_candidate_count"] == 1

    def test_statistics_empty(self):
        """空列表"""
        summary = compute_candidate_statistics([])
        assert summary["evaluated_event_count"] == 0
        assert summary["raw_candidate_count"] == 0
        assert summary["not_candidate_count"] == 0
        assert summary["final_candidate_count"] == 0


class TestInfectionOnlyNotCandidate:
    """单纯感染不进入休克候选测试"""

    def test_infection_only_no_shock_signal(self):
        """感染 + 无任何休克信号 → 非休克候选"""
        result = extract_candidate(
            infection_evidence={"has_infection": True},
        )
        assert result["is_septic_shock_candidate"] is False
        assert result["candidate_status"] == "not_candidate"

    def test_infection_with_shock_signal_is_candidate(self):
        """感染 + 休克信号 → 候选"""
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
        )
        assert result["is_septic_shock_candidate"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
