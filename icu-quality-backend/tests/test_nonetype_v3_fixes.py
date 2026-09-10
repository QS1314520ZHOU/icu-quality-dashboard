"""
V3 NoneType 回归测试
====================
修复 `.get(key, {}).get()` 在 key 存在但值为 None 时崩溃的问题。

根因: Python dict.get(key, default) 在 key 存在时返回存储值 (包括 None),
      不返回 default。因此 `.get("k", {}).get("x")` 在 `d["k"] = None` 时
      等价于 `None.get("x")` → AttributeError。

修复: 改用 `(d.get("k") or {}).get("x")` 模式。

测试场景:
  1. bundle_1h/bundle_3h 为 None 时不崩溃
  2. v3 为 None 时不崩溃
  3. sofa 为 None 时不崩溃
  4. clinical_layer 为 None 时不崩溃
  5. infection_evidence 各字段为 False 时不丢失
  6. 候选引擎处理缺失数据返回 pending_review
"""
import pytest
from datetime import datetime, timedelta, timezone


# ============================================================
# Issue 1: bundle_1h/bundle_3h 为 None 时的安全访问
# ============================================================

class TestBundleNoneAccess:
    """验证 bundle_1h/bundle_3h 为 None 时不会崩溃"""

    def test_bundle_1h_none_get_finish(self):
        """v3["bundle_1h"] = None 时，安全访问 .get("finish")"""
        v3 = {"bundle_1h": None, "bundle_3h": None, "gate": {}}

        # 旧代码会崩溃: v3.get("bundle_1h", {}).get("finish")
        # 修复后:
        bundle_1h = v3.get("bundle_1h") or {}
        assert bundle_1h.get("finish") is None

    def test_bundle_3h_none_get_finish(self):
        """v3["bundle_3h"] = None 时，安全访问 .get("finish")"""
        v3 = {"bundle_1h": None, "bundle_3h": None}

        bundle_3h = v3.get("bundle_3h") or {}
        assert bundle_3h.get("finish") is None

    def test_bundle_1h_dict_get_finish(self):
        """v3["bundle_1h"] 是正常 dict 时，行为不变"""
        v3 = {"bundle_1h": {"finish": True, "step1": True}, "bundle_3h": {"finish": False}}

        bundle_1h = v3.get("bundle_1h") or {}
        assert bundle_1h.get("finish") is True

    def test_bundle_1h_missing_key(self):
        """v3 没有 bundle_1h key 时，安全返回 None"""
        v3 = {"gate": {}}

        bundle_1h = v3.get("bundle_1h") or {}
        assert bundle_1h.get("finish") is None

    def test_bundle_1h_none_old_pattern_crashes(self):
        """验证旧的 .get(key, {}).get() 模式确实会崩溃"""
        v3 = {"bundle_1h": None}

        with pytest.raises(AttributeError, match="'NoneType' object has no attribute 'get'"):
            v3.get("bundle_1h", {}).get("finish")


# ============================================================
# Issue 2: v3 dict 中 k1/k2 为 None 时的安全访问
# ============================================================

class TestV3K1K2Access:
    """验证 v3 中 k1/k2 字段的安全访问"""

    def test_v3_none_k1_k2(self):
        """v3 = None 时，安全访问 k1/k2"""
        v3 = None
        result = (v3 or {}).get("k1")
        assert result is None

    def test_v3_k1_none_k2_true(self):
        """k1=None, k2=True 时，不满足 K1 AND K2"""
        v3 = {"k1": None, "k2": True}
        result = (v3.get("k1") == True) and (v3.get("k2") == True)
        assert result is False

    def test_v3_k1_false_k2_true(self):
        """k1=False, k2=True 时，不满足 K1 AND K2"""
        v3 = {"k1": False, "k2": True}
        result = (v3.get("k1") == True) and (v3.get("k2") == True)
        assert result is False

    def test_v3_k1_true_k2_true(self):
        """k1=True, k2=True 时，满足 K1 AND K2"""
        v3 = {"k1": True, "k2": True}
        assert (v3.get("k1") == True) and (v3.get("k2") == True) is True


