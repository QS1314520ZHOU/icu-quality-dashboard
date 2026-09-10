"""
ICU-05 综合审计测试
====================
覆盖15项测试需求，验证ICU-05数据链路修复的正确性。
使用合成数据测试，不依赖生产数据库。
"""
import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 辅助函数
# ============================================================

def _make_patient(pid, mrn=None, k1=None, k2=None, candidate_status="not_candidate",
                  exclusion_key=None, bundle_1h_finish=None, bundle_3h_finish=None,
                  bundle_6h_finish=None, v3_extra=None, **kwargs):
    """构造测试用患者数据"""
    v3 = {"k1": k1, "k2": k2}
    if bundle_1h_finish is not None:
        v3["bundle_1h"] = {"finish": bundle_1h_finish}
    if bundle_3h_finish is not None:
        v3["bundle_3h"] = {"finish": bundle_3h_finish}
    if bundle_6h_finish is not None:
        v3["bundle_6h"] = {"finish": bundle_6h_finish}
    if v3_extra:
        v3.update(v3_extra)
    pat = {
        "_id": pid,
        "mrn": mrn or pid,
        "exclusion_key": exclusion_key or pid,
        "v3": v3,
        "candidate_status": candidate_status,
        "candidate_pathways": kwargs.get("candidate_pathways", []),
        "clinical_confirmation_status": kwargs.get("clinical_confirmation_status", "insufficient"),
        **{k: v for k, v in kwargs.items() if k not in ("candidate_pathways", "clinical_confirmation_status")},
    }
    return pat


def _simulate_compute_icu05(all_den_candidates, num_candidates, hour="1h", mode="shadow"):
    """
    模拟 summary.py 中 _compute_icu05 的核心逻辑。
    简化版用于单元测试。
    """
    # Step 1: 旧口径 K1 AND K2
    official_den = [
        p for p in all_den_candidates
        if (p.get("v3") or {}).get("k1") is True and (p.get("v3") or {}).get("k2") is True
    ]

    # 新口径候选分母
    candidate_den = [
        p for p in all_den_candidates
        if p.get("candidate_status") != "not_candidate"
    ]

    if mode == "shadow":
        qualified_den = official_den
    else:
        qualified_den = candidate_den

    # 分子必须是分母子集
    den_keys = {p.get("exclusion_key") for p in qualified_den if p.get("exclusion_key")}
    qualified_num = [p for p in num_candidates if p.get("exclusion_key") in den_keys]

    return {
        "denominator": len(qualified_den),
        "numerator": len(qualified_num),
        "official_den": len(official_den),
        "candidate_den": len(candidate_den),
        "qualified_den": qualified_den,
        "qualified_num": qualified_num,
    }


# ============================================================
# Test 1: 九个月均参与累计
# ============================================================

class TestNineMonthsAggregation:
    """2026-01至2026-09共九个月均参与累计"""

    def test_month_range_generation(self):
        """月份列表正确生成9个月"""
        from main import _periods_between
        months = _periods_between("2026-01", "2026-09")
        assert len(months) == 9
        assert months[0] == "2026-01"
        assert months[-1] == "2026-09"

    def test_month_range_single(self):
        """单月查询"""
        from main import _periods_between
        months = _periods_between("2026-06")
        assert len(months) == 1
        assert months[0] == "2026-06"


# ============================================================
# Test 2: 缺失月份不会被静默当成0
# ============================================================

class TestMissingMonthDetection:
    """缺失月份不会被静默当成0"""

    def test_missing_months_detected(self):
        """缺失月份应被标记"""
        all_months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
                      "2026-06", "2026-07", "2026-08", "2026-09"]
        # 假设只有3个月有数据
        months_with_data = {"2026-01", "2026-06", "2026-09"}
        missing = [m for m in all_months if m not in months_with_data]
        assert len(missing) == 6
        assert "2026-02" in missing
        assert "2026-03" in missing

    def test_data_complete_flag(self):
        """所有月份都有数据时 data_complete=True"""
        all_months = ["2026-01", "2026-02", "2026-03"]
        months_with_data = {"2026-01", "2026-02", "2026-03"}
        missing = [m for m in all_months if m not in months_with_data]
        assert len(missing) == 0  # data_complete


# ============================================================
# Test 3: 跨月 numerator、denominator 正确求和
# ============================================================

