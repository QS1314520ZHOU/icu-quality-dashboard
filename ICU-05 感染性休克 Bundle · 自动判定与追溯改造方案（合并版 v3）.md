# ICU-05 感染性休克 Bundle · 自动判定与追溯改造方案（合并版 v3）

> 本文档合并三次需求，取代此前所有版本：
> · 基线：1h/3h Bundle 三步重排、脓毒症 4 项、脓毒症休克 2 项（改造版）
> · 叠加：分母入组、T0 锚点、6h Bundle 双路径、人工排除、未达标原因、详情可读性（最初版）
> · 追加：感染部位人工确认、SOFA / SOFA-2 自动评分与全链路追溯
>
> 全平台仅「感染部位确认」与「人工排除」两处需要人工操作，其余全部自动计算。

---

## 一、指标定义

| 指标 | 分子 | 分母 |
|---|---|---|
| ICU-05-1h | 1h 内完成 Bundle 的患者数 | 确诊脓毒性休克患者数 |
| ICU-05-3h | 3h 内完成 Bundle 的患者数 | 同上 |
| ICU-05-6h | 6h 内完成 Bundle 的患者数 | 同上 |

---

## 二、分母候选池

必须同时满足：

1. **入院 24 小时之内进入 ICU**
2. 入科类型 ∈ {入院、手术入院、外院}
3. 入科时间 = SmartCare `patient.icuAdmissionTime`
4. 统计期间内确诊脓毒性休克（见第五节）

派生字段：`icu_admit_time`、`icu_admit_type`、`admit_to_icu_hours`。
不满足第 1、2 条的病例不进候选池，但在详情中单列并注明落选原因。

---

## 三、T0 —— 怀疑脓毒症休克时间

**主锚点**：入科后 DataCenter `VI_ICU_ZYYZ` 中**第一条医嘱**的 `orderTime`。

多层兜底并留痕 `t0_source`：

| 层级 | t0_source | 取值 |
|---|---|---|
| L1 | `first_order` | 入科后第一条医嘱 `orderTime` |
| L2 | `icu_admission` | `icuAdmissionTime`（无医嘱记录时） |
| L3 | `manual` | 人工指定 |

⚠️ **已知偏差（必须在详情标注）**：`orderTime` 是医嘱**开立时间**，不是临床怀疑时刻，也不是首个异常指标出现时刻。用它当 T0 会让 Bundle 窗口起点偏晚 → 达标率偏高。
必须输出 `t0_delta_min`（T0 与首个异常指标时间之差）分布，超阈值标 `T0_SUSPECT`。

---

## 四、感染部位确认（唯一人工必填项）

| 项 | 说明 |
|---|---|
| 主部位 | 单选：肺部 / 腹腔 / 泌尿道 / 血流(导管相关) / 血流(非导管) / 皮肤软组织 / 中枢神经 / 骨与关节 / 手术切口 / 其他 / 不明确 |
| 次要部位 | 可多选，同上选项 |
| 系统推荐 | 基于诊断关键词 + 送检标本类型 + 影像报告自动推荐，人工一键采纳或改选 |
| 留痕 | 操作人、操作时间、系统推荐值、人工最终值、是否采纳推荐 |

- 未确认部位 → 病例进「待确认池」，**不进分子也不进分母**，大屏单列待确认数
- 选「不明确」视为已确认，但单独标记供复核
- 部位与送检标本类型不一致 → 提示，不阻断

---

## 五、脓毒症 / 脓毒性休克判定

### 5.1 【脓毒症】器官障碍（4 项全自动，任一成立）

| ID | 判定项 | code / 数据源 | 取值口径 | 阈值 |
|---|---|---|---|---|
| S1 | 氧合指数 | 血气 `param_bg_P/Fratio` | 时间范围内**最低值** | < 300 |
| S2 | GCS | 评分表 | 时间范围内**最低值** | < 13 |
| S3 | 平均动脉压 | 有创/无创**混合**后取最低 | 时间范围内**最低值** | < 70 mmHg |
| S4 | 血管活性药物 | 执行用药（有执行） | 药物配置 `classification == '血管活性'` | 存在即成立 |