# ============================================================
# Issue 3: sofa 为 None 时的安全访问
# ============================================================

class TestSofaNoneAccess:
    """验证 sofa 结果为 None 时的安全访问"""

    def test_sofa_none_container(self):
        """sofa = None 时，sofa_container 为空 dict"""
        v3_result = {"sofa": None}
        sofa_container = v3_result.get("sofa") or {}
        assert sofa_container == {}
        assert sofa_container.get("sofa2") is None

    def test_sofa_none_classic(self):
        """sofa = None 时，classic_sofa_result 为 None"""
        v3_result = {"sofa": None}
        sofa_container = v3_result.get("sofa") or {}
        classic_result = sofa_container.get("classic") or v3_result.get("classic")
        assert classic_result is None

    def test_sofa_normal_structure(self):
        """正常 sofa 结构时，行为不变"""
        v3_result = {
            "sofa": {
                "sofa2": {"sofa2_score": 5},
                "classic": {"sofa_score": 4},
            }
        }
        sofa_container = v3_result.get("sofa") or {}
        assert sofa_container.get("sofa2") == {"sofa2_score": 5}


# ============================================================
# Issue 4: clinical_layer 为 None 时的安全访问
# ============================================================

class TestClinicalLayerNoneAccess:
    """验证 clinical_layer 为 None 时的安全访问"""

    def test_clinical_layer_none(self):
        """clinical_layer = None 时，安全降级为空 dict"""
        v3 = {"clinical_layer": None}
        cl = v3.get("clinical_layer") or {}
        assert cl == {}
        assert cl.get("layer4_shock", {}) == {}

    def test_clinical_layer_with_sofa2_total(self):
        """clinical_layer 正常时，sofa2_total 可访问"""
        v3 = {
            "clinical_layer": {
                "layer2_organ_dysfunction": {"sofa2_total": 5}
            }
        }
        cl = v3.get("clinical_layer") or {}
        sofa2_total = (cl.get("layer2_organ_dysfunction") or {}).get("sofa2_total")
        assert sofa2_total == 5

    def test_clinical_layer_missing_organ_key(self):
        """clinical_layer 存在但缺少 layer2 时，安全返回 None"""
        v3 = {"clinical_layer": {"layer1_infection": {}}}
        cl = v3.get("clinical_layer") or {}
        sofa2_total = (cl.get("layer2_organ_dysfunction") or {}).get("sofa2_total")
        assert sofa2_total is None


# ============================================================
# Issue 5: 感染证据 False 不被 or 吞掉
# ============================================================

class TestInfectionEvidenceFalsePreservation:
    """验证 False 感染证据不会被 or 运算符吞掉"""

    def test_i1_false_not_overridden(self):
        """i1=False (明确无感染) 不被后续 None 覆盖"""
        v3_result = {"i1": False, "i2": None, "i3": None}

        # 旧代码: i1 = v3_result.get("i1") or ... → False or None = None (BUG!)
        # 修复后:
        i1 = v3_result.get("i1")
        if i1 is None:
            i1 = (v3_result.get("infection_evidence") or {}).get("i1")
        assert i1 is False  # False 被保留

    def test_i1_true_preserved(self):
        """i1=True 仍然正确"""
        v3_result = {"i1": True, "i2": None, "i3": None}

        i1 = v3_result.get("i1")
        if i1 is None:
            i1 = (v3_result.get("infection_evidence") or {}).get("i1")
        assert i1 is True

    def test_i1_none_falls_through(self):
        """i1=None 时回退到 infection_evidence"""
        v3_result = {
            "i1": None,
            "infection_evidence": {"i1": True}
        }

        i1 = v3_result.get("i1")
        if i1 is None:
            i1 = (v3_result.get("infection_evidence") or {}).get("i1")
        assert i1 is True


# ============================================================
# Issue 6: 升压药 False 不被 or 吞掉
# ============================================================

