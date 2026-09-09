"""
SOFA 评分桥接层单元测试。
使用合成数据覆盖要求的边界场景。

覆盖场景:
1. 有感染但SOFA急性增加不足2
2. 有既存器官障碍但本次无急性增加
3. 肝脏/肾脏/凝血异常而S1-S4不明显
4. 使用升压药但不能确认感染性休克
5. 乳酸恰好2.0
6. 用药后MAP已恢复但仍依赖升压药
7. 候选存在但门控失败或资料不足
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

# 确保 VASO_WIDE_LABELS 已注入
import scoring.bundle_engine as engine
try:
    engine.set_vaso_wide_labels({"去甲肾上腺素", "norepinephrine", "肾上腺素", "epinephrine",
                                  "多巴胺", "dopamine", "多巴酚丁胺", "dobutamine"})
except RuntimeError:
    pass  # 已经注入

from scoring.sofa_bridge import compute_sofa_scores_from_data, build_clinical_layer


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, 0, tzinfo=timezone.utc)


# ============================================================
# 场景1: 有感染但SOFA急性增加不足2
# ============================================================

def test_infection_insufficient_sofa_increase():
    """诊断: 肺炎; 但SOFA-2总分 < 2 → is_sepsis = False"""
    eval_time = _utc(2026, 1, 15, 12)

    # 观测: 全部正常，SOFA-2总分应为0
    observations = [
        {"code": "param_bg_P/Fratio", "value_number": 400, "unit": "", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "PLT", "value_number": 200, "unit": "10^9/L", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "TBIL", "value_number": 0.8, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "gcsScore", "value_number": 15, "unit": "", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "CREA", "value_number": 1.0, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "MAP", "value_number": 85, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = []  # 无升压药

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    # SOFA-2 总分应为0（全部正常）
    assert sofa_result["sofa2"]["sofa2_score"] == 0, \
        f"Expected sofa2_score=0, got {sofa_result['sofa2']['sofa2_score']}"

    # 有感染但SOFA<2 → is_sepsis = False
    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": True, "i3": False},
    )
    assert clinical["layer3_sepsis"]["is_sepsis"] is False, \
        "Should not be sepsis when SOFA-2 < 2"


# ============================================================
# 场景2: 有既存器官障碍但本次无急性增加
# ============================================================

def test_preexisting_no_acute_increase():
    """既往CKD, 本次肌酐稳定在3.0mg/dL; SOFA-2 kidney=2 但无急性增加"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = [
        # 肌酐3.0 → SOFA-2 kidney=2（慢性稳定值）
        {"code": "CREA", "value_number": 3.0, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        # 其他正常
        {"code": "param_bg_P/Fratio", "value_number": 400, "unit": "", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "PLT", "value_number": 200, "unit": "10^9/L", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "TBIL", "value_number": 0.8, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "gcsScore", "value_number": 15, "unit": "", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "MAP", "value_number": 85, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = []

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    # SOFA-2 kidney 应为 2
    assert sofa_result["sofa2"]["components"]["kidney"] == 2, \
        f"Expected kidney=2, got {sofa_result['sofa2']['components']['kidney']}"

    # 总分 ≥ 2，有感染 → 当前口径下 is_sepsis = True
    # (注: 这是Sepsis-3的已知局限性，需要基线对比才能区分慢性vs急性)
    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": False, "i3": False},
    )
    # 当前实现: SOFA-2 ≥ 2 + 感染 = 脓毒症
    # 基线未知时，sepsis_basis 标记为 pending_baseline
    assert clinical["layer3_sepsis"]["sepsis_basis"] == "sepsis3_sofa2_pending_baseline"


# ============================================================
# 场景3: 肝脏异常但S1-S4不明显
# ============================================================

def test_liver_abnormal_no_s_signal():
    """TBIL=80umol/L → SOFA-2 liver=1; 但P/F>300, GCS>13, MAP>70, 无升压药"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = [
        # TBIL = 80 umol/L → ~4.68 mg/dL → SOFA-2 liver=2
        {"code": "TBIL", "value_number": 4.68, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        # 其他正常
        {"code": "param_bg_P/Fratio", "value_number": 400, "unit": "", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "PLT", "value_number": 200, "unit": "10^9/L", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "gcsScore", "value_number": 15, "unit": "", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "CREA", "value_number": 1.0, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "MAP", "value_number": 85, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = []

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    # liver 应为 2
    assert sofa_result["sofa2"]["components"]["liver"] == 2, \
        f"Expected liver=2, got {sofa_result['sofa2']['components']['liver']}"

    # 总分 ≥ 2 → 有感染时构成脓毒症
    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": False, "i3": False},
    )
    assert clinical["layer2_organ_dysfunction"]["has_acute_organ_dysfunction"] is True
    assert clinical["layer3_sepsis"]["is_sepsis"] is True

    # 但 S1-S4 辅助信号可能都不明显
    # S4 (has_vasopressor_wide) 应为 False
    assert clinical["layer2_organ_dysfunction"]["s4_signal"] is False


# ============================================================
# 场景4: 使用升压药但不能确认感染性休克
# ============================================================

def test_vasopressor_no_shock():
    """去甲肾上腺素使用中，但乳酸=1.5, 无感染证据 → shock_status != confirmed"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = [
        {"code": "param_bg_Lac", "value_number": 1.5, "unit": "mmol/L", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "MAP", "value_number": 60, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = [
        {"med_name": "去甲肾上腺素", "route": "静脉泵入", "dose_ugkgmin": 0.15, "admin_end": None},
    ]

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    # 无感染 → 不是脓毒性休克
    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": False, "i1": False, "i2": False, "i3": False},
        has_vasopressor_wide=True,
        lactate_value=1.5,
        map_value=60,
    )
    assert clinical["layer4_shock"]["shock_status"] == "not_confirmed", \
        f"Expected not_confirmed, got {clinical['layer4_shock']['shock_status']}"
    assert clinical["layer3_sepsis"]["is_sepsis"] is False


# ============================================================
# 场景5: 乳酸恰好2.0
# ============================================================

def test_lactate_borderline():
    """乳酸 = 2.0 → lactate_borderline = True, shock_status = borderline"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = [
        {"code": "param_bg_Lac", "value_number": 2.0, "unit": "mmol/L", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "CREA", "value_number": 1.0, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "MAP", "value_number": 60, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = [
        {"med_name": "去甲肾上腺素", "route": "静脉泵入", "dose_ugkgmin": 0.15, "admin_end": None},
    ]

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": False, "i3": False},
        has_vasopressor_wide=True,
        lactate_value=2.0,
        map_value=60,
    )
    assert clinical["layer4_shock"]["lactate_borderline"] is True, \
        "Lactate=2.0 should be marked as borderline"
    assert clinical["layer4_shock"]["shock_status"] == "borderline", \
        f"Expected borderline, got {clinical['layer4_shock']['shock_status']}"
    assert clinical["layer4_shock"]["criteria"]["lactate_gt_2"] is False


# ============================================================
# 场景6: MAP已恢复但仍依赖升压药
# ============================================================

def test_map_recovered_vasopressor_dependent():
    """MAP=75, 但仍在泵去甲肾上腺素 → map_recovered=True
    容量已评估时 confirmed; 容量未知时 pending_review"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = [
        {"code": "param_bg_Lac", "value_number": 3.5, "unit": "mmol/L", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "CREA", "value_number": 1.0, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "MAP", "value_number": 75, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = [
        {"med_name": "去甲肾上腺素", "route": "静脉泵入", "dose_ugkgmin": 0.15, "admin_end": None},
    ]

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    # Case 1: 容量未知 → pending_review (§13 修复)
    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": False, "i3": False},
        has_vasopressor_wide=True,
        lactate_value=3.5,
        map_value=75,
    )
    assert clinical["layer4_shock"]["map_recovered"] is True, \
        "MAP=75 with vasopressor should be map_recovered=True"
    assert clinical["layer4_shock"]["shock_status"] == "pending_review", \
        f"Expected pending_review (volume unknown), got {clinical['layer4_shock']['shock_status']}"

    # Case 2: 容量已评估 → confirmed
    clinical2 = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": False, "i3": False},
        has_vasopressor_wide=True,
        lactate_value=3.5,
        map_value=75,
        has_fluid_resuscitation=True,
    )
    assert clinical2["layer4_shock"]["shock_status"] == "confirmed", \
        f"Expected confirmed (volume assessed), got {clinical2['layer4_shock']['shock_status']}"