- `器官障碍 = S1 || S2 || S3 || S4`
- **删除项**：qSOFA 评分、呼吸频率(RR)
- 每项支持自动判定 + 人工勾选/取消，人工操作留痕（操作人、时间、覆盖前的自动值）
- `param_bg_P/Fratio` 的 code 含斜杠，查询与正则需转义

### 5.2 脓毒症成立条件

```
脓毒症 = 器官障碍成立  AND  感染部位已人工确认
```

### 5.3 【脓毒性休克】（2 项全自动）

| ID | 判定项 | code / 数据源 | 阈值 |
|---|---|---|---|
| K1 | 动脉血乳酸 | 血气 `param_bg_Lac`（动脉血） | ≥ 2 mmol/L |
| K2 | 是否需要升压 | 执行用药（有执行），`classification == '血管活性'` | 存在即成立 |

- **`SHOCK_RULE = and`（强制）**：`脓毒性休克 = 脓毒症 && K1 && K2`
- ⚠️ K2 与 S4 判定条件完全相同。若配成 `or`，「用了血管活性药」会同时满足脓毒症与休克，构成循环论证，分母虚高
- 输出 `shock_confirmed`、`shock_basis[]`（每项取值 + 观测时间 + 来源记录 ID）

### 5.4 血管活性药物识别（S4 / K2 共用）

- 唯一判据：药物配置表 `classification == '血管活性'`，**禁止药名正则硬编码**
- 必须有**执行记录**（`statusFlag == '已执行'` 或等价），医嘱开立不算
- 结果缓存为 `vaso_drug_codes`，配置变更时失效重建

---

## 六、1h / 3h Bundle（三步，全自动）

窗口 `[T0, T0+1h]` / `[T0, T0+3h]`。

### 6.1 第一步 —— 乳酸测定

| 项 | 显示 | 判定 |
|---|---|---|
| A1 | `乳酸测定值：{value} mmol/L` + `□达标` | 窗口内取到动脉血 `param_bg_Lac` → 打钩 |

- 删除：「血气分析医嘱开立」、「乳酸≥2mmol/L」
- 取值：窗口内**最早一条**（反映多久测上首次乳酸），同时记录**最高值**供第三步 C2 用
- ⚠️ 待确认：达标 = 取到值即达标（当前实现），或取到值且 <阈值
- 缺失 → `null` + 显示「—」+ `DATA_MISSING_LAC`，**严禁当未达标**

### 6.2 第二步 —— 血培养与抗生素顺序

| 项 | 显示 | 数据源 |
|---|---|---|
| B1 | 抗菌药物 · 执行时间 | 执行用药的**开始时间**；抗生素由药物字典判定 |
| B2 | 血培养 · 执行时间 | 医嘱关键字【血培养】的 **`reviewTime`（审核时间）** |
| B3 | `□达标` | `B1 有值 && B2 有值 && B1 > B2` |

- 删除：抗菌药物「开立时间」、血培养「开立时间」
- 多条取值：**倒序取第一条（= 最晚一条）**；配置 `AB_PICK = latest_in_window`（默认）/ `first_in_window`
- **同时记录首剂时间 `antibiotic_first_time`**，详情两者并列；报表输出两种口径达标率差异
- ⚠️ 两处已知偏差，详情必须标注：
  - `latest_in_window` 会系统性抬高「抗生素晚于培养」的达标率
  - `reviewTime` 是审核时间而非标本采集时间，早于实际采血，同样偏向达标
- 超窗：窗口内无则向后取最早一条，**红色显示时间但不打钩**，原因码 `AB_LATE` / `BC_LATE`
- 完全无 → `null` + 「—」+ `AB_MISSING` / `BC_MISSING`
- 顺序不对（`B1 <= B2`）→ 不打钩 + `BC_AFTER_AB`

