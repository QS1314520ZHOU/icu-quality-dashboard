"""
SOFA / SOFA-2 阈值表与元数据。
来源:
  经典 SOFA 1996: Vincent JL, et al. Intensive Care Med. 1996;22:707-710.
  SOFA-2 2025: JAMA. 2025;334(23):2090-2103. DOI: 10.1001/jama.2025.20516.

两个 rulepack 恒为 clinical_approval_status=not_approved, lifecycle_status=experimental。
SOFA / SOFA-2 只能辅助展示与影子比对，不得作为任何质控指标分子分母的判定依据。
"""

# ============================================================
# 经典 SOFA 1996 阈值表
# ============================================================

CLASSIC_SOFA_THRESHOLDS = {
    "respiratory": {
        "display_name": "Respiratory (PaO2/FiO2)",
        "codes": ["param_PaO2", "PaO2", "param_FiO2", "FiO2", "param_bg_P/Fratio"],
        "lookback_hours": 24,
        "max_staleness_hours": 4,
        "aggregation": "worst",
        "range_guard": (0, 1000),  # #22: P/F 0-1000
        "thresholds": [
            {"low": 400, "high": 99999, "score": 0},
            {"low": 300, "high": 400, "score": 1},
            {"low": 200, "high": 300, "score": 2},
            {"low": 100, "high": 200, "score": 3},  # 需机械通气(第12条门控)
            {"low": 0,   "high": 100, "score": 4},  # 需机械通气(第12条门控)
        ],
        "source": "Vincent 1996 Table 1, p.708",
    },
    "coagulation": {
        "display_name": "Coagulation (Platelets)",
        "codes": ["PLT", "platelets"],
        "lookback_hours": 24,
        "max_staleness_hours": 12,
        "aggregation": "worst",
        "range_guard": (0, 3000),  # #22: PLT 0-3000
        "thresholds": [
            {"low": 150, "high": 99999, "score": 0},
            {"low": 100, "high": 150, "score": 1},
            {"low": 50,  "high": 100, "score": 2},
            {"low": 20,  "high": 50,  "score": 3},
            {"low": 0,   "high": 20,  "score": 4},
        ],
        "source": "Vincent 1996 Table 1, p.708",
    },
    "liver": {
        "display_name": "Liver (Bilirubin)",
        "codes": ["TBIL", "bilirubin"],
        "lookback_hours": 24,
        "max_staleness_hours": 12,
        "aggregation": "worst",
        "canonical_unit": "umol/l",
        "range_guard": (0, 2000),  # #22: 胆红素 0-2000 μmol/L
        "thresholds": [
            {"low": 0,    "high": 20,   "score": 0},
            {"low": 20,   "high": 33,   "score": 1},
            {"low": 33,   "high": 102,  "score": 2},
            {"low": 102,  "high": 204,  "score": 3},
            {"low": 204,  "high": 99999, "score": 4},
        ],
        "source": "Vincent 1996 Table 1, p.708",
    },
    "cardiovascular": {
        "display_name": "Cardiovascular (MAP & Vasopressors)",
        "codes": ["MAP", "mean_arterial_pressure"],
        "lookback_hours": 24,
        "max_staleness_hours": 1,
        "aggregation": "worst",
        "source": "Vincent 1996 Table 1, p.708",
        # 需求文档 7.3 第 1 条: 按 Vincent 1996 原文重写
        # 剂量梯度 + MAP<70→1 + 多巴胺分档
        "pressor_thresholds": [
            {"low": 0,    "high": 0,    "score": 0},
            {"low": 0.001, "high": 0.1,  "score": 1},
            {"low": 0.1,   "high": 0.2,  "score": 2},
            {"low": 0.2,   "high": 0.5,  "score": 3},
            {"low": 0.5,   "high": 999,  "score": 4},
        ],
        "dopamine_thresholds": [
            {"low": 0,    "high": 5,    "score": 2},
            {"low": 5,    "high": 15,   "score": 3},
            {"low": 15,   "high": 999,  "score": 4},
        ],
    },
    "central_nervous_system": {
        "display_name": "CNS (GCS)",
        "codes": ["param_score_gcs_obs", "gcsScore", "GCS"],
        "lookback_hours": 24,
        "max_staleness_hours": 8,
        "aggregation": "worst",
        "range_guard": (3, 15),  # #22: GCS 3-15
        "thresholds": [
            {"low": 15, "high": 16, "score": 0},
            {"low": 13, "high": 15, "score": 1},
            {"low": 10, "high": 13, "score": 2},
            {"low": 6,  "high": 10, "score": 3},
            {"low": 0,  "high": 6,  "score": 4},
        ],
        "source": "Vincent 1996 Table 1, p.708",
    },
    "renal": {
        "display_name": "Renal (Creatinine & Urine)",
        "codes_creatinine": ["CREA", "creatinine"],
        "codes_urine": ["urine_output", "urineVolume"],
        "lookback_hours": 24,
        "max_staleness_hours": 12,
        "aggregation": "worst",
        # 经典 SOFA 用 μmol/L
        "canonical_unit_creatinine": "umol/l",
        "canonical_unit_urine": "ml/24h",
        "range_guard_creatinine": (0, 3000),  # #22: 肌酐 0-3000 μmol/L
        "range_guard_urine": (0, 20000),  # #22: 尿量 0-20000 ml
        "creatinine_thresholds": [
            {"low": 0,    "high": 110,  "score": 0},
            {"low": 110,  "high": 170,  "score": 1},
            {"low": 170,  "high": 300,  "score": 2},
            {"low": 300,  "high": 440,  "score": 3},
            {"low": 440,  "high": 99999, "score": 4},
        ],
        "urine_thresholds": [
            {"low": 500,  "high": 999999, "score": 0},
            {"low": 200,  "high": 500,    "score": 3},
            {"low": 0,    "high": 200,    "score": 4},
        ],
        "source": "Vincent 1996 Table 1, p.708",
    },
}

