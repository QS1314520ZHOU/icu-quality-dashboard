"""ICU-05 Bundle 1h/3h/6h 独立性测试
验证三个时间窗口各自独立判定，互不影响"""
import pytest
from datetime import datetime, timedelta

# 注入 VASO_WIDE_LABELS
import scoring.bundle_engine as engine
try:
    engine.set_vaso_wide_labels({
        "去甲肾上腺素", "norepinephrine",
        "肾上腺素", "epinephrine",
        "多巴胺", "dopamine",
        "多巴酚丁胺", "dobutamine",
        "血管加压素", "vasopressin",
    })
except RuntimeError:
    pass  # 已注入

from scoring.bundle_engine import judge_bundle_v3


def make_patient_data(
    t0=None,
    # Gate: organ dysfunction
    pf_ratio_min=200,  # 默认触发S1 (pf_ratio < 300)
    gcs_min=None,
    map_min=None,
    has_vasopressor=True,  # 默认有升压药，触发S4和K2
    # Gate: infection
    diagnosis_text="脓毒症",
    has_antibiotic=True,
    has_culture=True,
    # Gate: shock confirmation
    lactate_initial=5.0,  # 默认高乳酸，触发K1
    # 1h window
    w1h_lactate_initial=5.0,
    w1h_antibiotic_time=None,
    w1h_culture_time=None,
    w1h_map_min=None,
    w1h_lactate_max=None,
    w1h_has_fluid=False,
    # 3h window
    w3h_lactate_initial=5.0,
    w3h_antibiotic_time=None,
    w3h_culture_time=None,
    w3h_map_min=None,
    w3h_lactate_max=None,
    w3h_fluid_ml=0,
    # 6h window
    w6h_lactate_initial=5.0,
    w6h_antibiotic_time=None,
    w6h_culture_time=None,
    w6h_map_min=None,
    w6h_lactate_max=None,
    w6h_fluid_ml=0,
    w6h_has_lactate_recheck=True,  # 6h特有: 复测乳酸
):
    """构造 judge_bundle_v3 所需的完整 patient_data
    默认值已配置为通过所有门控条件"""
    if t0 is None:
        t0 = datetime(2026, 6, 15, 10, 0, 0)

    return {
        "t0": t0,
        # Gate: organ dysfunction (S1-S4)
        "pf_ratio_min": pf_ratio_min,
        "gcs_min": gcs_min,
        "map_min": map_min,
        "has_vasopressor": has_vasopressor,
        # Gate: infection (I1-I3)
        "diagnosis_text": diagnosis_text,
        "has_antibiotic": has_antibiotic,
        "has_culture": has_culture,
        # Gate: shock confirmation (K1-K2)
        "lactate_initial": lactate_initial,
        # 1h window
        "w1h": {
            "lactate_initial": w1h_lactate_initial,
            "antibiotic_time": w1h_antibiotic_time,
            "culture_time": w1h_culture_time,
            "map_min": w1h_map_min,
            "lactate_max": w1h_lactate_max,
            "has_fluid": w1h_has_fluid,
        },
        # 3h window
        "w3h": {
            "lactate_initial": w3h_lactate_initial,
            "antibiotic_time": w3h_antibiotic_time,
            "culture_time": w3h_culture_time,
            "map_min": w3h_map_min,
            "lactate_max": w3h_lactate_max,
            "fluid_ml": w3h_fluid_ml,
        },
        # 6h window
        "w6h": {
            "lactate_initial": w6h_lactate_initial,
            "antibiotic_time": w6h_antibiotic_time,
            "culture_time": w6h_culture_time,
            "map_min": w6h_map_min,
            "lactate_max": w6h_lactate_max,
            "fluid_ml": w6h_fluid_ml,
            "has_lactate_recheck": w6h_has_lactate_recheck,
        },
    }


def get_bundle_finish(result, bundle_key):
    """安全获取 Bundle 完成状态
    返回: True (完成), False (未完成), None (未触发/数据缺失)
    """
    bundle = result.get(bundle_key)
    if bundle is None:
        return None
    return bundle.get("finish")