# ============================================================
# 场景7: 候选存在但门控失败或资料不足
# ============================================================

def test_candidate_gate_failure_insufficient_data():
    """无观测数据 → insufficient_data"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = []  # 无数据
    medications = []

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    assert sofa_result["sofa2"]["sofa2_score"] is None
    assert sofa_result["sofa2"]["result_status"] == "insufficient"

    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": None, "i1": None, "i2": None, "i3": None},
    )
    assert clinical["layer2_organ_dysfunction"]["has_acute_organ_dysfunction"] is None
    assert clinical["layer3_sepsis"]["is_sepsis"] is None
    assert clinical["layer4_shock"]["shock_status"] == "insufficient_data"


def test_candidate_gate_failure_no_infection():
    """有SOFA评分但无感染 → 不进分母"""
    eval_time = _utc(2026, 1, 15, 12)

    observations = [
        {"code": "CREA", "value_number": 3.0, "unit": "mg/dl", "observed_at": _utc(2026, 1, 15, 8)},
        {"code": "MAP", "value_number": 60, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = [
        {"med_name": "去甲肾上腺素", "route": "静脉泵入", "dose_ugkgmin": 0.2, "admin_end": None},
    ]

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": False, "i1": False, "i2": False, "i3": False},
        has_vasopressor_wide=True,
    )
    assert clinical["layer3_sepsis"]["is_sepsis"] is False
    assert clinical["layer4_shock"]["shock_status"] == "not_confirmed"


# ============================================================
# 场景8: S4 ≠ K2 验证
# ============================================================

def test_s4_k2_separation():
    """验证 S4 (has_vasopressor_wide) 和 K2 不再是同一个布尔值"""
    eval_time = _utc(2026, 1, 15, 12)

    # 有升压药但乳酸<2 → K1不成立
    observations = [
        {"code": "param_bg_Lac", "value_number": 1.0, "unit": "mmol/L", "observed_at": _utc(2026, 1, 15, 10)},
        {"code": "MAP", "value_number": 60, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = [
        {"med_name": "去甲肾上腺素", "route": "静脉泵入", "dose_ugkgmin": 0.15, "admin_end": None},
    ]

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    clinical = build_clinical_layer(
        sofa_result,
        infection_evidence={"has_infection": True, "i1": True, "i2": False, "i3": False},
        has_vasopressor_wide=True,
        lactate_value=1.0,
        map_value=60,
    )

    # S4 辅助信号 = True (有升压药)
    assert clinical["layer2_organ_dysfunction"]["s4_signal"] is True

    # 但 shock_status = not_confirmed (乳酸<2)
    assert clinical["layer4_shock"]["shock_status"] == "not_confirmed"

    # clinical_layer 中的 criteria 明确区分了 vasopressor_required 和 lactate_gt_2
    assert clinical["layer4_shock"]["criteria"]["vasopressor_required"] is True
    assert clinical["layer4_shock"]["criteria"]["lactate_gt_2"] is False


# ============================================================
# 场景9: 版本元数据验证
# ============================================================

def test_version_meta_attached():
    """验证评分版本元数据被正确附加"""
    eval_time = _utc(2026, 1, 15, 12)
    observations = [
        {"code": "MAP", "value_number": 85, "unit": "mmHg", "observed_at": _utc(2026, 1, 15, 10)},
    ]
    medications = []

    sofa_result = compute_sofa_scores_from_data(observations, medications, eval_time)

    assert "version_meta" in sofa_result
    assert sofa_result["version_meta"]["classic"]["rulepack_id"] == "classic-sofa-1996"
    assert sofa_result["version_meta"]["sofa2"]["rulepack_id"] == "sofa-2-2025"
    assert sofa_result["version_meta"]["classic"]["clinical_approval_status"] == "not_approved"
    assert sofa_result["version_meta"]["sofa2"]["lifecycle_status"] == "experimental"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
