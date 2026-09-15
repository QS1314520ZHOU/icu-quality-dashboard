# ICU-05 脓毒症休克 Bundle 完成率 — 指标计算说明

> 版本: v3 (active 模式)
> 更新日期: 2026-09-15
> 对应代码: `scoring/bundle_engine.py`, `db.py:judge_bundle_v3_for_patient()`, `config/indicator_windows.py`

---

## 一、指标概述

| 项目 | 说明 |
|------|------|
| 指标编号 | ICU-05 |
| 指标名称 | 脓毒症休克 1h/3h/6h Bundle 完成率 |
| 定义 | 符合脓毒症休克定义的 ICU 患者中，在规定时间内完成 Bundle 三步的比例 |
| **分母** | 满足脓毒症休克条件的 ICU 患者人次 (S1-S4 任一 + I1-I3 任一 + K1∧K2) |
| **分子** | 分母中 Bundle 1h/3h/6h 各自完成的患者人次 |
| 计算公式 | 分子 / 分母 × 100% |
| 数据源 | SmartCare MongoDB (`bedside`, `bGATemp`, `drugExe`, `score`, `diseaseDiagnosis`) + DataCenter (`VI_ICU_ZYYZ`, `VI_ICU_EXAM_ITEM`) |
| 评估周期 | 月度 |
| **重要** | 1h/3h/6h 是三个独立的时间窗口，各自独立判定，互不影响 |

---

## 二、核心概念

### 2.1 T0 (时间零点)

T0 是 Bundle 计时的起点，定义为 **患者首次满足脓毒症休克条件的时刻**。

T0 的确定方式：
1. 查询患者所有候选感染性休克记录 (`infectionShockV2`)
2. 选取 `createdTime` 最早的一条
3. 其 `createdTime` 即为 T0

若无候选记录，则该患者不进入分母。

### 2.2 三态逻辑 (True / False / None)

判定项返回三种状态：
- **True**: 条件确认成立
- **False**: 条件确认不成立 (有数据但不满足)
- **None**: 数据缺失或查询异常，无法判定

**关键原则**: None ≠ False。缺失数据不得回退为 0 或空值。

### 2.3 时间窗口

| 窗口 | 范围 | 用途 |
|------|------|------|
| 门控窗口 | T0-24h ~ T0+6h | S1-S4, K1-K2 判定 |
| 1h Bundle | T0 ~ T0+1h | 1h 完成率 |
| 3h Bundle | T0 ~ T0+3h | 3h 完成率 |
| 6h Bundle | T0 ~ T0+6h | 6h 完成率 |

---

## 三、分母判定 — 脓毒症休克确认

分母 = 满足 **器官障碍** AND **感染证据** AND **休克确认** 的患者。

### 3.1 器官障碍 (S1-S4 任一成立)

| 判定项 | 条件 | 数据源 | 字段 |
|--------|------|--------|------|
| **S1** | P/F ratio < 300 | bGATemp | `bedsides.code=param_bg_P/Fratio`, 取窗口内最低值 |
| **S2** | GCS < 13 | score / bedside | 优先 `score(scoreType='gcsScore').total`; 兜底 `bedside(param_score_gcs_obs)` 编码解析 (E?V?M? → E+V+M) |
| **S3** | MAP < 70 mmHg | bedside | `param_ibp_m`(有创) + `param_nibp_m`(无创), 取窗口内最低值 |
| **S4** | 存在升压药使用 | drugExe | T0-24h ~ T0+6h 内有升压药执行记录 (详见第四节) |

**门控逻辑**: S1 OR S2 OR S3 OR S4 → `has_organ_dysfunction = True`

### 3.2 感染证据 (I1-I3 任一成立)

| 判定项 | 条件 | 数据源 | 匹配规则 |
|--------|------|--------|----------|
| **I1** | 诊断含感染关键词 | diseaseDiagnosis | 关键词: 脓毒/败血/感染性休克/感染/肺炎/腹膜炎/脑膜炎/蜂窝织炎/脓肿/化脓/尿路感染/胆管炎 等 |
| **I2** | T0~T0+6h 有抗感染药物执行 | drugExe | 抗生素关键词匹配 (头孢/培南/青霉/万古/左氧/莫西/甲硝唑/利奈等), 排除非抗生素药物 |
| **I3** | T0 后有病原学送检 | DC:VI_ICU_ZYYZ | `orderName` 匹配: 血培养/痰培养/尿培养/细菌培养/真菌培养/分泌物培养等 |