# ============================================================
# SOFA-2 2025 阈值表
# ============================================================

SOFA2_THRESHOLDS = {
    "brain": {
        "display_name": "Brain (SOFA-2)",
        "codes": ["param_score_gcs_obs", "gcsScore", "GCS"],
        "lookback_hours": 24,
        "max_staleness_hours": 8,
        "aggregation": "worst",
        "thresholds": [
            {"low": 15, "high": 16, "score": 0},
            {"low": 13, "high": 15, "score": 1},
            {"low": 9,  "high": 13, "score": 2},
            {"low": 6,  "high": 9,  "score": 3},
            {"low": 3,  "high": 6,  "score": 4},
        ],
        "motor_fallback": {
            # M6=0, M5=1, M4=2, M3=3, M2/M1=4
            6: 0, 5: 1, 4: 2, 3: 3, 2: 4, 1: 4,
        },
        "source": "JAMA 2025 Table 2",
    },
    "respiratory": {
        "display_name": "Respiratory (SOFA-2)",
        "codes": ["param_PaO2", "PaO2", "param_FiO2", "FiO2", "param_bg_P/Fratio", "SpO2"],
        "lookback_hours": 24,
        "max_staleness_hours": 4,
        "aggregation": "worst",
        # SOFA-2 P/F ratio 阈值
        "pf_thresholds": [
            {"low": 300,  "high": 9999, "score": 0},
            {"low": 225,  "high": 300,  "score": 1},
            {"low": 150,  "high": 225,  "score": 2},
            {"low": 75,   "high": 150,  "score": 3},  # 需高级呼吸支持
            {"low": 0,    "high": 75,   "score": 4},  # 需高级呼吸支持
        ],
        # SpO2/FiO2 替代路径 (仅 SpO2 < 98%)
        "sf_thresholds": [
            {"low": 300,  "high": 9999, "score": 0},
            {"low": 250,  "high": 300,  "score": 1},
            {"low": 200,  "high": 250,  "score": 2},
            {"low": 120,  "high": 200,  "score": 3},
            {"low": 0,    "high": 120,  "score": 4},
        ],
        "source": "JAMA 2025 Table 2",
    },
    "hemostasis": {
        "display_name": "Hemostasis (SOFA-2)",
        "codes": ["PLT", "platelets"],
        "lookback_hours": 24,
        "max_staleness_hours": 12,
        "aggregation": "worst",
        "range_guard": (0, 3000),  # #22: PLT 0-3000
        "thresholds": [
            {"low": 150, "high": 9999, "score": 0},
            {"low": 100, "high": 150,  "score": 1},
            {"low": 80,  "high": 100,  "score": 2},
            {"low": 50,  "high": 80,   "score": 3},
            {"low": 0,   "high": 50,   "score": 4},
        ],
        "source": "JAMA 2025 Table 2",
    },
    "liver": {
        "display_name": "Liver (SOFA-2)",
        "codes": ["TBIL", "bilirubin"],
        "lookback_hours": 24,
        "max_staleness_hours": 12,
        "aggregation": "worst",
        # SOFA-2 用 mg/dL
        "canonical_unit": "mg/dl",
        "thresholds": [
            {"low": 0,    "high": 1.20,  "score": 0},
            {"low": 1.20, "high": 3.0,   "score": 1},
            {"low": 3.0,  "high": 6.0,   "score": 2},
            {"low": 6.0,  "high": 12.0,  "score": 3},
            {"low": 12.0, "high": 999,   "score": 4},
        ],
        "source": "JAMA 2025 Table 2",
    },
    "kidney": {
        "display_name": "Kidney (SOFA-2)",
        "codes_creatinine": ["CREA", "creatinine"],
        "codes_urine": ["urine_output", "urineVolume"],
        "lookback_hours": 24,
        "max_staleness_hours": 12,
        "aggregation": "worst",
        # SOFA-2 用 mg/dL
        "canonical_unit_creatinine": "mg/dl",
        "canonical_unit_urine": "ml/kg/h",
        "creatinine_thresholds": [
            {"low": 0,    "high": 1.20,  "score": 0},
            {"low": 1.20, "high": 2.0,   "score": 1},
            {"low": 2.0,  "high": 3.50,  "score": 2},
            {"low": 3.50, "high": 999,   "score": 3},
        ],
        "urine_thresholds_mlh": [
            # mL/kg/h, 按持续时间分档
            {"rate_lt": 0.3, "hours_ge": 24, "score": 3},
            {"rate_lt": 0.5, "hours_ge": 12, "score": 2},
            {"rate_lt": 0.5, "hours_ge": 6,  "score": 1},
            {"anuria_hours_ge": 12, "score": 3},
        ],
        "source": "JAMA 2025 Table 2",
    },
    "cardiovascular": {
        "display_name": "Cardiovascular (SOFA-2)",
        "codes": ["MAP", "mean_arterial_pressure"],
        "lookback_hours": 24,
        "max_staleness_hours": 1,
        "aggregation": "worst",
        "source": "JAMA 2025 Table 2",
        # SOFA-2 NE+Epi 剂量梯度
        "ne_epi_thresholds": [
            {"low": 0,    "high": 0,    "score": 0},
            {"low": 0.001, "high": 0.2,  "score": 2},
            {"low": 0.2,   "high": 0.4,  "score": 3},
            {"low": 0.4,   "high": 999,  "score": 4},
        ],
        # 多巴胺独立梯度
        "dopamine_thresholds": [
            {"low": 0,    "high": 20,   "score": 2},
            {"low": 20,   "high": 40,   "score": 3},
            {"low": 40,   "high": 999,  "score": 4},
        ],
        # MAP 无升压药路径
        "map_no_pressor": [
            {"low": 70, "high": 999, "score": 0},
            {"low": 0,  "high": 70,  "score": 1},
        ],
    },
}

