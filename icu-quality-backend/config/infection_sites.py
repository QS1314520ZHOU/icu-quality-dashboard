# -*- coding: utf-8 -*-
"""
感染部位取值表（11 项）。
前端下拉与后端校验共用同一份。
"""

# 部位取值表
INFECTION_SITES = {
    "lung": "肺部",
    "abdomen": "腹腔",
    "urinary": "泌尿道",
    "bloodstream_catheter": "血流（导管相关）",
    "bloodstream_non_catheter": "血流（非导管）",
    "skin_soft_tissue": "皮肤软组织",
    "cns": "中枢神经",
    "bone_joint": "骨与关节",
    "surgical_site": "手术切口",
    "other": "其他",
    "unknown": "不明确",
}

# 有效部位 code 集合
VALID_SITE_CODES = set(INFECTION_SITES.keys())

# evidence_type 取值
VALID_EVIDENCE_TYPES = {"diagnosis", "imaging", "microbiology", "clinical"}

# 自动建议关键词表
SITE_SUGGEST_KEYWORDS = {
    "lung": ["肺炎", "肺部感染", "支气管", "痰培养", "肺脓肿", "呼吸机相关肺炎", "VAP"],
    "abdomen": ["腹腔感染", "腹膜炎", "阑尾", "胆囊", "胆管炎", "胰腺", "肠穿孔", "腹腔引流"],
    "urinary": ["尿路感染", "泌尿系感染", "肾盂", "膀胱", "导尿管相关", "尿培养", "CAUTI"],
    "bloodstream_catheter": ["导管相关血流感染", "CRBSI", "中心静脉导管", "导管尖端培养"],
    "bloodstream_non_catheter": ["血流感染", "菌血症", "血培养阳性", "败血症"],
    "skin_soft_tissue": ["蜂窝织炎", "皮肤软组织", "压疮感染", "坏疽", "筋膜炎"],
    "cns": ["脑膜炎", "脑脓肿", "颅内感染", "脑室炎", "脑脊液培养"],
    "bone_joint": ["骨髓炎", "关节感染", "化脓性关节炎"],
    "surgical_site": ["手术切口感染", "切口愈合不良", "SSI", "术后感染"],
}


def validate_site_code(code: str) -> bool:
    """校验部位 code 是否在 11 项内。"""
    return code in VALID_SITE_CODES


def validate_evidence_type(et: str) -> bool:
    """校验 evidence_type 是否在四个取值内。"""
    return et in VALID_EVIDENCE_TYPES


def get_site_label(code: str) -> str:
    """获取部位中文标签。"""
    return INFECTION_SITES.get(code, code)


def get_site_options() -> list:
    """返回部位选项列表（供前端下拉）。"""
    return [{"code": k, "label": v} for k, v in INFECTION_SITES.items()]
