"""
SOFA评分真实数据库只读验证测试。

使用真实临床MongoDB进行只读测试，验证评分链端到端结构完整性。
不验证具体数值，只验证返回结构和类型正确性。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timedelta, timezone


# ============================================================
# 连接真实数据库
# ============================================================

def _get_db():
    """获取真实数据库连接"""
    from pymongo import MongoClient
    from config import mongodb

    uri = f"mongodb://{mongodb.MONGO_USER}:{mongodb.MONGO_PASS}@{mongodb.MONGO_HOST}:{mongodb.MONGO_PORT}/{mongodb.MONGO_DB}?authSource={mongodb.MONGO_AUTH_DB}"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[mongodb.MONGO_DB]
    # 验证连接
    client.admin.command("ping")
    return db, client


def _pick_random_patient(db, dept_codes=None):
    """从数据库中随机选取一个有入院记录的患者"""
    from config.hospital import DEPT_CODES
    if dept_codes is None:
        dept_codes = DEPT_CODES

    # 用最近的患者
    pipeline = [
        {"$match": {"admitDeptCode": {"$in": dept_codes}}},
        {"$group": {"_id": "$pid", "latest_admit": {"$max": "$admitTime"}}},
        {"$sort": {"latest_admit": -1}},
        {"$limit": 1},
    ]
    result = list(db["infoPatient"].aggregate(pipeline))
    if not result:
        pytest.skip("No patients found in database")

    pid = result[0]["_id"]

    # 获取sc_pid, mrn
    link = db["dcLink"].find_one({"pid": pid})
    if not link:
        pytest.skip(f"No dcLink found for pid={pid}")

    # 获取入院记录
    admission = db["sc_admissionRecord"].find_one(
        {"pid": link.get("sc_pid", "")},
        sort=[("admitTime", -1)]
    )
    if not admission:
        pytest.skip(f"No admission record for sc_pid={link.get('sc_pid')}")

    return {
        "pid": pid,
        "sc_pid": link.get("sc_pid", ""),
        "mrn": admission.get("mrn", ""),
        "dc_pid": admission.get("pid", ""),
        "admit_time": admission.get("admitTime"),
        "discharge_time": admission.get("dischargeTime"),
        "dept": admission.get("deptCode", ""),
    }


# ============================================================
# 测试: 数据适配器层
# ============================================================

class TestDataAdapterRealDB:
    """数据适配器真实数据库测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            self.db, self.client = _get_db()
        except Exception as e:
            pytest.skip(f"Cannot connect to MongoDB: {e}")

        self.patient = _pick_random_patient(self.db)
        yield
        self.client.close()

    def test_fetch_patient_obs_meds_structure(self):
        """验证 fetch_patient_obs_meds 返回正确结构"""
        from scoring.data_adapter import fetch_patient_obs_meds

        p = self.patient
        if not p["admit_time"]:
            pytest.skip("No admit time")

        t0 = p["admit_time"]
        if p["discharge_time"]:
            eval_time = min(t0 + timedelta(hours=24), p["discharge_time"])
        else:
            eval_time = t0 + timedelta(hours=24)

        result = fetch_patient_obs_meds(
            sc_pid=p["sc_pid"],
            mrn=p["mrn"],
            dc_pid=p["dc_pid"],
            t0=t0,
            eval_time=eval_time,
            weight_kg=None,
        )

        # 验证返回结构
        assert isinstance(result, dict)
        assert "observations" in result
        assert "medications" in result
        assert "has_advanced_support" in result
        assert "weight_kg" in result
        assert "has_vasopressor_wide" in result
        assert "data_quality_flags" in result
        assert "fetch_meta" in result

        # 验证类型
        assert isinstance(result["observations"], list)
        assert isinstance(result["medications"], list)
        assert isinstance(result["has_advanced_support"], bool)
        assert isinstance(result["has_vasopressor_wide"], bool)
        assert isinstance(result["data_quality_flags"], dict)
        assert isinstance(result["fetch_meta"], dict)

        # 验证观测数据结构
        for obs in result["observations"]:
            assert "code" in obs
            assert "observed_at" in obs
            # 至少有一个值字段
            assert "value_number" in obs or "value_text" in obs

        # 验证药物数据结构
        for med in result["medications"]:
            assert "med_name" in med
            assert "route" in med
            assert "dose_ugkgmin" in med


# ============================================================
# 测试: SOFA评分桥接层
# ============================================================

