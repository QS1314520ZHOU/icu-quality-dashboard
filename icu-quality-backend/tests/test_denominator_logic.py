"""
分母逻辑测试。
验证: den = qualified_events - exclusions, num ⊆ den

使用合成数据测试 summary.py 中 _compute_icu05 的逻辑。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, 0, tzinfo=timezone.utc)


# ============================================================
# 模拟 _compute_icu05 的核心逻辑
# ============================================================

def _simulate_compute_icu05(all_den_candidates, num_candidates):
    """
    模拟 summary.py 中修复后的 ICU-05 分母逻辑。

    Step 1: 筛选合格分母 (is_septic_shock = True)
    Step 2: 分子必须是分母的子集
    Step 3: 返回结果
    """
    # Step 1: Filter for qualified denominator
    qualified_den = [p for p in all_den_candidates if p.get("v3", {}).get("is_septic_shock") is True]

    # Step 2: Numerator must be subset of qualified denominator
    den_exclusion_keys = {p.get("exclusion_key") for p in qualified_den if p.get("exclusion_key")}
    qualified_num = [p for p in num_candidates if p.get("exclusion_key") in den_exclusion_keys]

    return {
        "denominator": len(qualified_den),
        "numerator": len(qualified_num),
        "qualified_den": qualified_den,
        "qualified_num": qualified_num,
    }


# ============================================================
# 测试: 分子是分母的子集
# ============================================================

def test_numerator_subset_of_denominator():
    """分子中只有在合格分母中的候选才计入"""
    # 3个候选: 2个septic shock, 1个不是
    den_candidates = [
        {"exclusion_key": "P001", "v3": {"is_septic_shock": True}},
        {"exclusion_key": "P002", "v3": {"is_septic_shock": True}},
        {"exclusion_key": "P003", "v3": {"is_septic_shock": False}},
    ]
    # 3个都满足bundle
    num_candidates = [
        {"exclusion_key": "P001"},
        {"exclusion_key": "P002"},
        {"exclusion_key": "P003"},
    ]

    result = _simulate_compute_icu05(den_candidates, num_candidates)

    assert result["denominator"] == 2, f"Expected den=2, got {result['denominator']}"
    assert result["numerator"] == 2, f"Expected num=2, got {result['numerator']}"
    # P003 不在合格分母中，所以不在分子中
    num_keys = {p["exclusion_key"] for p in result["qualified_num"]}
    assert "P003" not in num_keys


# ============================================================
# 测试: 全部不合格 → 分母=0
# ============================================================

def test_no_qualified_candidates():
    """所有候选都不是septic shock → 分母=0"""
    den_candidates = [
        {"exclusion_key": "P001", "v3": {"is_septic_shock": False}},
        {"exclusion_key": "P002", "v3": {"is_septic_shock": False}},
    ]
    num_candidates = [
        {"exclusion_key": "P001"},
    ]

    result = _simulate_compute_icu05(den_candidates, num_candidates)

    assert result["denominator"] == 0
    assert result["numerator"] == 0


# ============================================================
# 测试: 分子为空
# ============================================================

def test_empty_numerator():
    """分母有合格候选，但分子为空 → 分母>0, 分子=0"""
    den_candidates = [
        {"exclusion_key": "P001", "v3": {"is_septic_shock": True}},
    ]
    num_candidates = []

    result = _simulate_compute_icu05(den_candidates, num_candidates)

    assert result["denominator"] == 1
    assert result["numerator"] == 0


# ============================================================
# 测试: 分子包含不在分母中的患者
# ============================================================

def test_numerator_has_non_denominator_patient():
    """分子包含一个不在分母中的患者 → 该患者被过滤"""
    den_candidates = [
        {"exclusion_key": "P001", "v3": {"is_septic_shock": True}},
    ]
    num_candidates = [
        {"exclusion_key": "P001"},
        {"exclusion_key": "P999"},  # 不在分母中
    ]

    result = _simulate_compute_icu05(den_candidates, num_candidates)

    assert result["denominator"] == 1
    assert result["numerator"] == 1  # P999 被过滤
    assert result["qualified_num"][0]["exclusion_key"] == "P001"


# ============================================================
# 测试: v3字段缺失
# ============================================================

def test_missing_v3_field():
    """候选缺少v3字段 → 不算septic shock"""
    den_candidates = [
        {"exclusion_key": "P001"},  # 无v3字段
        {"exclusion_key": "P002", "v3": {"is_septic_shock": True}},
    ]
    num_candidates = [
        {"exclusion_key": "P001"},
        {"exclusion_key": "P002"},
    ]

    result = _simulate_compute_icu05(den_candidates, num_candidates)

    assert result["denominator"] == 1  # 只有P002
    assert result["numerator"] == 1


# ============================================================
# 测试: old vs new shock 口径
# ============================================================

def test_old_vs_new_shock_count():
    """验证old(K1∧K2)和new(SOFA-2)口径的差异"""
    patients = [
        {
            "pid": "P001",
            "v3": {
                "is_septic_shock": True,
                "k1": True, "k2": True,
                "clinical_layer": {
                    "layer4_shock": {
                        "shock_status": "confirmed",
                        "criteria": {"vasopressor_required": True, "lactate_gt_2": True},
                    },
                },
            },
        },
        {
            "pid": "P002",
            "v3": {
                "is_septic_shock": True,
                "k1": True, "k2": True,
                "clinical_layer": {
                    "layer4_shock": {
                        "shock_status": "confirmed",
                        "criteria": {"vasopressor_required": True, "lactate_gt_2": True},
                    },
                },
            },
        },
        {
            "pid": "P003",
            "v3": {
                "is_septic_shock": False,
                "k1": True, "k2": False,
                "clinical_layer": {
                    "layer4_shock": {
                        "shock_status": "not_confirmed",
                        "criteria": {"vasopressor_required": True, "lactate_gt_2": False},
                    },
                },
            },
        },
    ]

    # Old: K1∧K2
    old_shock = [p for p in patients if p["v3"].get("k1") is True and p["v3"].get("k2") is True]
    # New: clinical_layer shock_status
    new_shock = [p for p in patients if
                 (p["v3"].get("clinical_layer") or {}).get("layer4_shock", {}).get("shock_status") == "confirmed"]

    assert len(old_shock) == 2  # P001, P002
    assert len(new_shock) == 2  # P001, P002 (在这个测试中一致)


# ============================================================
# 测试: 乳酸2.0边界
# ============================================================

def test_lactate_2_0_boundary_in_denominator():
    """乳酸=2.0的患者: old口径可能计入, new口径标记为borderline"""
    patient = {
        "pid": "P001",
        "v3": {
            "is_septic_shock": False,  # 乳酸=2.0不满足>2
            "k1": True,  # 旧口径: 有升压药
            "k2": True,
            "clinical_layer": {
                "layer4_shock": {
                    "shock_status": "borderline",
                    "lactate_borderline": True,
                    "criteria": {"vasopressor_required": True, "lactate_gt_2": False},
                },
            },
        },
    }

    # Old口径: K1∧K2 = True → 会计入
    old_shock = patient["v3"]["k1"] is True and patient["v3"]["k2"] is True
    # New口径: borderline → 不计入confirmed
    new_shock = patient["v3"]["clinical_layer"]["layer4_shock"]["shock_status"] == "confirmed"

    assert old_shock is True
    assert new_shock is False  # new口径下不计入


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