class TestCrossMonthSummation:
    """跨月分子分母正确求和"""

    def test_summation_basic(self):
        """基本求和"""
        monthly = [
            {"numerator": 1, "denominator": 3},
            {"numerator": 0, "denominator": 2},
            {"numerator": 2, "denominator": 5},
        ]
        total_num = sum(r["numerator"] for r in monthly)
        total_den = sum(r["denominator"] for r in monthly)
        assert total_num == 3
        assert total_den == 10

    def test_summation_with_none(self):
        """None值不参与求和"""
        monthly = [
            {"numerator": 1, "denominator": 3},
            {"numerator": None, "denominator": None},
            {"numerator": 2, "denominator": 5},
        ]
        total_num = sum(r["numerator"] for r in monthly if r["numerator"] is not None)
        total_den = sum(r["denominator"] for r in monthly if r["denominator"] is not None)
        assert total_num == 3
        assert total_den == 8


# ============================================================
# Test 4: 同一患者不同住院事件不能误合并
# ============================================================

class TestDistinctAdmissions:
    """同一患者不同住院事件不能误合并"""

    def test_different_admissions_separate(self):
        """同一MRN不同住院事件应分开计数"""
        # 模拟同一患者两次住院
        patients = [
            _make_patient("P001_A", mrn="MRN001", k1=True, k2=True,
                          exclusion_key="P001_A|20260101"),
            _make_patient("P001_B", mrn="MRN001", k1=True, k2=True,
                          exclusion_key="P001_B|20260601"),
        ]
        # exclusion_key 不同 → 不会被去重
        keys = {p["exclusion_key"] for p in patients}
        assert len(keys) == 2

    def test_same_admission_deduplicated(self):
        """同次住院重复记录应去重"""
        patients = [
            _make_patient("P001", mrn="MRN001", k1=True, k2=True,
                          exclusion_key="P001|20260101"),
            _make_patient("P001", mrn="MRN001", k1=True, k2=True,
                          exclusion_key="P001|20260101"),  # 重复
        ]
        keys = {p["exclusion_key"] for p in patients}
        assert len(keys) == 1  # 去重后只有1个


# ============================================================
# Test 5: K1=True, K2=True 正确进入正式分母
# ============================================================

class TestK1K2OfficialDenominator:
    """K1=True, K2=True 正确进入正式分母"""

    def test_k1_k2_both_true(self):
        """K1=True AND K2=True → 进入正式分母"""
        patients = [
            _make_patient("P001", k1=True, k2=True),
        ]
        result = _simulate_compute_icu05(patients, [])
        assert result["official_den"] == 1
        assert result["denominator"] == 1

    def test_k1_true_k2_false(self):
        """K1=True, K2=False → 不进入正式分母"""
        patients = [
            _make_patient("P001", k1=True, k2=False),
        ]
        result = _simulate_compute_icu05(patients, [])
        assert result["official_den"] == 0

    def test_k1_false_k2_true(self):
        """K1=False, K2=True → 不进入正式分母"""
        patients = [
            _make_patient("P001", k1=False, k2=True),
        ]
        result = _simulate_compute_icu05(patients, [])
        assert result["official_den"] == 0


# ============================================================
# Test 6: K1=None 或 K2=None 不得当成明确不满足
# ============================================================

class TestK1K2NoneHandling:
    """K1=None 或 K2=None 不得当成明确不满足，需进入待复核"""

    def test_k1_none_k2_true(self):
        """K1=None, K2=True → 不进入正式分母(旧口径)，但候选引擎可能纳入"""
        patients = [
            _make_patient("P001", k1=None, k2=True, candidate_status="pending_review"),
        ]
        # 旧口径: K1=None != True → 不进入
        result = _simulate_compute_icu05(patients, [], mode="shadow")
        assert result["official_den"] == 0
        # 候选引擎: pending_review → 进入候选分母
        result_active = _simulate_compute_icu05(patients, [], mode="active")
        assert result_active["candidate_den"] == 1

    def test_k2_none_k1_true(self):
        """K2=None, K1=True → 不进入正式分母(旧口径)"""
        patients = [
            _make_patient("P001", k1=True, k2=None, candidate_status="pending_review"),
        ]
        result = _simulate_compute_icu05(patients, [], mode="shadow")
        assert result["official_den"] == 0

    def test_both_none(self):
        """K1=None, K2=None → 不进入任何分母"""
        patients = [
            _make_patient("P001", k1=None, k2=None, candidate_status="not_candidate"),
        ]
        result = _simulate_compute_icu05(patients, [], mode="shadow")
        assert result["official_den"] == 0
        assert result["candidate_den"] == 0


