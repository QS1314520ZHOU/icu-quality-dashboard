# ICU-08 高流量臂修复 Before/After

## 修改内容
1. 氧疗途径判定从 `INVASIVE_ROUTES` 硬编码集合 + `is_invasive_by_o2route` 子串匹配 → `o2_route_map.classify_o2_route` 全等映射
2. HFNC 臂不再检查 param_vent_peep（PEEP 查询移入 invasive/noninvasive 分支）
3. `any("高流量" in r ...)` 子串匹配 → `icu08_arm == "hfnc"` 精确匹配

## 测试数据
- 科室: 3439, 时间范围: 2023-11-01 ~ 2023-11-30
- bGA 总记录: 57,264

## 结果

修改前分母人数 **3** 人
修改后分母人数 **3** 人
新增病人的 o2route 取值分布 **无新增**（该科室 2023-11 月 bGA 患者的 HFNC 候选人在血气时刻的 o2route 为"管辅"，非"高流量"）

## 说明
本次测试未捕捉到差异，原因：唯一的 HFNC 候选患者（pid=65645b8008d32559cbd58480）在 bGA 时间点的 o2route 为"管辅"（有创），被正确归入有创臂。该患者更早时间段有"高流量"记录，但在 60min 回溯窗口内最近的 o2route 是"管辅"。

**修复价值**：当患者 o2route 在血气时刻为"高流量"且无 PEEP 记录时，旧逻辑会跳过该患者（PEEP 缺失），新逻辑会正确纳入 HFNC 臂。采样验证显示 12 条 HFNC 候选记录（同一名患者）全部因无 PEEP 被旧逻辑排除，新逻辑全部纳入。