# ============================================================
# 元数据
# ============================================================

CLASSIC_SOFA_META = {
    "rulepack_id": "classic-sofa-1996",
    "score_name": "SOFA",
    "score_variant": "classic_sofa_1996",
    "rulepack_version": "classic-sofa-1996.1",
    "reference_year": 1996,
    "authority": "Vincent JL et al., ESICM",
    "authority_reference": "Vincent JL, et al. Intensive Care Medicine, 1996;22:707-710",
    "clinical_approval_status": "not_approved",
    "lifecycle_status": "experimental",
}

SOFA2_META = {
    "rulepack_id": "sofa-2-2025",
    "score_name": "SOFA",
    "score_variant": "sofa_2_2025",
    "rulepack_version": "sofa-2-2025.1",
    "reference_year": 2025,
    "authority": "SOFA-2 Working Group (Ranzani et al.)",
    "authority_reference": "JAMA. 2025;334(23):2090-2103. DOI: 10.1001/jama.2025.20516",
    "clinical_approval_status": "not_approved",
    "lifecycle_status": "experimental",
}

# ============================================================
# 单位转换因子 — 三元组 key: (substance, from_unit, to_unit)
# ============================================================
_UNIT_CONVERSION = {
    # bilirubin: μmol/L → mg/dL (÷17.104)
    ("bilirubin", "umol/l", "mg/dl"): lambda v: v / 17.104,
    ("bilirubin", "μmol/l", "mg/dl"): lambda v: v / 17.104,
    ("bilirubin", "micromol/l", "mg/dl"): lambda v: v / 17.104,
    ("bilirubin", "微摩尔/升", "mg/dl"): lambda v: v / 17.104,
    # bilirubin: mg/dL → μmol/L (×17.104)
    ("bilirubin", "mg/dl", "umol/l"): lambda v: v * 17.104,
    # creatinine: μmol/L → mg/dL (÷88.4)
    ("creatinine", "umol/l", "mg/dl"): lambda v: v / 88.4,
    ("creatinine", "μmol/l", "mg/dl"): lambda v: v / 88.4,
    ("creatinine", "micromol/l", "mg/dl"): lambda v: v / 88.4,
    ("creatinine", "微摩尔/升", "mg/dl"): lambda v: v / 88.4,
    # creatinine: mg/dL → μmol/L (×88.4)
    ("creatinine", "mg/dl", "umol/l"): lambda v: v * 88.4,
}