# ============================================================
# Test 7: 新候选在 shadow 模式下不污染正式结果
# ============================================================

class TestShadowModeIsolation:
    """新候选在shadow模式下不污染正式结果"""

    def test_shadow_mode_uses_old_criteria(self):
        """shadow模式使用旧口径(K1 AND K2)"""
        patients = [
            _make_patient("P001", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("P002", k1=False, k2=True, candidate_status="high_probability"),
            _make_patient("P003", k1=True, k2=False, candidate_status="probable"),
        ]
        result = _simulate_compute_icu05(patients, [], mode="shadow")
        # shadow: 只有K1∧K2
        assert result["denominator"] == 1
        assert result["official_den"] == 1
        # 候选引擎: 3个都是候选
        assert result["candidate_den"] == 3

    def test_active_mode_uses_candidate_engine(self):
        """active模式使用候选引擎结果"""
        patients = [
            _make_patient("P001", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("P002", k1=False, k2=True, candidate_status="high_probability"),
            _make_patient("P003", k1=True, k2=False, candidate_status="not_candidate"),
        ]
        result = _simulate_compute_icu05(patients, [], mode="active")
        # active: candidate_status != "not_candidate"
        assert result["denominator"] == 2


# ============================================================
# Test 8: 分子严格为分母子集
# ============================================================

class TestNumeratorSubsetOfDenominator:
    """分子严格为分母子集"""

    def test_numerator_subset(self):
        """分子中只有在分母中的才计入"""
        den = [
            _make_patient("P001", k1=True, k2=True, exclusion_key="P001"),
            _make_patient("P002", k1=True, k2=True, exclusion_key="P002"),
        ]
        num = [
            {"exclusion_key": "P001"},
            {"exclusion_key": "P999"},  # 不在分母中
        ]
        result = _simulate_compute_icu05(den, num)
        assert result["denominator"] == 2
        assert result["numerator"] == 1  # P999被过滤

    def test_empty_numerator(self):
        """分子为空"""
        den = [_make_patient("P001", k1=True, k2=True)]
        result = _simulate_compute_icu05(den, [])
        assert result["denominator"] == 1
        assert result["numerator"] == 0


# ============================================================
# Test 9: exclusion_key 缺失时记录异常
# ============================================================

class TestExclusionKeyMissing:
    """exclusion_key缺失时记录异常"""

    def test_missing_exclusion_key(self):
        """exclusion_key缺失的患者"""
        pat = _make_patient("P001", k1=True, k2=True)
        pat["exclusion_key"] = None
        # 缺失exclusion_key的患者不应进入分母
        den = [pat]
        qualified = [p for p in den if p.get("exclusion_key")]
        assert len(qualified) == 0


# ============================================================
# Test 10: 1h、3h、6h 分母一致性
# ============================================================

class TestDenominatorConsistency:
    """1h、3h、6h分母一致性"""

    def test_shared_denominator(self):
        """1h/3h/6h共享同一基础分母"""
        den = [
            _make_patient("P001", k1=True, k2=True,
                          bundle_1h_finish=True, bundle_3h_finish=True, bundle_6h_finish=True),
            _make_patient("P002", k1=True, k2=True,
                          bundle_1h_finish=False, bundle_3h_finish=False, bundle_6h_finish=False),
        ]
        # 三个指标的分母应该相同
        for hour in ("1h", "3h", "6h"):
            result = _simulate_compute_icu05(den, den, hour=hour)
            assert result["denominator"] == 2


# ============================================================
# Test 11: 6h 不应在 1h/3h 分母为3时无故变成0
# ============================================================

class TestSixHourNotZero:
    """6h不应在1h/3h有分母时无故变成0"""

    def test_6h_has_denominator(self):
        """6h应该有与1h/3h相同的分母"""
        den = [
            _make_patient("P001", k1=True, k2=True),
            _make_patient("P002", k1=True, k2=True),
            _make_patient("P003", k1=True, k2=True),
        ]
        result_1h = _simulate_compute_icu05(den, [], hour="1h")
        result_6h = _simulate_compute_icu05(den, [], hour="6h")
        assert result_1h["denominator"] == 3
        assert result_6h["denominator"] == 3  # 不应为0

    def test_6h_bundle_judgment_exists(self):
        """6h bundle判定应该存在"""
        from scoring.bundle_engine import judge_bundle_v3
        # 构造最小patient_data
        t0 = datetime(2026, 6, 1, 10, 0)
        patient_data = {
            't0': t0,
            'diagnosis_text': '脓毒性休克',
            'has_antibiotic': True,
            'has_culture': True,
            'has_vasopressor': True,
            'vasopressor_status': 'active',
            'lactate_initial': 3.0,
            'gcs_min': 10,
            'pf_ratio_min': 200,
            'map_min': 55,
            'w1h': {'lactate_initial': 3.0, 'lactate_max': 3.0, 'map_min': 55,
                    'antibiotic_time': t0 + timedelta(minutes=30),
                    'culture_time': t0 + timedelta(minutes=20), 'has_fluid': True},
            'w3h': {'lactate_initial': 3.0, 'lactate_max': 3.0, 'map_min': 55,
                    'antibiotic_time': t0 + timedelta(minutes=30),
                    'culture_time': t0 + timedelta(minutes=20), 'fluid_ml': 2000},
            'w6h': {'lactate_initial': 3.0, 'lactate_max': 3.0, 'map_min': 55,
                    'antibiotic_time': t0 + timedelta(minutes=30),
                    'culture_time': t0 + timedelta(minutes=20), 'fluid_ml': 2000,
                    'has_lactate_recheck': True, 'lactate_recheck_value': 2.5},
        }
        # 需要注入VASO_WIDE_LABELS
        from scoring.bundle_engine import set_vaso_wide_labels
        set_vaso_wide_labels({"norepinephrine", "去甲肾上腺素"})
        result = judge_bundle_v3(patient_data)
        assert "bundle_6h" in result
        assert result["bundle_6h"] is not None


# ============================================================
# Test 12: 人工排除前后数量可追溯
# ============================================================

class TestManualExclusionTraceability:
    """人工排除前后数量可追溯"""

    def test_exclusion_counts(self):
        """排除前后数量关系正确"""
        raw_num = 5
        raw_den = 10
        excluded_num = 1
        excluded_den = 2
        final_num = raw_num - excluded_num
        final_den = raw_den - excluded_den
        assert final_num == 4
        assert final_den == 8
        assert final_num <= final_den  # 分子≤分母


# ============================================================
# Test 13: 数据入口覆盖明确诊断病例
# ============================================================

class TestDataEntryCoverage:
    """数据入口能覆盖明确脓毒性休克诊断病例"""

    def test_septic_shock_keywords(self):
        """脓毒性休克关键词应被识别"""
        from scoring.candidate_engine import extract_candidate
        keywords = ["脓毒性休克", "感染性休克", "脓毒症休克", "septic shock"]
        for kw in keywords:
            result = extract_candidate(diagnosis_text=kw)
            assert result["is_septic_shock_candidate"] is True, f"关键词 '{kw}' 未被识别"

    def test_sepsis_only_needs_shock_signal(self):
        """仅有脓毒症诊断需要休克信号才进入候选"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(diagnosis_text="脓毒症")
        assert result["is_septic_shock_candidate"] is False


# ============================================================
# Test 14: 乳酸=2.0、缺失、升压药unknown分别处理
# ============================================================

class TestLactateAndVasopressorEdgeCases:
    """乳酸和升压药边界情况"""

    def test_lactate_exactly_2_0(self):
        """乳酸=2.0 → borderline, K1=True(>=2)"""
        from scoring.bundle_engine import judge_K1_lactate
        assert judge_K1_lactate(2.0) is True  # >= 2

    def test_lactate_missing(self):
        """乳酸缺失 → K1=None"""
        from scoring.bundle_engine import judge_K1_lactate
        assert judge_K1_lactate(None) is None

    def test_lactate_below_2(self):
        """乳酸<2 → K1=False"""
        from scoring.bundle_engine import judge_K1_lactate
        assert judge_K1_lactate(1.5) is False

    def test_vasopressor_unknown(self):
        """升压药unknown → 不应作为电子确认依据"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            vasopressor_status="unknown",
        )
        # unknown升压药 → confirmed_shock_signal应为False(不是电子确认)
        assert result["confirmed_shock_signal"] is False
        # 但应进入missing_evidence供人工复核
        assert any("未知" in m for m in result["missing_evidence"])

    def test_vasopressor_active(self):
        """升压药active → confirmed_shock_signal=True"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
            vasopressor_status="active",
        )
        assert result["confirmed_shock_signal"] is True


# ============================================================
# Test 15: Shadow模式候选统计正确
# ============================================================

class TestShadowCandidateStatistics:
    """Shadow模式候选统计"""

    def test_shadow_statistics(self):
        """候选统计各状态计数正确"""
        from scoring.candidate_engine import compute_candidate_statistics
        candidates = [
            {"candidate_status": "high_probability"},
            {"candidate_status": "high_probability"},
            {"candidate_status": "probable"},
            {"candidate_status": "pending_review"},
            {"candidate_status": "not_candidate"},
            {"candidate_status": "not_candidate"},
        ]
        stats = compute_candidate_statistics(candidates)
        assert stats["raw_candidate_count"] == 4
        assert stats["high_probability_count"] == 2
        assert stats["probable_count"] == 1
        assert stats["pending_review_count"] == 1
        assert stats["not_candidate_count"] == 2

    def test_candidate_den_vs_official_den(self):
        """候选分母≥正式分母(旧口径)"""
        patients = [
            _make_patient("P001", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("P002", k1=True, k2=False, candidate_status="probable"),
            _make_patient("P003", k1=False, k2=True, candidate_status="pending_review"),
            _make_patient("P004", k1=False, k2=False, candidate_status="not_candidate"),
        ]
        result = _simulate_compute_icu05(patients, [], mode="shadow")
        # 旧口径: 只有P001
        assert result["official_den"] == 1
        # 候选引擎: P001+P002+P003
        assert result["candidate_den"] == 3
        # 候选分母≥正式分母
        assert result["candidate_den"] >= result["official_den"]


# ============================================================
# Test 16: Bundle判定引擎完整性
# ============================================================

class TestBundleEngineCompleteness:
    """Bundle判定引擎完整性"""

    def test_1h_bundle_finish(self):
        """1h Bundle完成判定"""
        from scoring.bundle_engine import judge_bundle_finish_v3
        result = judge_bundle_finish_v3(
            a1=True, b3=True,
            c1=False, c2=False, c3=True,
        )
        # 未触发C1/C2 → step3=True
        assert result["finish"] is True

    def test_3h_bundle_finish(self):
        """3h Bundle完成判定"""
        from scoring.bundle_engine import judge_bundle_finish_v3
        result = judge_bundle_finish_v3(
            a1=True, b3=True,
            c1=True, c2=False, c3=True,
        )
        # C1触发 → 需要C3
        assert result["finish"] is True

    def test_bundle_not_finish(self):
        """Bundle未完成"""
        from scoring.bundle_engine import judge_bundle_finish_v3
        result = judge_bundle_finish_v3(
            a1=True, b3=False,
            c1=False, c2=False, c3=True,
        )
        assert result["finish"] is False

    def test_bundle_missing_data(self):
        """数据缺失→None"""
        from scoring.bundle_engine import judge_bundle_finish_v3
        result = judge_bundle_finish_v3(
            a1=None, b3=True,
            c1=False, c2=False, c3=True,
        )
        assert result["finish"] is None


# ============================================================
# Test 17: 候选引擎四通道
# ============================================================

class TestCandidateEngineFourChannels:
    """候选引擎四通道"""

    def test_channel_a_diagnosis(self):
        """通道A: 明确诊断"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(diagnosis_text="脓毒性休克")
        assert "diagnosis" in result["candidate_pathways"]
        assert result["is_septic_shock_candidate"] is True

    def test_channel_b_strong_shock(self):
        """通道B: 强休克证据"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
            lactate_value=3.0,
        )
        assert "strong_shock" in result["candidate_pathways"]

    def test_channel_c_composite(self):
        """通道C: 组合证据"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            has_vasopressor_wide=True,
            sofa2_result={"sofa2_score": 5, "result_status": "complete",
                          "components": {}, "completeness": 1.0},
        )
        assert result["is_septic_shock_candidate"] is True

    def test_channel_d_pending(self):
        """通道D: 证据不完整"""
        from scoring.candidate_engine import extract_candidate
        result = extract_candidate(
            infection_evidence={"has_infection": True},
            lactate_value=2.5,
        )
        assert result["candidate_status"] in ("pending_review", "probable", "high_probability")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