**门控逻辑**: I1 OR I2 OR I3 → `has_infection = True`  
**注意**: 可通过 `INFECTION_GATE=off` 配置跳过感染证据门控

### 3.3 休克确认 (K1 AND K2)

| 判定项 | 条件 | 数据源 | 阈值 |
|--------|------|--------|------|
| **K1** | 血乳酸 ≥ 2 mmol/L | bGATemp | `bedsides.code=param_bg_Lac`, 取 T0-2h ~ T0+1h 内最近值 |
| **K2** | 需要升压治疗 | drugExe | T0-24h ~ T0+6h 内有升压药执行 (同 S4) |

**门控逻辑**: K1 AND K2 → `is_septic_shock = True`  
**配置**: 可通过 `SHOCK_RULE=or` 改为 K1 OR K2 (不推荐, 会导致循环论证)

### 3.4 分母汇总

```
分母患者 = {
  is_septic_shock == True
  AND has_organ_dysfunction == True
  AND has_infection == True
}
```

---

## 四、升压药识别规则 (K2 / S4)

升压药识别采用 **三层匹配机制**:

### 4.1 第一层: VASO_WIDE (全等匹配)

- **数据源**: `configDrug` 表 `classification='血管活性'` 的药物
- **注入时机**: 服务启动时 `_inject_vaso_wide_labels()` 从 MongoDB 读取
- **匹配方式**: 药名全等 (忽略大小写)
- **特点**: 精确匹配, 覆盖医院字典中所有标记为血管活性的药物

**当前 configDrug 血管活性药清单 (29个):**

| 代码 | 药名 | 备注 |
|------|------|------|
| X025 | 去甲肾上腺素注射液 | 核心升压药 |
| X1043 | 肾上腺素注射液 | 核心升压药 |
| X3162 | 多巴胺注射液 | 核心升压药 |
| X3825 | 多巴酚丁胺注射液 | 核心升压药 |
| X2557 | 间羟胺注射液 | 核心升压药 |
| X3909 | 间羟胺注射液 (小规格) | 核心升压药 |
| X2934 | 垂体后叶注射液 | 核心升压药 |
| X2563 | 多巴酚丁胺注射液 (大规格) | 核心升压药 |
| X4091 | 多巴胺注射液 (大规格) | 核心升压药 |
| 10035728 | 特利加压素粉针 | 核心升压药 |
| X2607 | 去乙酰毛花苷 (西地兰) | 非升压药 (强心苷) |
| X2999 | 硝酸甘油片 | 扩血管 |
| X3986 | 硝酸甘油注射液 | 扩血管 |
| X1861 | 硝酸甘油注射液 (大规格) | 扩血管 |
| X2081 | 硝普钠粉针 | 扩血管 |
| X3634 | 尼卡地平注射液 | 降压 |
| 10036788 | 乌拉地尔注射液 | 降压 |
| X1092 | 异丙肾上腺素注射液 | 核心升压药 |
| X3332 | 盐酸胺碘酮注射液 | 抗心律失常 (非升压) |
| X3359 | 胺碘酮片 | 抗心律失常 (非升压) |
| X2363 | 浓氯化钠注射液 | 电解质 (误分类) |
| X3282 | 氯化钾注射液 | 电解质 (误分类) |
| 2363 | 浓氯化钠注射液 | 电解质 (误分类) |
| X3223 | 氯化钾颗粒 | 电解质 (误分类) |
| 48 | 胺碘酮针/注射液 | 抗心律失常 (非升压) |
| X2291 | 胺碘酮片 | 抗心律失常 (非升压) |
| 10033999 | 氯化钾缓释片 | 电解质 (误分类) |
| X3162 | 多巴胺注射液 | 核心升压药 |

**注意**: configDrug 中有误分类的药物 (浓氯化钠、氯化钾、胺碘酮等), 但由于 VASO_WIDE 采用全等匹配, 不影响 canon_drug 的判断。

### 4.2 第二层: canon_drug (模糊规范化匹配)

- **实现**: `scoring/adapter.py:canon_drug()`
- **匹配方式**: 药名中包含关键词即命中 (子串匹配)
- **特点**: 覆盖各种别名/商品名/剂量差异

**canon_drug 关键词清单 (按优先级排序):**

