"""指标窗口与口径开关。改这里,不要改散落在 db.py 里的魔法数。"""

# ---- ICU-08 ARDS 俯卧位 ----
# P/F 阈值比较符。"lt" = 小于 150(现状代码);"lte" = 小于等于 150(现状前端文案)
ARDS_PF_OP = "lt"
# 分子:俯卧位记录是否必须晚于让该患者入组的那条血气时间
ARDS_PRONE_AFTER_PF = True
# 分母:PEEP 与氧疗途径 跟 血气 的配对回溯窗口(分钟)
ARDS_PAIR_LOOKBACK_MIN = 60
# 配对是否允许向后取值。False = 只向前回溯;True = 双向
ARDS_PAIR_BIDIRECTIONAL = False

# 开发期自检:True 时,取数窗口里出现 datetime.now() 直接抛异常
WINDOW_CLAMP_STRICT = True