def is_bundle_complete(result, bundle_key):
    """判断 Bundle 是否完成
    返回: True (完成), False (未完成或未触发)
    """
    finish = get_bundle_finish(result, bundle_key)
    return finish is True


def assert_bundle_finish(result, expected_1h, expected_3h, expected_6h):
    """断言 Bundle 完成状态"""
    finish_1h = get_bundle_finish(result, "bundle_1h")
    finish_3h = get_bundle_finish(result, "bundle_3h")
    finish_6h = get_bundle_finish(result, "bundle_6h")
    assert finish_1h == expected_1h, f"1h expected={expected_1h}, got={finish_1h}"
    assert finish_3h == expected_3h, f"3h expected={expected_3h}, got={finish_3h}"
    assert finish_6h == expected_6h, f"6h expected={expected_6h}, got={finish_6h}"


class TestBundle1hIndependence:
    """1h Bundle 独立性测试"""

    def test_1h_complete_independent_of_3h_6h(self):
        """1h完成不应受3h/6h未完成影响"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            # 1h: 全部完成 + 低MAP触发Step3
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,  # 1h有液体
            w1h_map_min=60,      # MAP<70触发C1
            # 3h: 无液体 + 低MAP触发Step3
            w3h_fluid_ml=0,
            w3h_map_min=60,      # MAP<70触发C1
            # 6h: 无液体 + 低MAP触发Step3
            w6h_fluid_ml=0,
            w6h_map_min=60,      # MAP<70触发C1
        )
        result = judge_bundle_v3(data)
        # 1h应完成，3h/6h应未完成
        assert is_bundle_complete(result, "bundle_1h") is True
        assert is_bundle_complete(result, "bundle_3h") is False
        assert is_bundle_complete(result, "bundle_6h") is False

    def test_1h_only_needs_fluid_presence(self):
        """1h Bundle 只需要有液体复苏，不要求1500ml"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            # 1h: 有液体但量少 + 低MAP触发Step3
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,  # 只要有液体
            w1h_map_min=60,      # MAP<70触发C1
            w3h_fluid_ml=0,
            w6h_fluid_ml=0,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_1h") is True

    def test_1h_fails_without_lactate(self):
        """1h未测乳酸应失败"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            # 1h: 未测乳酸
            w1h_lactate_initial=None,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            w3h_fluid_ml=0,
            w3h_map_min=60,
            w6h_fluid_ml=0,
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        # 乳酸未测 → a1=None → finish=None (不是False)
        assert is_bundle_complete(result, "bundle_1h") is False


class TestBundle3hIndependence:
    """3h Bundle 独立性测试"""

    def test_3h_complete_independent_of_6h(self):
        """3h完成不应受6h未完成影响"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,      # MAP<70触发C1
            # 3h: 达标 + 低MAP触发Step3
            w3h_lactate_initial=5.0,
            w3h_antibiotic_time=t0 + timedelta(minutes=30),
            w3h_culture_time=t0 + timedelta(minutes=20),
            w3h_fluid_ml=1500,  # 3h达标
            w3h_map_min=60,      # MAP<70触发C1
            # 6h: 无液体
            w6h_fluid_ml=0,
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_3h") is True
        assert is_bundle_complete(result, "bundle_6h") is False

    def test_3h_needs_1500ml(self):
        """3h Bundle 需要 >=1500ml"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            # 3h: 不足1500ml + 低MAP触发Step3
            w3h_lactate_initial=5.0,
            w3h_antibiotic_time=t0 + timedelta(minutes=30),
            w3h_culture_time=t0 + timedelta(minutes=20),
            w3h_fluid_ml=1499,
            w3h_map_min=60,
            w6h_fluid_ml=0,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_3h") is False

    def test_3h_fails_without_blood_culture_before_ab(self):
        """3h血培养未在抗菌药前采集应失败"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            # 3h: 血培养在抗菌药后 + 低MAP触发Step3
            w3h_lactate_initial=5.0,
            w3h_antibiotic_time=t0 + timedelta(minutes=30),
            w3h_culture_time=t0 + timedelta(hours=2),  # 血培养在抗菌药后
            w3h_fluid_ml=1500,
            w3h_map_min=60,
            w6h_fluid_ml=0,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_3h") is False


