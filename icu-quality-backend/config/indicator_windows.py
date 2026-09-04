"""
指标窗口与口径开关。改这里,不要改散落在 db.py 里的魔法数。
每个键上方注释: 改它影响哪个指标、往哪个方向变。
"""

# ---- ICU-08 ARDS 俯卧位 ----

# P/F 阈值比较符。"lt" = 小于 150(现状代码);"lte" = 小于等于 150(现状前端文案)
# 影响: ICU-08 分母，改 lte 会多纳入 P/F=150 的患者
ARDS_PF_OP = "lt"

# 分子:俯卧位记录是否必须晚于让该患者入组的那条血气时间
# 影响: ICU-08 分子，False 会允许俯卧位早于血气时刻
ARDS_PRONE_AFTER_PF = True

# 分母:PEEP 与氧疗途径 跟 血气 的配对回溯窗口(分钟)
# 影响: ICU-08 分母，窗口越大配对成功率越高
ARDS_PAIR_LOOKBACK_MIN = 60

# 配对是否允许向后取值。False = 只向前回溯;True = 双向
# 影响: ICU-08 分母，True 会多纳入血气后才记录的 PEEP
ARDS_PAIR_BIDIRECTIONAL = False

# ---- SOFA-2 呼吸支持 ----

# 人工气道(管辅/切辅)是否算高级呼吸支持。
# False = 不额外加分,靠 o2_route_map 映射;
# True  = 管辅/切辅直接判 IMV，呼吸分项升高
# 影响: SOFA/SOFA-2 呼吸分项，True 会让更多患者得 3/4 分
ARTIFICIAL_AIRWAY_AS_ADVANCED = False

# 经典 SOFA 是否把 HFNC 算高级支持。
# False = HFNC 不算高级支持(经典 SOFA 1996 原文口径)
# 影响: 经典 SOFA 呼吸分项，True 会让 HFNC 患者得 3/4 分
HFNC_AS_ADVANCED_CLASSIC = False

# SOFA-2 是否把 HFNC 算高级支持。
# True  = HFNC 算高级支持(SOFA-2 2025 口径)
# 影响: SOFA-2 呼吸分项，False 会让 HFNC 患者降为 2 分
HFNC_AS_ADVANCED_SOFA2 = True

# ---- SOFA-2 / ICU-08 呼吸支持回溯窗口 ----

# 呼吸支持(param_XiYangTuJing)回溯 hours。D2 实测 P50=2.1h,8h 覆盖98%
# 影响: SOFA/SOFA-2 呼吸分项 + ICU-08 分母，窗口越大配对成功率越高
RESP_LOOKBACK_H = 24

# 新鲜度门槛(minutes):距血气时间超过此值视为 stale
# 影响: o2route_staleness_grade 判定，超过此值为 acceptable
RESP_STALENESS_FRESH_MIN = 60

# 最大容忍 stale 小时数:超过此值直接判 missing
# 影响: 超过此值呼吸分项缺失，走 missing_policy
RESP_STALENESS_MAX_H = 8

# 呼吸支持与血气配对模式。"locf_8h"=8h内最近一次(LOCF);None=严格60min
# 影响: ICU-08 分母，locf_8h 会显著扩大分母
ICU08_PAIR_MODE = "locf_8h"

# ---- SOFA-2 升压药 ----

# 升压药剂量无法计算时的策略。"min_band_2"=视为>=0.1 ug/kg/min(最保守)
# 影响: SOFA 循环分项，reject 会让循环分项直接缺失
VASO_DOSE_UNKNOWN_POLICY = "min_band_2"

# 去甲肾上腺素标示量口径。
# "base" = 碱基(×1.0)(主任确认，换算系数 1.0，不除 2)
# "salt" = 盐(×0.5)
# "unknown" = 待药师确认(拒绝计算)
# 影响: SOFA 循环分项剂量计算，salt 会让所有 NE 剂量减半，循环分项低估
NE_LABEL_BASIS = "base"

# ---- ICU-05 感染性休克 ----

# 休克判定: "and"=低血压+升压药同时;"or"=任一即可
# ⚠️ 改 or 会导致循环论证，分母虚高
# 影响: ICU-05 分母
SHOCK_RULE = "and"

# 感染部位是否必填。
# False = 不阻塞分母，未确认只标黄 + SITE_UNCONFIRMED 原因码
# ⚠️ True 时没人录部位分母会空掉，指标不可用
# 影响: ICU-05 分母
SITE_REQUIRED = False

# ---- SOFA/SOFA-2 缺失策略 ----

# 缺失分项的处理。"strict_partial"=有缺失按已有分项算(0-14分);None=缺失判0分
# 影响: SOFA 总分，换 official 会给缺失项补 0
SOFA_MISSING_POLICY = "strict_partial"

# SOFA 变体。"both"=同时算 SOFA 和 SOFA-2;"sofa"=只算 SOFA;"sofa2"=只算 SOFA-2
# 影响: 是否同时跑两个版本
SOFA_VARIANTS = "both"

# SOFA 窗口钳制。"icu_admission"=以入科时间为起点;"full_24h"=取评估时刻前24h
# 影响: SOFA 取数窗口，full_24h 会吸入入 ICU 前的数据
SOFA_WINDOW_CLAMP = "icu_admission"

# ---- 评估频率 ----

# 评估频率模式。"person"=按患者(每人每天一次);None=按记录(每条记录)
# 影响: ICU-09/10 评估率，换 bed_day 后数值会明显下降
ASSESS_RATE_MODE = "person"

# 去重维度。"patient"=按患者去重;"admission"=按住院去重
# 影响: admission 会让同人多次住院分开计
DEDUP_BY = "patient"

# 有效评分规则。"valid_and_nonnull"=评分非null且非0
# 影响: 放宽会抬高评估率
VALID_SCORE_RULE = "valid_and_nonnull"

# 窗口自检:True 时,取数窗口里出现 datetime.now() 直接抛异常
# 影响: 开发期安全网
WINDOW_CLAMP_STRICT = True