| 关键词 | 规范名 | 药物类别 |
|--------|--------|----------|
| 去甲肾上腺素 | norepinephrine | α-肾上腺素能激动剂 |
| noradrenaline | norepinephrine | 英文别名 |
| 异丙肾上腺素 | isoproterenol | β-肾上腺素能激动剂 |
| 苯肾上腺素 | phenylephrine | α-肾上腺素能激动剂 |
| 去氧肾上腺素 | phenylephrine | 中文别名 |
| 多巴酚丁胺 | dobutamine | β1-肾上腺素能激动剂 |
| 多巴胺 | dopamine | 多巴胺能激动剂 |
| 血管加压素 | vasopressin | V1受体激动剂 |
| **垂体后叶** | vasopressin | 中文别名 (垂体后叶素) |
| **垂体后叶素** | vasopressin | 中文别名 |
| 特利加压素 | terlipressin | V1受体激动剂 |
| **间羟胺** | metaraminol | α-肾上腺素能激动剂 |
| **阿拉明** | metaraminol | 商品名 |
| 米力农 | milrinone | 磷酸二酯酶抑制剂 |
| **左西孟旦** | levosimendan | 钙增敏剂 |
| 肾上腺素 | epinephrine | α+β-肾上腺素能激动剂 |
| adrenaline | epinephrine | 英文别名 |

### 4.3 第三层: VASO_STRICT (精确集合校验)

- **实现**: `scoring/bundle_engine.py:VASO_STRICT_LABELS`
- **匹配方式**: 精确集合匹配
- **用途**: 与 canon_drug 互补, 作为兜底校验

### 4.4 匹配流程

```
drugExe.drugList[].name
  ├─ in_wide = name_lower in VASO_WIDE_LABELS   (全等)
  ├─ in_strict = canon_drug(name) is not None     (模糊)
  └─ if in_wide or in_strict: → 升压药命中 ✓
```

### 4.5 drugExe 数据结构

```json
{
  "pid": "患者SmartCare ID",
  "startTime": "执行开始时间 (datetime)",
  "drugList": [
    {
      "name": "●*去甲肾上腺素注射液16.000mg",
      "code": "X025",
      "dose": 16.0,
      "unit": "mg",
      "liquidAmount": 16.0
    }
  ],
  "drugActionList": [
    {
      "time": "操作时间",
      "action": "stop/pause/cancel",
      "type": "停止/暂停/取消"
    }
  ]
}
```

**关键字段说明**:
- `drugList[].name`: 药名含剂量 (如 `*去甲肾上腺素注射液16.000mg`), canon_drug 通过子串匹配忽略剂量部分
- `startTime`: 药物执行开始时间, datetime 类型 (非字符串)
- `drugActionList`: 停药记录, 用于判断 T0 前开始的用药是否仍在使用

### 4.6 K2/S4 判定逻辑 (db.py:2454-2512)

```
查询范围: T0-24h ~ T0+6h 内的 drugExe 记录
遍历每条记录的 drugList:
  对每个药物名调用 _classify_vasopressor(name):
    → in_wide: VASO_WIDE_LABELS 全等匹配
    → in_strict: canon_drug() 模糊匹配
    → if in_wide or in_strict: 命中升压药

  若 T0 前开始用药 (is_prestarter=True):
    → 检查 drugActionList 是否有停止/暂停/取消记录
    → 无动作记录: status="unknown" (不判定为活跃)
    → 无停止记录: status="active" ✓
  
  若 T0 后开始用药:
    → 直接 status="active" ✓
```

---

## 五、分子判定 — Bundle 三步完成

### 5.1 第一步: A1 (乳酸测定)

| 窗口 | 条件 | 数据源 |
|------|------|--------|
| 1h/3h/6h | T0~T0+Nh 内有乳酸测定记录 | bGATemp `param_bg_Lac` |

- 默认规则 `A1_RULE=value_present`: 有值即达标
- 备选规则 `A1_RULE=value_below_threshold`: 值 < 2 mmol/L 才达标

### 5.2 第二步: B1 + B2 + B3 (抗生素 + 血培养)

| 判定项 | 条件 | 数据源 |
|--------|------|--------|
| **B1** | T0~T0+Nh 内有抗菌药物执行 | drugExe (抗生素关键词匹配) |
| **B2** | T0~T0+Nh 内有血培养送检 | DC:VI_ICU_ZYYZ (`orderName` 含"血培养") |
| **B3** | B1 AND B2 AND 抗生素时间 > 血培养时间 | 时间比较 |

