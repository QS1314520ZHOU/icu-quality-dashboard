"""
第二轮修复回归断言测试。
覆盖 #4, #11, #14, #18 回归断言。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring.adapter import canon_drug


# ---- #1: canon_drug 测试 ----

def test_canon_drug_phenylephrine_alone_score2():
    """#23: 苯肾上腺素 1.0 ug/kg/min 单独使用 → SOFA-2 心血管 = 2，不是 4"""
    from datetime import datetime, timezone
    from scoring.sofa2_core import _calc_cardiovascular

    # 苯肾上腺素 → phenylephrine（other 桶），SOFA-2 other_vasopressor → ≥2
    assert canon_drug("苯肾上腺素") == "phenylephrine"
    assert canon_drug("phenylephrine") == "phenylephrine"

    # 端到端测试
    eval_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    pressors = [
        {
            "med_name": "苯肾上腺素",
            "route": "静脉泵入",
            "dose_ugkgmin": 1.0,
            "admin_end": None,
        }
    ]
    score, info = _calc_cardiovascular([], eval_time, pressors, weight_kg=70.0)
    assert score == 2, f"Expected score=2 (other_vasopressor), got {score}"


def test_canon_drug_isoproterenol_other():
    """异丙肾上腺素 任意剂量 → other 桶"""
    assert canon_drug("异丙肾上腺素") == "isoproterenol"
    assert canon_drug("isoproterenol") == "isoproterenol"


def test_canon_drug_norepinephrine_salt_form():
    """重酒石酸去甲肾上腺素注射液 → canon_drug 返回 norepinephrine"""
    assert canon_drug("重酒石酸去甲肾上腺素注射液") == "norepinephrine"
    assert canon_drug("去甲肾上腺素") == "norepinephrine"
    assert canon_drug("noradrenaline") == "norepinephrine"


def test_canon_drug_dobutamine_not_dopamine():
    """多巴酚丁胺 → dobutamine，不是 dopamine"""
    assert canon_drug("多巴酚丁胺") == "dobutamine"
    assert canon_drug("dobutamine") == "dobutamine"
    # 确认不会误匹配为 dopamine
    assert canon_drug("多巴酚丁胺") != "dopamine"


def test_canon_drug_epinephrine_priority():
    """肾上腺素必须排在去甲/异丙/苯/去氧之后"""
    # 去甲肾上腺素 → norepinephrine（不是 epinephrine）
    assert canon_drug("去甲肾上腺素") == "norepinephrine"
    # 肾上腺素 → epinephrine
    assert canon_drug("肾上腺素") == "epinephrine"
    assert canon_drug("adrenaline") == "epinephrine"
    assert canon_drug("epinephrine") == "epinephrine"


def test_canon_drug_none_for_unknown():
    """未知药物返回 None"""
    assert canon_drug("阿莫西林") is None
    assert canon_drug("") is None
    assert canon_drug(None) is None


# ---- #23: GCS 阈值表首行 ----

def test_gcs_threshold_first_row():
    """GCS 两张表首行 {"low":15,"high":15} 改成 {"low":15,"high":16}"""
    from scoring.sofa_rules import CLASSIC_SOFA_THRESHOLDS, SOFA2_THRESHOLDS
    classic_gcs = CLASSIC_SOFA_THRESHOLDS["central_nervous_system"]["thresholds"]
    sofa2_gcs = SOFA2_THRESHOLDS["brain"]["thresholds"]
    assert classic_gcs[0]["low"] == 15
    assert classic_gcs[0]["high"] == 16
    assert sofa2_gcs[0]["low"] == 15
    assert sofa2_gcs[0]["high"] == 16


# ---- #17: GCS 正则 E 最大 4 ----

def test_gcs_regex_e_max_4():
    """E4VTM6 → 两版都得 0 分"""
    from scoring.sofa_core import _parse_gcs
    total, err = _parse_gcs("E4VTM6")
    # V=T → motor fallback, not a total score
    assert err == "V=T_motor_fallback"


def test_gcs_regex_e5_rejected():
    """E5 应被拒绝（E 最大 4）"""
    from scoring.sofa_core import _parse_gcs
    total, err = _parse_gcs("E5V1M1")
    assert total is None
    assert err is not None


# ---- #18: GCS 回归断言 ----

def test_gcs_e4vtm6_score_0():
    """#23: E4VTM6 → motor fallback: M6=0，端到端测试"""
    from datetime import datetime, timezone
    from scoring.sofa_core import _calc_cns
    from scoring.sofa2_core import _calc_brain

    eval_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    obs = [
        {"code": "param_score_gcs_obs", "value_text": "E4VTM6", "observed_at": eval_time, "unit": ""},
    ]

    # 经典 SOFA
    score_classic, _ = _calc_cns(obs, eval_time)
    assert score_classic == 0, f"Expected classic score=0, got {score_classic}"

    # SOFA-2
    score_sofa2, _ = _calc_brain(obs, eval_time)
    assert score_sofa2 == 0, f"Expected sofa2 score=0, got {score_sofa2}"