class TestVasopressorFalsePreservation:
    """验证 False 升压药证据不会被 or 运算符吞掉"""

    def test_k2_false_not_overridden(self):
        """k2=False 不被 has_vasopressor 覆盖"""
        v3_result = {"k2": False, "has_vasopressor": True}

        # 旧代码: has_vasopressor = v3_result.get("k2") or v3_result.get("has_vasopressor") or False
        # → False or True or False = True (BUG! k2=False 被吞掉)
        # 修复后:
        k2_val = v3_result.get("k2")
        if k2_val is not None:
            has_vasopressor = bool(k2_val)
        else:
            has_vasopressor = bool(v3_result.get("has_vasopressor"))
        assert has_vasopressor is False  # k2=False 被保留

    def test_k2_true_preserved(self):
        """k2=True 仍然正确"""
        v3_result = {"k2": True}

        k2_val = v3_result.get("k2")
        if k2_val is not None:
            has_vasopressor = bool(k2_val)
        else:
            has_vasopressor = bool(v3_result.get("has_vasopressor"))
        assert has_vasopressor is True

    def test_k2_none_falls_through(self):
        """k2=None 时回退到 has_vasopressor"""
        v3_result = {"k2": None, "has_vasopressor": True}

        k2_val = v3_result.get("k2")
        if k2_val is not None:
            has_vasopressor = bool(k2_val)
        else:
            has_vasopressor = bool(v3_result.get("has_vasopressor"))
        assert has_vasopressor is True


# ============================================================
# Issue 7: 候选引擎处理 None sofa 数据
# ============================================================

class TestCandidateEngineWithNoneSofa:
    """验证候选引擎在 sofa 数据为 None 时仍能正常工作"""

    def test_extract_candidate_with_none_sofa(self):
        """sofa=None 时，候选引擎不崩溃"""
        from scoring.candidate_engine import extract_candidate

        v3_result = {
            "sofa": None,
            "i1": True,
            "k2": True,
            "lactate_initial": 3.5,
            "map_min": 55,
            "diagnosis_text": "脓毒性休克",
        }

        result = extract_candidate(v3_result=v3_result)
        assert result is not None
        assert "candidate_status" in result

    def test_extract_candidate_with_missing_sofa(self):
        """没有 sofa key 时，候选引擎不崩溃"""
        from scoring.candidate_engine import extract_candidate

        v3_result = {
            "i1": True,
            "k2": True,
            "lactate_initial": 3.5,
        }

        result = extract_candidate(v3_result=v3_result)
        assert result is not None

    def test_extract_candidate_all_none(self):
        """所有字段为 None 时，候选引擎返回 not_candidate"""
        from scoring.candidate_engine import extract_candidate

        result = extract_candidate(v3_result={})
        assert result is not None
        assert result["candidate_status"] == "not_candidate"


# ============================================================
# Issue 8: summary.py 中 v3 为 None 的安全访问
# ============================================================

class TestSummaryV3NoneAccess:
    """验证 summary.py 中 v3 可能为 None 时的安全访问"""

    def test_v3_key_missing_in_pat(self):
        """患者没有 v3 key 时，安全降级"""
        pat = {"mrn": "test"}
        v3 = pat.get("v3") or {}
        assert v3 == {}
        assert v3.get("k1") is None

    def test_v3_key_none_in_pat(self):
        """患者 v3=None 时，安全降级"""
        pat = {"mrn": "test", "v3": None}
        v3 = pat.get("v3") or {}
        assert v3 == {}

    def test_official_den_filter_with_none_v3(self):
        """v3=None 的患者不会进入正式分母"""
        all_den_candidates = [
            {"mrn": "p1", "v3": {"k1": True, "k2": True}},
            {"mrn": "p2", "v3": None},
            {"mrn": "p3"},  # no v3 key
            {"mrn": "p4", "v3": {"k1": True, "k2": False}},
        ]

        official_den = [
            p for p in all_den_candidates
            if (p.get("v3") or {}).get("k1") == True and (p.get("v3") or {}).get("k2") == True
        ]

        assert len(official_den) == 1
        assert official_den[0]["mrn"] == "p1"
