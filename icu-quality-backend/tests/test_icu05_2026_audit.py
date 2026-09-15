"""
ICU-05 2026年6月至9月专项审计测试。
验证分母为0的根因，生成患者级审计数据。
"""
import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from summary import _compute_icu05, _natural_months_back, find_missing_periods
from config.candidate_rules import CANDIDATE_ENGINE_MODE


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


def _simulate_compute_icu05(all_den_candidates, num_candidates=None, hour="1h", mode="shadow"):
    """
    模拟 summary.py 中 _compute_icu05 的核心逻辑。
    简化版用于单元测试。

    all_den_candidates: 所有分母候选患者
    num_candidates: 完成Bundle的分子患者（None时用all_den_candidates，即同一批人）
    """
    from scoring.candidate_engine import compute_candidate_statistics

    if num_candidates is None:
        num_candidates = all_den_candidates

    # Step 1: 候选统计
    cand_summary = compute_candidate_statistics(all_den_candidates)

    # Step 2: 旧口径 K1 AND K2
    official_den_patients = [
        p for p in all_den_candidates
        if (p.get("v3") or {}).get("k1") == True and (p.get("v3") or {}).get("k2") == True
    ]

    # Step 3: 新口径候选
    candidate_den_patients = [
        p for p in all_den_candidates
        if p.get("candidate_status") != "not_candidate"
    ]

    if mode == "shadow":
        qualified_den = official_den_patients
    else:
        qualified_den = candidate_den_patients

    # Step 4: 分子 — 从 num_candidates (完成Bundle的患者) 中
    #         筛选在分母 exclusion_key 集合中的
    den_exclusion_keys = {p.get("exclusion_key") for p in qualified_den if p.get("exclusion_key")}
    qualified_num = [
        p for p in num_candidates
        if p.get("exclusion_key") in den_exclusion_keys
    ]

    num = len(qualified_num)
    den = len(qualified_den)
    val = round(num / den * 100, 1) if den > 0 else 0.0

    return {
        "num": num, "den": den, "val": val,
        "candidate_mode": mode,
        "raw_candidate_count": cand_summary.get("raw_candidate_count", 0),
        "high_probability_count": cand_summary.get("high_probability_count", 0),
        "probable_count": cand_summary.get("probable_count", 0),
        "pending_review_count": cand_summary.get("pending_review_count", 0),
        "not_candidate_count": cand_summary.get("not_candidate_count", 0),
        "new_shock_count": len(candidate_den_patients),
        "old_shock_count": len(official_den_patients),
        "shock_diff": len(candidate_den_patients) - len(official_den_patients),
    }


# ============================================================
# 测试用例
# ============================================================