### 6.3 第三步 —— 触发条件与液体复苏

⚠️ **本步与 6h 第一步语义相反**：这里打钩表示「存在异常/触发」，不是达标。

| 项 | 显示 | 判定 | 适用 |
|---|---|---|---|
| C1 | `□ MAP<70mmHg` | 窗口内 MAP **最低值** < 70 → 打钩（触发） | 1h / 3h |
| C2 | `□ 血乳酸≥4 {value}` | 窗口内 Lac **最高值** ≥ 4 → 打钩，label 填具体值 | 1h / 3h |
| C3-1h | `□ 1h内有液体执行` | 开始执行时间在 `[T0, T0+1h]`，执行用药有药物执行 | 1h |
| C3-3h | `□ 液体量≥1500ml` | 开始执行时间在 `[T0, T0+3h]` 的药物用量累加 ≥1500ml | 3h |

- 删除：原第三步全部内容
- ⚠️ 液体量范围：配置 `FLUID_SCOPE = all_drugs | crystalloid_colloid_only`，**默认 `crystalloid_colloid_only`**。按「所有药物」会把抗生素溶媒和微量泵药物计入，显著高估复苏量
- MAP 需标注 `map_source = measured | computed`

### 6.4 完成判定（🔴 待确认，当前为建议实现）

```
第一步达标 = A1
第二步达标 = B3
第三步达标 = (C1 || C2) ? C3 : N/A → 视为达标
finish     = 第一步 && 第二步 && 第三步
```

同时记录 `finish_path = triggered | not_triggered`，区分「真复苏到位」与「根本没触发」。

---

## 七、6h Bundle（沿用最初版，本次不改造）

6h 是**复苏目标评估**，第一步为达标项语义，与 1h/3h 的触发项语义不同，不要混用代码。

### 路径 1 —— 第一步全达标

第一步三项在 6h 内全部达标 → 完成自动勾上：

| 项 | 达标条件 |
|---|---|
| MAP | > 70 mmHg |
| 液体量 | ≥ 1500 ml |
| 乳酸 | < 4 mmol/L |

### 路径 2 —— 第一步有任意项不达标 → 进第二步

第二步 4 点全部达标 → 完成自动勾上：

| # | 项 | 状态 |
|---|---|---|
| 1 | 抗菌药物执行 | 沿用 6.2 口径 |
| 2 | 血培养执行 | 沿用 6.2 口径 |
| 3 | 液体量 ≥1500ml | 沿用 |
| 4 | **待确认** | 暂定「复测乳酸」，需你确认 |

`BUNDLE_6H_STEP2_ITEMS` 可配置，默认 `['antibiotic','blood_culture','fluid_1500','lactate_recheck']`。
输出 `path = 1 | 2`，详情显示走了哪条路径。

---

## 八、SOFA / SOFA-2 自动评分

### 8.1 来源与移植形态

逻辑提取自 `critical-care-alert-platform`（branch `master`）：

| 源文件 | 用途 |
|---|---|
| `rulepacks/sofa_rulepack.py` | 经典 SOFA 1996 阈值表 |
| `rulepacks/sofa2_rulepack.py` | SOFA-2 2025 阈值表 |
| `calculators/sofa.py` / `sofa2.py` | 两版计算器 |
| `calculators/common.py` | 窗口过滤 / 取最差 / 陈旧判断 |
| `missing_policy.py` | 4 种缺失策略 |
| `organ_support.py` | 呼吸支持 / RRT / 升压药 / 镇静 / 谵妄模型 |
| `window_spec.py` | 时间窗契约 |
| `score_result.py` | 结果契约 |
| `docs/scoring/sofa-2-official-rule-extraction.md` | JAMA 2025 Table 2 全脚注 |

