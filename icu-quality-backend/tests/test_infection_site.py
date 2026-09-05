# -*- coding: utf-8 -*-
# G-1: 感染部位人工确认与入库 — 单元测试
import pytest
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSuggestInfectionSite:
    """suggest_infection_site 纯函数测试（无 DB 依赖）"""

    def test_lung_suggestion(self):
        from db import suggest_infection_site
        result = suggest_infection_site(
            diagnosis_text="重症肺炎 呼吸衰竭",
            order_names=["头孢哌酮舒巴坦", "莫西沙星"],
            culture_specimens=["痰培养"],
        )
        assert len(result) > 0
        assert result[0]["site"] == "lung"
        assert result[0]["score"] >= 2
        assert "肺炎" in result[0]["matched_keywords"]

    def test_bloodstream_suggestion(self):
        from db import suggest_infection_site
        result = suggest_infection_site(
            diagnosis_text="败血症",
            order_names=["万古霉素"],
            culture_specimens=["血培养"],
        )
        sites = [r["site"] for r in result]
        assert "bloodstream_non_catheter" in sites

    def test_empty_returns_empty(self):
        from db import suggest_infection_site
        result = suggest_infection_site(
            diagnosis_text="",
            order_names=[],
            culture_specimens=[],
        )
        assert result == []

    def test_multiple_sites_scored(self):
        from db import suggest_infection_site
        result = suggest_infection_site(
            diagnosis_text="肺炎 腹腔感染 败血症",
            order_names=["美罗培南", "万古霉素"],
            culture_specimens=["痰培养", "血培养", "腹腔引流液培养"],
        )
        sites = [r["site"] for r in result]
        assert "lung" in sites
        assert "bloodstream_non_catheter" in sites
        assert "abdomen" in sites
        # 分数应该降序排列
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_uti_suggestion(self):
        from db import suggest_infection_site
        result = suggest_infection_site(
            diagnosis_text="尿路感染",
            order_names=["左氧氟沙星"],
            culture_specimens=["中段尿培养"],
        )
        sites = [r["site"] for r in result]
        assert "urinary" in sites


class TestInfectionSiteConfig:
    """config/infection_sites.py 配置测试"""

    def test_validate_site_code_valid(self):
        from config.infection_sites import validate_site_code
        assert validate_site_code("lung") is True
        assert validate_site_code("bloodstream_catheter") is True
        assert validate_site_code("bloodstream_non_catheter") is True
        assert validate_site_code("abdomen") is True

    def test_validate_site_code_invalid(self):
        from config.infection_sites import validate_site_code
        assert validate_site_code("invalid_site") is False
        assert validate_site_code("") is False
        assert validate_site_code(None) is False

    def test_validate_evidence_type_valid(self):
        from config.infection_sites import validate_evidence_type
        assert validate_evidence_type("clinical") is True
        assert validate_evidence_type("microbiology") is True
        assert validate_evidence_type("imaging") is True

    def test_validate_evidence_type_invalid(self):
        from config.infection_sites import validate_evidence_type
        assert validate_evidence_type("invalid") is False

    def test_get_site_label(self):
        from config.infection_sites import get_site_label
        assert get_site_label("lung") == "肺部"
        assert get_site_label("abdomen") == "腹腔"
        assert get_site_label("invalid") == "invalid"

    def test_get_site_options(self):
        from config.infection_sites import get_site_options
        options = get_site_options()
        assert len(options) == 11
        codes = [o["code"] for o in options]
        assert "lung" in codes
        assert "bloodstream_catheter" in codes
        assert "bloodstream_non_catheter" in codes


class TestCreateInfectionSiteValidation:
    """create_infection_site 输入校验测试（无真实 DB，仅测校验逻辑）"""

    def test_invalid_primary_site_raises(self):
        from db import create_infection_site
        with pytest.raises(ValueError, match="primary_site"):
            create_infection_site({
                "exclusion_key": "test|202509011200",
                "primary_site": "invalid_site",
                "evidence_type": "clinical",
                "confirmed_by": "test_user",
            })

    def test_invalid_evidence_type_raises(self):
        from db import create_infection_site
        with pytest.raises(ValueError, match="evidence_type"):
            create_infection_site({
                "exclusion_key": "test|202509011200",
                "primary_site": "lung",
                "evidence_type": "invalid_type",
                "confirmed_by": "test_user",
            })

    def test_primary_in_secondary_raises(self):
        from db import create_infection_site
        with pytest.raises(ValueError):
            create_infection_site({
                "exclusion_key": "test|202509011200",
                "primary_site": "lung",
                "secondary_sites": ["lung", "abdomen"],
                "evidence_type": "clinical",
                "confirmed_by": "test_user",
            })

    def test_empty_exclusion_key_raises(self):
        from db import create_infection_site
        with pytest.raises(ValueError, match="exclusion_key"):
            create_infection_site({
                "exclusion_key": "",
                "primary_site": "lung",
                "evidence_type": "clinical",
                "confirmed_by": "test_user",
            })

    def test_empty_confirmed_by_raises(self):
        from db import create_infection_site
        with pytest.raises(ValueError, match="confirmed_by"):
            create_infection_site({
                "exclusion_key": "test|202509011200",
                "primary_site": "lung",
                "evidence_type": "clinical",
                "confirmed_by": "",
            })


class TestRevokeInfectionSiteValidation:
    """revoke_infection_site 校验测试"""

    def test_invalid_record_id_raises(self):
        from db import revoke_infection_site
        with pytest.raises(Exception):
            revoke_infection_site("not_a_valid_objectid", "test_user")


class TestBuildExclusionKey:
    """build_exclusion_key 一致性测试"""

    def test_datetime_input(self):
        from db import build_exclusion_key
        from datetime import datetime
        result = build_exclusion_key("P001", datetime(2025, 9, 1, 12, 30))
        assert result == "P001|202509011230"

    def test_string_input(self):
        from db import build_exclusion_key
        result = build_exclusion_key("P001", "2025-09-01 12:30:00")
        assert result == "P001|202509011230"

    def test_consistency(self):
        from db import build_exclusion_key
        from datetime import datetime
        dt = datetime(2025, 9, 1, 12, 30)
        s = "2025-09-01 12:30:00"
        assert build_exclusion_key("P001", dt) == build_exclusion_key("P001", s)