class TestSofaBridgeRealDB:
    """SOFA评分桥接层真实数据库测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            self.db, self.client = _get_db()
        except Exception as e:
            pytest.skip(f"Cannot connect to MongoDB: {e}")

        self.patient = _pick_random_patient(self.db)
        yield
        self.client.close()

    def test_compute_sofa_scores_structure(self):
        """验证 compute_sofa_scores 返回正确结构"""
        from scoring.sofa_bridge import compute_sofa_scores

        p = self.patient
        if not p["admit_time"]:
            pytest.skip("No admit time")

        t0 = p["admit_time"]
        if p["discharge_time"]:
            eval_time = min(t0 + timedelta(hours=24), p["discharge_time"])
        else:
            eval_time = t0 + timedelta(hours=24)

        result = compute_sofa_scores(
            sc_pid=p["sc_pid"],
            mrn=p["mrn"],
            dc_pid=p["dc_pid"],
            t0=t0,
            eval_time=eval_time,
            weight_kg=None,
        )

        # 验证顶层结构
        assert isinstance(result, dict)
        assert "classic" in result
        assert "sofa2" in result
        assert "eval_time" in result
        assert "t0" in result
        assert "fetch_meta" in result
        assert "data_quality_flags" in result
        assert "version_meta" in result

        # 验证版本元数据
        assert result["version_meta"]["classic"]["rulepack_id"] == "classic-sofa-1996"
        assert result["version_meta"]["sofa2"]["rulepack_id"] == "sofa-2-2025"

        # 验证classic评分结构
        classic = result["classic"]
        assert "sofa_score" in classic
        assert "components" in classic
        assert "result_status" in classic
        assert "missing_items" in classic

        if classic["sofa_score"] is not None:
            assert isinstance(classic["sofa_score"], (int, float))
            assert 0 <= classic["sofa_score"] <= 24
            assert isinstance(classic["components"], dict)
            expected_organs = {"respiration", "coagulation", "liver", "cardiovascular", "cns", "kidney"}
            assert expected_organs.issubset(set(classic["components"].keys()))

        # 验证sofa2评分结构
        sofa2 = result["sofa2"]
        assert "sofa2_score" in sofa2
        assert "components" in sofa2
        assert "result_status" in sofa2
        assert "completeness" in sofa2
        assert "missing_items" in sofa2

        if sofa2["sofa2_score"] is not None:
            assert isinstance(sofa2["sofa2_score"], (int, float))
            assert isinstance(sofa2["components"], dict)
            assert isinstance(sofa2["completeness"], (int, float))

    def test_build_clinical_layer_structure(self):
        """验证 build_clinical_layer 返回正确结构"""
        from scoring.sofa_bridge import compute_sofa_scores, build_clinical_layer

        p = self.patient
        if not p["admit_time"]:
            pytest.skip("No admit time")

        t0 = p["admit_time"]
        if p["discharge_time"]:
            eval_time = min(t0 + timedelta(hours=24), p["discharge_time"])
        else:
            eval_time = t0 + timedelta(hours=24)

        sofa_result = compute_sofa_scores(
            sc_pid=p["sc_pid"],
            mrn=p["mrn"],
            dc_pid=p["dc_pid"],
            t0=t0,
            eval_time=eval_time,
            weight_kg=None,
        )

        clinical = build_clinical_layer(
            sofa_result,
            infection_evidence={"has_infection": None, "i1": None, "i2": None, "i3": None},
        )

        # 验证5层结构
        assert isinstance(clinical, dict)
        assert "layer1_infection" in clinical
        assert "layer2_organ_dysfunction" in clinical
        assert "layer3_sepsis" in clinical
        assert "layer4_shock" in clinical
        assert "layer5_bundle" in clinical

        # 验证各层字段
        assert "has_infection" in clinical["layer1_infection"]
        assert "has_acute_organ_dysfunction" in clinical["layer2_organ_dysfunction"]
        assert "is_sepsis" in clinical["layer3_sepsis"]
        assert "shock_status" in clinical["layer4_shock"]


# ============================================================
# 测试: 端到端评分链
# ============================================================

class TestEndToEndRealDB:
    """端到端评分链真实数据库测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            self.db, self.client = _get_db()
        except Exception as e:
            pytest.skip(f"Cannot connect to MongoDB: {e}")

        self.patient = _pick_random_patient(self.db)
        yield
        self.client.close()

    def test_judge_bundle_v3_with_sofa(self):
        """验证 judge_bundle_v3_for_patient 包含SOFA评分结果"""
        from db import judge_bundle_v3_for_patient

        p = self.patient
        if not p["admit_time"]:
            pytest.skip("No admit time")

        t0 = p["admit_time"]
        if p["discharge_time"]:
            eval_time = min(t0 + timedelta(hours=24), p["discharge_time"])
        else:
            eval_time = t0 + timedelta(hours=24)

        result = judge_bundle_v3_for_patient(
            sc_pid=p["sc_pid"],
            mrn=p["mrn"],
            dc_pid=p["dc_pid"],
            t0=t0,
            eval_time=eval_time,
            dept_code=p["dept"],
            bed_no="1",
            has_culture_24h=False,
            has_adrenalin=False,
        )

        # 验证SOFA字段存在
        assert "sofa" in result, "judge_bundle_v3_for_patient should include 'sofa' field"
        assert "clinical_layer" in result, "judge_bundle_v3_for_patient should include 'clinical_layer' field"

        sofa = result["sofa"]
        assert "classic" in sofa
        assert "sofa2" in sofa
        assert "version_meta" in sofa

        clinical = result["clinical_layer"]
        assert "layer1_infection" in clinical
        assert "layer2_organ_dysfunction" in clinical
        assert "layer3_sepsis" in clinical
        assert "layer4_shock" in clinical
        assert "layer5_bundle" in clinical

        # 验证 gate_comparison 存在 (shadow模式)
        assert "gate_comparison" in result, "gate_comparison should exist in shadow mode"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