新建 `icu-quality-backend/scoring/`，分两层：
`sofa_rules.py`（阈值常量）/ `sofa_core.py` + `sofa2_core.py`（纯函数内核）/ `missing_policy.py` / `adapter.py`（取数适配）。

### 8.2 内核铁律（照搬，不得放宽）

1. 纯函数，相同输入必得相同输出
2. 内核**不访问数据库**，只接收已构建好的 observation 集合
3. 内核**不调用 `now()`**，`evaluation_time` 必须显式传入
4. **严禁使用 `observed_at` 晚于 `evaluation_time` 的数据**
5. 时间窗左开右闭 `(evaluation_time − lookback, evaluation_time]`
6. 时间窗判断用 `observed_at`，不用 `ingested_at`
7. 所有 datetime 必须 timezone-aware
8. 输出必须可解释：每分项含取值、单位、来源记录 ID、观测时间、缺失状态
9. 迟到数据只重算其 `observed_at` 所属时刻，不污染其他历史时点

### 8.3 经典 SOFA 1996 阈值

| 器官 | 指标 | 单位 | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|---|---|
| 呼吸 | PaO₂/FiO₂ | mmHg | ≥400 | 300–399 | 200–299 | 100–199 | <100 |
| 凝血 | 血小板 | 10⁹/L | ≥150 | 100–149 | 50–99 | 20–49 | <20 |
| 肝 | 总胆红素 | μmol/L | <20 | 20–32 | 33–101 | 102–203 | ≥204 |
| 循环 | 见 8.5 坑① | — | MAP≥70 | MAP<70 | 多巴胺≤5 或多巴酚丁胺任意 | 多巴胺>5 或 NE≤0.1 或 Epi≤0.1 | 多巴胺>15 或 NE>0.1 或 Epi>0.1 |
| 神经 | GCS | 分 | 15 | 13–14 | 10–12 | 6–9 | ≤5 |
| 肾·肌酐 | 肌酐 | μmol/L | <110 | 110–169 | 170–299 | 300–439 | ≥440 |
| 肾·尿量 | 尿量 | mL/24h | ≥500 | — | — | 200–499 | <200 |

`renal = max(肌酐档, 尿量档)`。尿量 ≥500 **不代表**肾脏分项为 0。
P/F 配对间隔 ≤30 分钟；FiO₂ 必须 0–1 小数；来源不明或估算值不得计算。
完整度 = 有值器官/6，<0.5 → `insufficient` 且 `total=None`。

### 8.4 SOFA-2 2025 阈值

| 器官 | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| Brain GCS | 15 | 13–14 | 9–12 | 6–8 | 3–5 |
| Respiratory P/F | >300 | ≤300 | ≤225 | ≤150 **且有高级支持** | ≤75 **且有高级支持** |
| Respiratory S/F（备用） | >300 | ≤300 | ≤250 | ≤200 且有支持 | ≤120 且有支持 |
| Hemostasis 血小板 10⁹/L | >150 | >100–150 | >80–100 | >50–80 | ≤50 |
| Liver 胆红素 mg/dL | ≤1.20 | >1.20–3.0 | >3.0–6.0 | >6.0–12.0 | >12.0 |
| Kidney 肌酐 mg/dL | ≤1.20 | >1.20–2.0 | >2.0–3.50 | >3.50 | 见 RRT |
| Kidney 尿量 mL/kg/h | — | <0.5 持续 6–12h | <0.5 持续 ≥12h | <0.3 持续 ≥24h 或无尿 ≥12h | — |
| Cardiovascular | MAP≥70 无升压药 | MAP<70 无升压药 | NE+Epi ≤0.2 或任一其他升压/正性肌力药 | NE+Epi >0.2–0.4 或 NE+Epi≤0.2 合用其他 | NE+Epi >0.4 或 NE+Epi 0.2–0.4 合用其他 或机械循环支持 |

附加规则：