**B3 达标条件**: 抗生素执行时间 **晚于** 血培养送检时间 (确保先采血培养再给抗生素)

**B3 原因码**:
- `AB_MISSING`: 抗生素缺失
- `BC_MISSING`: 血培养缺失
- `BC_AFTER_AB`: 抗生素早于血培养 (不达标)

### 5.3 第三步: C1 + C2 + C3 (MAP/乳酸触发 + 液体)

| 判定项 | 条件 | 说明 |
|--------|------|------|
| **C1** | MAP < 70 mmHg | 触发项: 是否需要液体复苏 |
| **C2** | 乳酸 ≥ 4 mmol/L | 触发项: 是否需要液体复苏 |
| **C3** | 液体量达标 | 1h: 有液体执行即可; 3h: ≥1500ml; 6h: ≥1500ml |

**第三步逻辑**:
```
if C1 triggered OR C2 triggered:
    step3 = C3 (液体必须达标)
else:
    step3 = True (未触发视为达标)
```

**重要**: C1/C2 是触发条件，只有当 MAP<70 或 乳酸≥4 时才要求液体达标。如果 C1 和 C2 都是 None（数据缺失），则 step3 = None（无法判定）。

### 5.4 完成判定

```
finish = (step1 == True) AND (step2 == True) AND (step3 == True)
```

| step | 含义 | 不达标原因码 |
|------|------|-------------|
| step1 | 第一步 (A1 乳酸测定) | A1_NOT_MET |
| step2 | 第二步 (B3 抗生素+血培养) | AB_MISSING / BC_MISSING / BC_AFTER_AB |
| step3 | 第三步 (C3 液体) | FLUID_INSUFFICIENT / MAP_NOT_MET |

**finish 返回值说明**:
- `True`: 三步全部达标
- `False`: 有任一步明确不达标
- `None`: 有数据缺失，无法判定（不等于 False）

### 5.5 三个窗口的 Bundle 完成（独立判定）

**关键原则**: 1h/3h/6h 是三个独立的时间窗口，各自独立判定，互不影响。
- 1h 完成不影响 3h/6h 的判定
- 3h 完成不影响 6h 的判定
- 6h 不要求 3h 先完成

| 窗口 | 液体阈值 | 复测乳酸 | 特殊说明 |
|------|----------|----------|----------|
| 1h | 有液体执行即可（不要求1500ml） | 不要求 | 最严格时间窗口 |
| 3h | ≥ 1500 ml | 不要求 | — |
| 6h | ≥ 1500 ml | 要求 T0+1h 后有复测乳酸 | 缺复测乳酸则 finish=None（即使其他步骤达标） |

**6h Bundle 特殊规则**:
```python
# 6h 完成判定
result_6h = judge_bundle_finish_v3(a1_6h, b3_6h, c1_6h, c2_6h, c3_6h)
# 6h 特有: 复测乳酸是额外要求
if result_6h.get("finish") is True and not has_lactate_recheck:
    result_6h["finish"] = None  # 缺失复测乳酸，无法判定
    result_6h["reasons"].append("LACTATE_RECHECK_MISSING")
```

---

## 六、SOFA / SOFA-2 集成

### 6.1 SOFA 评分用于分母门控 (SOFA_GATE_MODE)

| 模式 | 说明 |
|------|------|
| `shadow` | 新旧门控并行计算, 输出对比, 不影响正式报表 |
| `active` | 使用 SOFA-2 ≥ 2 作为正式分母判定依据 |

### 6.2 SOFA 分项数据源

| 分项 | 数据源 | 关键字段 |
|------|--------|----------|
| 呼吸 | bGATemp + bedside | P/F ratio + O2 路径 |
| 凝血 | VI_ICU_EXAM_ITEM | PLT (×10⁹/L) |
| 肝脏 | VI_ICU_EXAM_ITEM | TBIL (μmol/L) |
| 循环 | bedside + drugExe | MAP + 升压药剂量 |
| 神经 | bedside + score | GCS |
| 肾脏 | VI_ICU_EXAM_ITEM | sCr (μmol/L, SOFA-2需÷88.4) |

### 6.3 升压药剂量换算