class TestBundle6hIndependence:
    """6h Bundle 独立性测试"""

    def test_6h_complete_independent_of_3h(self):
        """6h完成不应受3h未完成影响"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            # 3h: 无液体
            w3h_lactate_initial=5.0,
            w3h_antibiotic_time=t0 + timedelta(minutes=30),
            w3h_culture_time=t0 + timedelta(minutes=20),
            w3h_fluid_ml=0,
            w3h_map_min=60,
            # 6h: 达标 + 低MAP触发Step3
            w6h_lactate_initial=5.0,
            w6h_antibiotic_time=t0 + timedelta(minutes=30),
            w6h_culture_time=t0 + timedelta(minutes=20),
            w6h_fluid_ml=2000,  # 6h达标
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_3h") is False
        assert is_bundle_complete(result, "bundle_6h") is True

    def test_6h_needs_1500ml(self):
        """6h Bundle 需要 >=1500ml"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            w3h_fluid_ml=0,
            w3h_map_min=60,
            # 6h: 不足1500ml + 低MAP触发Step3
            w6h_lactate_initial=5.0,
            w6h_antibiotic_time=t0 + timedelta(minutes=30),
            w6h_culture_time=t0 + timedelta(minutes=20),
            w6h_fluid_ml=1499,
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_6h") is False

    def test_6h_elevated_lactate_triggers_fluid_requirement(self):
        """6h高乳酸触发液体需求"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            w3h_fluid_ml=0,
            w3h_map_min=60,
            # 6h: 高乳酸+液体达标
            w6h_lactate_initial=5.0,
            w6h_lactate_max=4.5,  # 乳酸>=4触发C2
            w6h_antibiotic_time=t0 + timedelta(minutes=30),
            w6h_culture_time=t0 + timedelta(minutes=20),
            w6h_fluid_ml=1500,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_6h") is True


class TestBundleCrossIndependence:
    """跨时间窗口独立性测试"""

    def test_all_three_complete(self):
        """三个Bundle全部完成"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,
            w1h_map_min=60,
            w3h_lactate_initial=5.0,
            w3h_antibiotic_time=t0 + timedelta(minutes=30),
            w3h_culture_time=t0 + timedelta(minutes=20),
            w3h_fluid_ml=1500,
            w3h_map_min=60,
            w6h_lactate_initial=5.0,
            w6h_antibiotic_time=t0 + timedelta(minutes=30),
            w6h_culture_time=t0 + timedelta(minutes=20),
            w6h_fluid_ml=2000,
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_1h") is True
        assert is_bundle_complete(result, "bundle_3h") is True
        assert is_bundle_complete(result, "bundle_6h") is True

    def test_only_1h_complete(self):
        """仅1h完成，3h/6h未完成"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            w1h_lactate_initial=5.0,
            w1h_antibiotic_time=t0 + timedelta(minutes=30),
            w1h_culture_time=t0 + timedelta(minutes=20),
            w1h_has_fluid=True,  # 1h有液体
            w1h_map_min=60,      # MAP<70触发C1
            w3h_fluid_ml=0,      # 3h无液体
            w3h_map_min=60,
            w6h_fluid_ml=0,      # 6h无液体
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        assert is_bundle_complete(result, "bundle_1h") is True
        assert is_bundle_complete(result, "bundle_3h") is False
        assert is_bundle_complete(result, "bundle_6h") is False

    def test_none_complete(self):
        """全部未完成（乳酸未测）"""
        t0 = datetime(2026, 6, 15, 10, 0, 0)
        data = make_patient_data(
            t0=t0,
            # 所有窗口乳酸未测
            w1h_lactate_initial=None,
            w1h_has_fluid=True,
            w1h_map_min=60,
            w3h_lactate_initial=None,
            w3h_fluid_ml=1500,
            w3h_map_min=60,
            w6h_lactate_initial=None,
            w6h_fluid_ml=2000,
            w6h_map_min=60,
        )
        result = judge_bundle_v3(data)
        # 乳酸未测 → a1=None → finish=None (不是False)
        assert is_bundle_complete(result, "bundle_1h") is False
        assert is_bundle_complete(result, "bundle_3h") is False
        assert is_bundle_complete(result, "bundle_6h") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