- **恶化必须持续 >1h 才计分**
- **呼吸支持门控**：无高级支持时呼吸上限 2 分，除非资源不可用或治疗上限（需结构化理由）。高级支持 = HFNC/CPAP/BiPAP/NIV/IMV/家用呼吸机/ECMO
- **ECMO**：呼吸指征→呼吸 4；循环指征→呼吸 4 且循环 4；指征不明**不许猜**
- **S/F 路径**仅当 PaO₂ 缺失**且** SpO₂<98% 时可用；FiO₂ >1.0 自动 ÷100
- **Brain**：谵妄用药（实际给药，非医嘱）→ 至少 1 分即使 GCS 15；镇静者用镇静前 GCS；镇静前 GCS 未知→给 0 但打 `imputed` 标记。取值优先级：镇静前 GCS > 完整 GCS 评估 > GCS 观测 > Motor 替代（竖拇指0/定位痛1/躲避痛2/屈曲3/过伸或无反应4）> 仅谵妄用药=1
- **升压药盐型换算 → NE base**：base ×1.0；酒石酸氢盐一水 ×0.50；无水酒石酸氢盐 ×(1/1.89)；盐酸盐 ×(1/1.22)
- **连续输注 ≥60 分钟才计分**，bolus/抢救推注不计
- **单用多巴胺**：≤20→2，>20–40→3，>40→4
- **MAP 替代路径**（仅升压药不可用/治疗上限）：≥70→0，60–69→1，50–59→2，40–49→3，<40→4
- **Kidney** = `max(肌酐, 尿量, RRT)`；非肾脏指征 RRT（清毒素/清细胞因子）**不计 4 分**；间断透析非治疗日持续 4 分直至明确终止
- **RRT 准入 4 分**：`(肌酐>1.2 或 尿量<0.3 持续>6h) 且 (K≥6.0 或 (pH≤7.20 且 HCO3≤12))` 但因治疗上限/不可用/延迟未开始
- **Day 1** 可用入 ICU 前 <6h 检验，必须打来源标记
- **缺失策略四选一**：`official_day1_normal_imputation` / `strict_partial` / `complete_case` / `sequential_locf`。Day1 补 0 打 `imputed_normal_zero`；Day2+ 用 LOCF 且**不跨 ICU 住院段**

### 8.5 移植必修 7 项

| # | 问题 | 修正 |
|---|---|---|
| ① | 经典 SOFA 心血管用通用剂量梯度，丢了 MAP<70→1 与多巴胺/多巴酚丁胺分档，与 Vincent 1996 原文不符 | 按原文重写（见 8.3 表） |
| ② | 单位换算依赖 `unit` 字符串，`unit` 缺失时静默按 mg/dL 处理 | **强制单位白名单校验**，缺失或不在白名单一律拒绝出分并记数据质量问题，禁止默认兜底 |
| ③ | 呼吸分项 PaO₂ 取最低、FiO₂ 取最高再相除，会高估呼吸衰竭 | **优先取血气单条 `param_bg_P/Fratio` 最低值**，取不到再回退配对（保留 30min 约束） |
| ④ | 经典肌酐阈值 `(299,300)` 区间空档 | 改为闭合区间 |
| ⑤ | 取不到值时塞 `value_number=0` 假 Observation | 改为返回 missing component |
| ⑥ | SOFA-2 尿量第 1 分档为**死代码**（`hours` 恒为 24），且用 24h 平均速率代替持续时长判定 | 改为**按小时序列扫描连续低尿量时长**，还原 6–12h / ≥12h / ≥24h 三档 |
| ⑦ | RRT 准入条件变量名 `cr_or_uo_met` 但只算了肌酐，**漏了尿量<0.3 持续>6h** | 补齐尿量分支 |

### 8.6 评估时点与窗口裁剪

| 时点 | evaluation_time | 用途 |
|---|---|---|
| T0 SOFA | 确诊时刻 T0 | 支撑器官障碍判定 |
| T0+24h SOFA | T0 + 24h | 算 `sofa_delta`，看治疗反应 |
| 首日 SOFA | `icuAdmissionTime + 24h` | 与 APACHE II / SMR 口径对齐 |