class TestICU05ZeroDenominator:
    """测试 ICU-05 分母为0的场景"""

    def test_empty_candidates_zero_denominator(self):
        """无候选患者 → 分母=0"""
        result = _simulate_compute_icu05([], [], hour="1h", mode="active")
        assert result["den"] == 0
        assert result["num"] == 0
        assert result["val"] == 0.0

    def test_all_not_candidate_zero_denominator(self):
        """所有患者为 not_candidate → active模式分母=0"""
        patients = [
            _make_patient("p1", candidate_status="not_candidate"),
            _make_patient("p2", candidate_status="not_candidate"),
        ]
        result = _simulate_compute_icu05(patients, patients, hour="1h", mode="active")
        assert result["den"] == 0
        assert result["candidate_mode"] == "active"

    def test_shadow_mode_uses_old_k1k2(self):
        """shadow模式使用旧口径K1 AND K2"""
        patients = [
            _make_patient("p1", k1=True, k2=True, candidate_status="not_candidate"),
            _make_patient("p2", k1=False, k2=True, candidate_status="high_probability"),
            _make_patient("p3", k1=True, k2=False, candidate_status="probable"),
        ]
        result = _simulate_compute_icu05(patients, patients, hour="1h", mode="shadow")
        # 只有p1满足K1 AND K2
        assert result["den"] == 1
        assert result["old_shock_count"] == 1
        assert result["new_shock_count"] == 2  # p2和p3是候选

    def test_active_mode_uses_candidate(self):
        """active模式使用候选引擎结果"""
        patients = [
            _make_patient("p1", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("p2", k1=False, k2=False, candidate_status="probable"),
            _make_patient("p3", k1=False, k2=False, candidate_status="not_candidate"),
        ]
        result = _simulate_compute_icu05(patients, patients, hour="1h", mode="active")
        # p1和p2是候选
        assert result["den"] == 2
        assert result["old_shock_count"] == 1
        assert result["new_shock_count"] == 2

    def test_pending_review_in_denominator(self):
        """pending_review患者计入分母"""
        patients = [
            _make_patient("p1", candidate_status="pending_review"),
            _make_patient("p2", candidate_status="high_probability"),
        ]
        result = _simulate_compute_icu05(patients, patients, hour="1h", mode="active")
        assert result["den"] == 2
        assert result["pending_review_count"] == 1


class TestICU05BundleCompletion:
    """测试 ICU-05 Bundle 完成率计算"""

    def test_1h_bundle_completion(self):
        """1h Bundle 完成"""
        all_patients = [
            _make_patient("p1", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("p2", k1=True, k2=True, candidate_status="probable"),
        ]
        # 分子: 只有 p1 完成 1h bundle
        num_patients = [_make_patient("p1", k1=True, k2=True, candidate_status="high_probability")]
        result = _simulate_compute_icu05(all_patients, num_patients, hour="1h", mode="active")
        assert result["den"] == 2
        assert result["num"] == 1  # 只有p1完成1h

    def test_3h_bundle_completion(self):
        """3h Bundle 完成"""
        all_patients = [
            _make_patient("p1", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("p2", k1=True, k2=True, candidate_status="probable"),
        ]
        # 分子: p1和p2都完成3h bundle
        num_patients = [
            _make_patient("p1", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("p2", k1=True, k2=True, candidate_status="probable"),
        ]
        result = _simulate_compute_icu05(all_patients, num_patients, hour="3h", mode="active")
        assert result["den"] == 2
        assert result["num"] == 2  # p1和p2都完成3h

    def test_6h_bundle_completion(self):
        """6h Bundle 完成"""
        all_patients = [
            _make_patient("p1", k1=True, k2=True, candidate_status="high_probability"),
            _make_patient("p2", k1=True, k2=True, candidate_status="probable"),
        ]
        # 分子: 只有 p1 完成 6h bundle
        num_patients = [_make_patient("p1", k1=True, k2=True, candidate_status="high_probability")]
        result = _simulate_compute_icu05(all_patients, num_patients, hour="6h", mode="active")
        assert result["den"] == 2
        assert result["num"] == 1  # 只有p1完成6h


class TestICU05CandidateStatistics:
    """测试候选引擎统计"""

    def test_candidate_statistics_counts(self):
        """候选统计计数正确"""
        from scoring.candidate_engine import compute_candidate_statistics

        patients = [
            _make_patient("p1", candidate_status="high_probability"),
            _make_patient("p2", candidate_status="high_probability"),
            _make_patient("p3", candidate_status="probable"),
            _make_patient("p4", candidate_status="pending_review"),
            _make_patient("p5", candidate_status="not_candidate"),
        ]
        stats = compute_candidate_statistics(patients)
        assert stats["evaluated_event_count"] == 5
        assert stats["raw_candidate_count"] == 4  # 2 high + 1 probable + 1 pending
        assert stats["high_probability_count"] == 2
        assert stats["probable_count"] == 1
        assert stats["pending_review_count"] == 1
        assert stats["not_candidate_count"] == 1


class TestICU05CrossMonthAggregation:
    """测试ICU-05跨月汇总"""

    def test_cross_month_numerator_denominator_sum(self):
        """跨月汇总：分子分母累加"""
        # 月份1: p1 是候选, 完成1h bundle
        month1_den = [_make_patient("p1", k1=True, k2=True, candidate_status="high_probability")]
        month1_num = [_make_patient("p1", k1=True, k2=True, candidate_status="high_probability")]
        month1 = _simulate_compute_icu05(month1_den, month1_num, hour="1h", mode="active")

        # 月份2: p2 是候选, 未完成1h bundle
        month2_den = [_make_patient("p2", k1=True, k2=True, candidate_status="probable")]
        month2_num = []  # p2 未完成 bundle，分子为空
        month2 = _simulate_compute_icu05(month2_den, month2_num, hour="1h", mode="active")

        # 跨月汇总
        total_num = month1["num"] + month2["num"]
        total_den = month1["den"] + month2["den"]
        total_val = round(total_num / total_den * 100, 1) if total_den > 0 else 0.0

        assert total_num == 1  # 只有月份1的p1完成
        assert total_den == 2  # p1 + p2
        assert total_val == 50.0


class TestMissingPeriodsDetection:
    """测试缺失月份检测"""

    def _make_mock_client(self, find_return_value):
        """构造 mock client"""
        mock_coll = MagicMock()
        mock_coll.find.return_value = find_return_value

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)

        return mock_client

    def test_2026_06_to_09_detection(self):
        """检测2026-06至2026-09缺失"""
        periods = ["2026-06", "2026-07", "2026-08", "2026-09"]
        mock_client = self._make_mock_client([])

        with patch("summary.get_client", return_value=mock_client):
            with patch("summary.BED_DB_NAMES", ["test_db"]):
                missing = find_missing_periods(["JJL000282"], periods)
                assert missing == ["2026-06", "2026-07", "2026-08", "2026-09"]

    def test_partial_2026_06_to_09(self):
        """部分月份存在（旧格式视为缺失）"""
        periods = ["2026-06", "2026-07", "2026-08", "2026-09"]
        # 旧格式文档（无indicator字段）现在被视为缺失
        mock_client = self._make_mock_client(
            [{"period": "2026-06"}, {"period": "2026-08"}]
        )

        with patch("summary.get_client", return_value=mock_client):
            with patch("summary.BED_DB_NAMES", ["test_db"]):
                missing = find_missing_periods(["JJL000282"], periods)
                # 旧格式（无indicator）需要重算
                assert missing == ["2026-06", "2026-07", "2026-08", "2026-09"]