- **唯一换算点**: `scoring/adapter.py:ne_ugkgmin()`
- **标示量口径**: `NE_LABEL_BASIS=base` (碱基, 换算系数 1.0)
- **未知剂量策略**: `VASO_DOSE_UNKNOWN_POLICY=min_band_2` (视为 ≥ 0.1 ug/kg/min)

---

## 七、配置开关一览 (config/indicator_windows.py)

| 开关 | 默认值 | 影响 | 说明 |
|------|--------|------|------|
| `SHOCK_RULE` | `"and"` | ICU-05 分母 | K1∧K2 (and) 或 K1∨K2 (or) |
| `SITE_REQUIRED` | `False` | ICU-05 分母 | 感染部位是否必填 |
| `INFECTION_GATE` | — | ICU-05 分母 | `off` 跳过感染证据门控 |
| `A1_RULE` | `"value_present"` | ICU-05 分子 | 乳酸测定达标规则 |
| `SOFA_GATE_MODE` | `"shadow"` | ICU-05 分母 | SOFA-2 门控模式 |
| `NE_LABEL_BASIS` | `"base"` | SOFA 循环分项 | NE 标示量口径 |
| `VASO_DOSE_UNKNOWN_POLICY` | `"min_band_2"` | SOFA 循环分项 | 未知剂量策略 |
| `SOFA_VARIANTS` | `"both"` | SOFA 输出 | 同时算 SOFA 和 SOFA-2 |
| `SOFA_MISSING_POLICY` | `"strict_partial"` | SOFA 总分 | 缺失分项策略 |
| `REQUIRED_INDICATORS` | 20个指标 | 月度完整性检查 | 按指标维度检查缺失 |

---

## 八、已知数据质量问题

| 问题 | 影响 | 当前处理 |
|------|------|----------|
| configDrug 误分类 (浓氯化钠/氯化钾/胺碘酮标为血管活性) | VASO_WIDE_LABELS 含非升压药 | 全等匹配, 不影响 canon_drug |
| drugExe 药名含剂量 (如 `*去甲肾上腺素注射液16.000mg`) | VASO_WIDE 全等匹配失败 | canon_drug 子串匹配兜底 |
| drugExe 药名格式不统一 (有/无前缀符号 `●*▲◆`) | VASO_WIDE 全等匹配失败 | canon_drug 子串匹配兜底 |
| drugExe 药名含配伍 (如 `去甲肾上腺素16mg+5%GS42ml`) | canon_drug 仍可命中 (子串匹配) | 无影响 |
| drugExe 药名为组名 (如 `去甲肾上腺素组`, `多巴胺组`) | canon_drug 子串匹配可命中 | 无影响 |
| patient 体重缺失 (仅19.6%有值) | SOFA 循环分项剂量计算 | 使用估算或缺失策略 |
| bGATemp 时间字段嵌套在 bedsides 数组内 | 查询需 $elemMatch | 已处理 |
| 旧格式汇总记录（无indicator字段） | 视为缺失，需要重算 | 自动迁移到新格式 |

---

## 九、每日重算机制

### 9.1 重算策略

| 场景 | 策略 | 说明 |
|------|------|------|
| 启动时检查 | 历史月份补缺失 + 当前月强制重算 | 确保当前月数据最新 |
| 每日凌晨2点 | 历史月份补缺失 + 当前月强制重算 | `rebuild_recent(months=13)` |
| 命令中心触发 | 缺失月份 + 当前月（如在查询范围） | `auto_fix_missing` |

**关键逻辑**:
```python
# rebuild_recent() 核心逻辑
historical_periods = periods[:-1]  # 历史月份
current_period = periods[-1]       # 当前自然月

# 历史月份只补缺失
missing_historical = find_missing_periods(dept_codes, historical_periods)

# 当前月始终加入重算列表（不检查是否已有数据）
periods_to_rebuild = list(dict.fromkeys(missing_historical + [current_period]))
```

### 9.2 分布式锁机制

所有重算入口都使用分布式锁防止多实例重复执行：

| 锁名称 | 用途 | 超时时间 |
|--------|------|----------|
| `daily_rebuild` | 每日凌晨任务 | 1小时 |
| `startup_rebuild` | 启动时完整性检查 | 1小时 |
| `auto_fix_missing` | 命令中心自动修复 | 1小时 |

**锁实现要点**:
- 使用 MongoDB `update_one + upsert` 原子操作
- 每个实例生成唯一 `owner_token` (UUID)
- 只有锁的持有者（匹配 owner_token）才能释放锁
- 心跳机制 (`heartbeat_at`) 用于检测僵尸任务
- 僵尸任务：30分钟无心跳的 running 任务会被标记为 `interrupted`