⚠️ T0 SOFA 的窗口 `(T0−24h, T0]` 会跨到入 ICU 之前。
配置 `SOFA_WINDOW_CLAMP = icu_admission | full_24h`，**默认 `icu_admission`**（起点不早于 `icuAdmissionTime − 6h`），避免把急诊/病房数据算成 ICU 器官衰竭。

### 8.7 合规约束（硬性）

- 两个规则包 `clinical_approval_status = not_approved`，`lifecycle_status = experimental`
- `sofa_router.py` 在 `execution_mode="production"` 时直接拒绝执行；SOFA-2 另有 `is_sofa2_ready()` 门禁
- ⇒ **SOFA / SOFA-2 仅用于辅助展示与影子比对，不得作为任何质控指标分子/分母的判定依据**
- 展示必须带：评分版本号、rulepack 版本、`content_hash`、`result_status`、`completeness`、「实验性」标识
- `insufficient` 的评分**不得触发任何临床提示**，只能生成数据质量提示
- `partial` 评分展示时必须标注缺失项

### 8.8 影子比对（照搬那个项目的原则）

- 同患者同时刻，比对平台计算值 vs SmartCare `score` 表值
- 记录差值分布、一致率、方向性偏差、时间滞后
- 差异归因 7 类：数据缺失 / 单位不一致 / 时间窗不同 / 算法版本不同 / 取整差异 / 原始数据不同 / 厂商更新滞后
- **比对用于发现自身缺陷，不得因为对不上就直接改用 SmartCare 的值**

---

## 九、SOFA 详情与全链路追溯

### 9.1 三层展开

**第一层 · 总分卡**：SOFA 与 SOFA-2 总分并列 + 版本号 + rulepack 版本 + `content_hash` 前 8 位 + `result_status` + `completeness` + 「实验性·不用于质控判定」角标 + `evaluation_time`。

**第二层 · 6 个分项行**：分项名 / 得分 / 命中档位 / 原始值+单位 / 观测时间 / 距 evaluation_time 时长 / 状态标（正常·陈旧·缺失·补0·LOCF）。

**第三层 · 单分项追溯**，7 段必备：

| # | 内容 |
|---|---|
| 1 | **计算逻辑**：完整阈值表，高亮命中行，标注规则来源（`JAMA Table 2, p.8` / `Vincent 1996 Table 1, p.708`） |
| 2 | **取值口径**：lookback / max_staleness / aggregation / boundary / tie_breaker |
| 3 | **本次取值**：原始值+原始单位 → 换算规则（如 `μmol/L ÷ 88.4`）→ 标准值+标准单位 |
| 4 | **时间点**：`observed_at`（精确到秒）+ `evaluation_time` + 时间差 + 是否超陈旧度 |
| 5 | **来源追溯**：数据库 / 集合 / 记录 `_id` / 字段名，**可点击查看原始记录 JSON** |
| 6 | **候选记录清单**：窗口内**全部**候选记录按时间列出，**高亮被选中那条** —— 追溯核心，缺此说不清「为什么取这个值」 |
| 7 | **门控与旁路**：呼吸高级支持状态 / 循环连续输注时长与盐型换算 / 肾 RRT 指征 / Brain 镇静与谵妄旁路，各自命中与否 + 依据记录 ID |

### 9.2 缺失分项也必须可点开

显示：窗口内查了哪些 code、各 code 命中几条、为什么全部不可用（无记录 / 超陈旧度 / 单位不合法 / 值超范围），以及当前缺失策略下如何处理（补 0 打 `imputed_normal_zero` / LOCF 带源时间 / 保持缺失）。

### 9.3 Bundle 判定项同样要追溯