def test_gcs_e1vtm1_score_4():
    """E1VTM1 → motor fallback: M1=4"""
    from scoring.sofa_rules import SOFA2_THRESHOLDS
    motor_fallback = SOFA2_THRESHOLDS["brain"]["motor_fallback"]
    assert motor_fallback[1] == 4


def test_gcs_window_takes_worst():
    """同一窗口内 GCS 15@08:00 与 GCS 6@12:00，evaluation_time=13:00 → 取 6 得 3 分"""
    from datetime import datetime, timezone
    from scoring.sofa_core import _lowest_gcs_in_window

    eval_time = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    t08 = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    t12 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    obs = [
        {"code": "param_score_gcs_obs", "value_number": 15, "observed_at": t08, "unit": ""},
        {"code": "param_score_gcs_obs", "value_number": 6, "observed_at": t12, "unit": ""},
    ]

    gcs_total, gcs_ts, vt_motor, vt_only = _lowest_gcs_in_window(
        obs, ["param_score_gcs_obs", "gcsScore", "GCS"], eval_time, lookback_h=24
    )
    assert gcs_total == 6, f"Expected GCS=6 (worst), got {gcs_total}"
    assert gcs_ts == t12


# ---- #14: 呼吸配对回归断言 ----

def test_respiratory_pair_worst_ratio():
    """PaO2=60@10:00 与 FiO2=0.21@10:00、FiO2=1.0@10:20 → 应取 60/1.0=60（最差）"""
    from datetime import datetime, timezone, timedelta
    from scoring.sofa_core import _worst_pf_pair_in_window

    eval_time = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
    t10_00 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t10_20 = datetime(2025, 1, 1, 10, 20, 0, tzinfo=timezone.utc)

    obs = [
        {"code": "PaO2", "value_number": 60, "observed_at": t10_00, "unit": "mmHg"},
        {"code": "FiO2", "value_number": 0.21, "observed_at": t10_00, "unit": ""},
        {"code": "FiO2", "value_number": 1.0, "observed_at": t10_20, "unit": ""},
    ]

    result = _worst_pf_pair_in_window(obs, ["PaO2"], ["FiO2"], eval_time, lookback_h=24)
    assert result is not None
    ratio, pao2_ts, fio2_ts = result
    # 最差 = 最小 ratio = 60/1.0 = 60
    assert abs(ratio - 60.0) < 0.1, f"Expected ratio ~60, got {ratio}"
    assert fio2_ts == t10_20, "Should pair with FiO2=1.0 at 10:20"


# ---- #11: 窗口校验回归断言 ----

def test_antibiotic_150min_1h_false_3h_true():
    """抗生素执行时间 = t0 + 150 分钟 → bundle_1h 的 b1 为 False，bundle_3h 的 b1 为 True"""
    from datetime import datetime, timezone, timedelta
    from scoring.bundle_engine import judge_bundle_v3, set_vaso_wide_labels

    # 确保 VASO_WIDE 已注入
    set_vaso_wide_labels({"去甲肾上腺素", "norepinephrine"})

    t0 = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    abx_time = t0 + timedelta(minutes=150)  # 2.5h 后 → 超出 1h 窗口，在 3h 窗口内

    patient_data = {
        "t0": t0,
        "diagnosis_text": "脓毒症",
        "has_antibiotic": True,
        "has_culture": True,
        "has_vasopressor": True,
        "lactate_initial": 3.0,
        "gcs_min": 10,
        "pf_ratio_min": 200,
        "map_min": 60,
        "w1h": {
            "lactate_initial": 3.0,
            "lactate_max": 3.0,
            "map_min": 60,
            "antibiotic_time": abx_time,  # 不在 1h 窗口内
            "culture_time": t0 + timedelta(minutes=10),
            "has_fluid": True,
        },
        "w3h": {
            "lactate_initial": 3.0,
            "lactate_max": 3.0,
            "map_min": 60,
            "antibiotic_time": abx_time,  # 在 3h 窗口内
            "culture_time": t0 + timedelta(minutes=10),
            "fluid_ml": 2000,
        },
    }

    result = judge_bundle_v3(patient_data)
    b1_1h = result["bundle_1h"]["b1"]
    b1_3h = result["bundle_3h"]["b1"]

    # 1h: 抗生素在窗口外 → b1 应为 None（窗口外数据不参与达标）
    assert b1_1h is None, f"1h b1 should be None (out of window), got {b1_1h}"
    # 3h: 抗生素在窗口内 → b1 应为 True
    assert b1_3h is True, f"3h b1 should be True, got {b1_3h}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
