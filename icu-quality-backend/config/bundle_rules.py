"""
ICU-05 Bundle 判定规则配置。
改这里影响感染性休克 Bundle 完成率（1h/3h/6h）的分子分母判定。
所有键必须显式列出，业务代码禁止硬编码。
"""

# ---- 引擎开关 ----
# compare 时新旧引擎并行出双份结果；auto 用新引擎；manual 用旧引擎
# 影响: get_bundle_data vs get_bundle_data_v2 走哪个
BUNDLE_ENGINE = "compare"

# ---- 分母锚点 ----
# t0 = 以 T0（第一条医嘱 orderTime）所在月份归属；diagnosis_time = 以诊断时间归属
# 影响: 分母归属月份，t0 更贴近临床实际
BUNDLE_DENOM_ANCHOR = "t0"

# ---- 休克判定 ----
# and = 低血压+升压药同时成立才算脓毒性休克；or = 任一即可
# ⚠️ 改 or 会导致循环论证，分母虚高
SHOCK_RULE = "and"

# ---- 感染证据门控 ----
# on = 必须有感染证据(I1/I2/I3任一)才进分母；off = 跳过感染证据判定
# 影响: off 会让任何用升压药的病人都算脓毒症
INFECTION_GATE = "on"

# ---- 感染部位是否必填 ----
# off = 不阻塞分母，未确认只标黄 + SITE_UNCONFIRMED 原因码
# ⚠️ on 时没人录部位分母会空掉，指标不可用
SITE_REQUIRED = "off"

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

# ---- 6h 路径 2 判定项 ----
# 6h 第二步包含的具体项目清单
# 影响: 6h 达标判定的完整性
BUNDLE_6H_STEP2_ITEMS = [
    "antibiotic",       # 抗菌药物执行
    "blood_culture",    # 血培养执行
    "fluid_1500",       # 液体量≥1500ml
    "lactate_recheck",  # 复测乳酸
]