每个判定项（A1/B1/B2/B3/C1/C2/C3）点开显示：判定规则原文、窗口范围、窗口内全部候选记录、被选中记录与选取理由（如 `AB_PICK=latest_in_window`）、原始记录 ID、以及本项若未达标的原因码与人类可读解释。

---

## 十、三态强制规则

每个判定项取值只能是 `true` / `false` / `null`：

- `null` 走 `DATA_MISSING_*` 原因码，详情显示灰色「—」
- **`null` 严禁当 `false` 参与 finish 计算**
- 缺失率超阈值时详情页顶部横幅提示
- 分母为 0 时指标值显示 `null` 而非 0

---

## 十一、未达标原因码

`NO_T0` / `T0_SUSPECT` / `SITE_UNCONFIRMED` / `AB_LATE` / `AB_MISSING` / `BC_LATE` / `BC_MISSING` / `BC_AFTER_AB` / `FLUID_NONE` / `FLUID_INSUFFICIENT` / `MAP_NOT_MET` / `LAC_NOT_MET` / `LAC_NO_RECHECK` / `NO_VASO` / `DATA_MISSING_MAP` / `DATA_MISSING_LAC` / `DATA_MISSING_FLUID` / `MANUAL_EXCLUDED`

每个原因码必须配一句人类可读解释，详情列表逐例展示（多个用分号分隔），并在 summary 里出原因排行榜。

---

## 十二、人工排除

- `exclusion_key = "ICU-05:{diseaseId或pid}:{period}"`，**病例级**，不是指标级
- 原因枚举：`not_septic_shock` / `outside_treated` / `dnr` / `t0_wrong` / `data_error` / `other`
- 留痕：操作人、时间、原因码、自由文本
- 排除后该例从分子分母同时移除，详情中划线保留并显示排除原因，可恢复
- 排除数在指标卡与大屏单列，不得静默隐藏

---

## 十三、配置项汇总（零硬编码，全部进 `config/bundle_rules.py`）

| 配置 | 取值 | 默认 |
|---|---|---|
| `BUNDLE_ENGINE` | auto / manual / compare | compare |
| `BUNDLE_DENOM_ANCHOR` | diagnosis_time / t0 | t0 |
| `SHOCK_RULE` | and / or | **and（强制）** |
| `SITE_REQUIRED` | on / off | on |
| `AB_PICK` | latest_in_window / first_in_window | latest_in_window |
| `FLUID_SCOPE` | all_drugs / crystalloid_colloid_only | crystalloid_colloid_only |
| `BUNDLE_6H_STEP2_ITEMS` | list | antibiotic, blood_culture, fluid_1500, lactate_recheck |
| `SOFA_WINDOW_CLAMP` | icu_admission / full_24h | icu_admission |
| `SOFA_MISSING_POLICY` | 四选一 | strict_partial |
| `SOFA_VARIANTS` | classic / sofa2 / both | both |

---

## 十四、待对齐事项（🔴 = 阻塞）

- [ ] 🔴 1h/3h「完成」总判定规则（6.4 为建议实现）
- [ ] 🔴 6h 第二步第 4 点具体是什么（暂定复测乳酸）
- [ ] 第一步「达标」定义：取到值即达标 vs 取到值且 <阈值
- [ ] 集合名 `VI_ZYYZ` 与 `VI_ICU_ZYYZ` 是否同一个
- [ ] 血培养是否有比 `reviewTime` 更准的采集时间字段
- [ ] `AB_PICK` 默认 latest 是否接受（会抬高达标率）
- [ ] `FLUID_SCOPE` 液体累加范围
- [ ] MAP 是实测还是 SBP/DBP 计算
- [ ] 患者体重可用性（决定 SOFA-2 尿量路径能否走）
- [ ] 检验单位确认：胆红素、肌酐、血小板、乳酸
- [ ] `SOFA_WINDOW_CLAMP` 默认值确认
- [ ] 药物字典「抗生素」「血管活性」两个分类值的确切写法