"""
ICU-05 Bundle 判定规则配置。
改这里影响感染性休克 Bundle 完成率（1h/3h/6h）的分子分母判定。
所有键必须显式列出，业务代码禁止硬编码。
"""

# 本模块可能先于 db.py 被 import，自行加载 .env（幂等；不覆盖已有环境变量）
import os
try:
    from pathlib import Path
    from dotenv import load_dotenv
    for _p in (Path(__file__).resolve().parent / ".env",
               Path(__file__).resolve().parent.parent / ".env",
               Path.cwd() / ".env"):
        if _p.exists():
            load_dotenv(_p)
            break
except Exception:
    pass

# ---- 引擎开关 ----
# compare 时新旧引擎并行出双份结果；auto 用新引擎；manual 用旧引擎
# 影响: get_bundle_data vs get_bundle_data_v2 走哪个
BUNDLE_ENGINE = "compare"

# ---- 医院变体开关（改 .env 的 BUNDLE_HOSPITAL_VARIANT，重启生效） ----
# "default" = 标准医院：读 SmartCare / DataCenter，标准提取
# "cg"     = 变体医院：读 SmartCare_cg / DataCenter_cg；
#            血气 / 痰培养 / 血培养按 DataCenter.VI_ICU_ZYYZ 医嘱名识别；
#            抗生素沿用系统 drugExe 关键词逻辑（不变）；
#            分母确诊时间取 patient.diagnosisHistoryList 中最早含
#            脓毒血症 / 败血症 / 感染性休克 的 time
# 影响: ICU-05 bundle 全链路（分母确诊时间、血气/培养识别、跨库路由）
BUNDLE_HOSPITAL_VARIANT = (os.getenv("BUNDLE_HOSPITAL_VARIANT", "default")
                           or "default").strip().lower()

# ---- cg 变体: VI_ICU_ZYYZ 医嘱名识别关键词 ----
# 影响: cg 变体下血气(A1)、痰培养(I3)、血培养(B2) 的识别口径
CG_ORDER_KEYWORDS = {
    "blood_gas": "ICU血气",        # 血气识别
    "sputum_culture": "细菌培养",   # 痰培养（I3 病原学送检）
    "blood_culture": "血培养鉴定",  # 血培养（B2）
}

# ---- cg 变体: 分母确诊诊断关键词 ----
# patient.diagnosisHistoryList[].diagnosis 包含其一 → 命中，取最早 time
# 影响: cg 变体分母的确诊时间（diagnosisTime）
CG_CONFIRM_DIAG_KEYWORDS = ("脓毒血症", "败血症", "感染性休克")


# ---- 分母锚点 ----
# t0 = 以 T0（第一条医嘱 orderTime）所在月份归属；diagnosis_time = 以诊断时间归属
# 影响: 分母归属月份，t0 更贴近临床实际
BUNDLE_DENOM_ANCHOR = "t0"

# ---- 感染证据门控 ----
# on = 必须有感染证据(I1/I2/I3任一)才进分母；off = 跳过感染证据判定
# 影响: off 会让任何用升压药的病人都算脓毒症
INFECTION_GATE = "on"

# ---- 第一步 A1 规则 ----
# value_present = 取到值即达标；value_below_threshold = 值低于阈值才算达标
# 影响: 抬高或降低第一步达标率
A1_RULE = "value_present"

# ---- 抗生素选取策略 ----
# latest_in_window = 窗口内倒序取第一条；first_in_window = 正序取第一条
# 影响: latest 系统性抬高第二步达标率
AB_PICK = "latest_in_window"

# ---- 液体范围 ----
# crystalloid_colloid_only = 只计晶体/胶体；all_drugs = 所有药物都计入
# 影响: all_drugs 会把溶媒计入，高估复苏量
FLUID_SCOPE = "crystalloid_colloid_only"

# ---- 休克确认规则 ----
# and = K1 AND K2 必须同时成立；or = K1 OR K2 任一成立
# 影响: 脓毒性休克确认的严格程度
SHOCK_RULE = "and"

# ---- 感染部位确认 ----
# True = 必须确认感染部位才进分母；False = 不要求
# 影响: 分母大小，True 会排除部位未确认的病例
SITE_REQUIRED = False

# ---- 6h 实现状态 ----
# True = 6h 已实现完整判定逻辑；False = 6h 仍返回 rule_pending
# 影响: ICU-05-6h 是否参与正式统计
BUNDLE_6H_IMPLEMENTED = True

# ---- 6h 路径 2 判定项 ----
# 6h 第二步包含的具体项目清单
# 影响: 6h 达标判定的完整性
BUNDLE_6H_STEP2_ITEMS = [
    "antibiotic",       # 抗菌药物执行
    "blood_culture",    # 血培养执行
    "fluid_1500",       # 液体量≥1500ml
    "lactate_recheck",  # 复测乳酸
]