**task_id 生成**:
- 使用 `uuid.uuid4().hex` 保证全局唯一
- 长度32位，已建立唯一索引

### 9.3 find_missing_periods 检查逻辑

按指标维度检查完整性，不跳过任何缺失：

```python
def find_missing_periods(dept_codes, periods):
    # 获取所有已存在记录的 (period, indicator) 组合
    existing_docs = coll.find(...)

    for period in periods:
        if period not in existing_indicators:
            # 完全无记录 → 缺失
            missing.append(period)
        elif period in has_old_format:
            # 有旧格式记录（无indicator字段）→ 需要重算迁移
            missing.append(period)
        else:
            # 有新格式记录，检查是否所有必需指标都有
            if len(indicators) < len(REQUIRED_INDICATORS):
                missing.append(period)
```

**必需指标列表** (`REQUIRED_INDICATORS`):
```
ICU-01, ICU-02, ICU-03, ICU-04, ICU-05,
ICU-06, ICU-07, ICU-08, ICU-09, ICU-10,
ICU-11, ICU-12, ICU-13, ICU-14, ICU-15,
ICU-16, ICU-17, ICU-18, ICU-19, CAUTI
```

---

## 九、调用链路

```
_compute_icu05(month)
  → get_bundle_data_v2(month)
      → 遍历 den_patient (分母患者)
          → judge_bundle_v3_for_patient(patient)    [db.py]
              → 查询各数据源 (bedside, bGATemp, drugExe, ...)
              → 组装 patient_data dict
              → bundle_engine.judge_bundle_v3(patient_data)
                  → 门控判定 (S1-S4, I1-I3, K1-K2)
                  → Bundle 时间窗判定 (1h, 3h, 6h)
                  → 返回 {bundle_1h, bundle_3h, bundle_6h, gate}
  → 聚合: numerator / denominator
  → 写入 icu_monthly_summary
```

---

## 十、升压药完整清单 (2026-06 ~ 2026-08 drugExe 实测)

### 核心升压药 (canon_drug 已覆盖)

| 药物 | 通用名 | 英文名 | 2026-06~08 频次 | 覆盖患者数 |
|------|--------|--------|-----------------|-----------|
| 去甲肾上腺素注射液 | 去甲肾上腺素 | norepinephrine | ~3800+ | 175人/月 |
| 间羟胺注射液 | 间羟胺 | metaraminol | ~1000+ | 175人/月 |
| 多巴胺注射液 | 多巴胺 | dopamine | ~300+ | 40人/月 |
| 多巴酚丁胺注射液 | 多巴酚丁胺 | dobutamine | ~300+ | 35人/月 |
| 肾上腺素注射液 | 肾上腺素 | epinephrine | ~600+ | 35人/月 |
| 垂体后叶注射液 | 垂体后叶素 | vasopressin | ~800+ | 53人/月 |
| 特利加压素粉针 | 特利加压素 | terlipressin | ~580+ | 63人/月 |
| 乌拉地尔注射液 | 乌拉地尔 | — | ~1200+ | 129人/月 |
| 异丙肾上腺素注射液 | 异丙肾上腺素 | isoproterenol | ~400+ | 109人/月 |
| 左西孟旦注射液 | 左西孟旦 | levosimendan | ~15 | 12人 |
| 盐酸去氧肾上腺素注射液 | 去氧肾上腺素 | phenylephrine | ~6 | 3人 |

### 血管扩张药 (非核心升压药, canon_drug 未纳入)

| 药物 | 用途 | 频次 |
|------|------|------|
| 艾司洛尔注射液 | 控制心率/降压 | ~812次, 130人 |
| 硝酸甘油注射液 | 扩冠/降压 | ~307次, 50人 |
| 硝普钠粉针 | 扩血管降压 | ~60次, 15人 |
| 尼卡地平注射液 | 降压 | ~350次, 46人 |
| 拉贝洛尔片 | 降压 | ~6次, 2人 |

> **说明**: 艾司洛尔、硝酸甘油等属于血管扩张药/控制心率药物, 在 SOFA-2 标准中**不作为升压药**。脓毒症休克 Bundle 中 K2/S4 仅识别真正的升压药 (vasopressors/inotropers)。
