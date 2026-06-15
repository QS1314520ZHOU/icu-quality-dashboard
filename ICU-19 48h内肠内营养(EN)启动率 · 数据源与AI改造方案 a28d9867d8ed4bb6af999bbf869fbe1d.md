# ICU-19 48h内肠内营养(EN)启动率 · 数据源与AI改造方案

<aside>
⚠️

核心结论:ICU-19「48h 内 EN 启动率」可由 **drugExe(营养类) + bedside(消化系统评估)** 双源判定 EN 启动时间。但需解决三件事:① 「营养」分类含**肠外营养(PN)**,须二次区分肠内;② bedside 字段与「营养」分类**跨院可能未配置**,需医嘱名称关键词兜底与自动降级;③ 48h 窗口需另接**入 ICU 时间**。分母排除 EN 禁忌证按 ICU-06 方式做规则 + 留痕 + 人工复核。

</aside>

## 一、指标定义与口径

- **分子**:入住 ICU 超过 48h 的患者中,48h 内启动 EN 的患者人数。
- **分母**:同期入住 ICU 超过 48h 的患者总数。
- **计算公式**:48h 内肠内营养启动率 = 分子 / 分母 × 100%。
- **指标导向**:高优指标(越高越好)。数据来源:NCIS 系统(本院落在 SmartCare.drugExe + bedside 消化系统评估)。
- **禁忌证**:EN 启动前应排除 EN 禁忌证(参考《中国成人患者肠外肠内营养临床应用指南(2023 版)》)。

<aside>
❗

指标说明第 2 条:统计「同期入住 ICU 超过 48h 的患者总数」时,**不应自动排除** EN 禁忌证患者,具体情况应在病程记录中备注说明。→ 禁忌证以「标注 + 留痕」为主,不直接从分母删除。

</aside>

## 二、数据源盘点(本院已确认)

| 数据源 | 提供什么 | 备注 |
| --- | --- | --- |
| **drugExe + configDrug.classification='营养'** | 营养制剂执行时间(startTime / hisStartTime.exeTime)、剂量、途径(methodCode)、执行状态(status='finished' / statusFlag='已执行') | 「营养」类**含肠外 PN**,需再筛肠内 |
| **bedside 消化系统评估** | param_肠内营养途径(造瘘/经口/胃管/鼻空肠管)、param_营养输注方式(开始/结束/分次推注/间接重力滴注/持续泵入/顿服)、param_肠内营养措施(开始/增速/维持/暂停/结束)、param_肠内营养耐受评分、param_腹部体征 | **明确肠内**,可覆盖匀浆膳/管饲;但跨院可能未配置 |
| 入 ICU 时间 | 入科 / 床位 / 住院记录表(待确认表名字段) | 48h 窗口必需,drugExe 与 bedside 都没有 |

## 三、关键口径坑

1. **「营养」分类过宽**:同时含肠外营养(脂肪乳、复方氨基酸、葡萄糖、卡文/卡全三腔袋)。只按 `classification='营养'` 会把 PN 误纳,与 CRBSI 误纳动脉导管是同类「分类口径过宽」问题。
2. **bedside 跨院差异**:不同医院可能未配置消化系统评估字段 → 不能只依赖 bedside。
3. **「营养」分类也可能未配/配错** → 需**医嘱名称关键词兜底**。
4. **入 ICU 时间在另一张表** → 必须 join 才能算 48h 窗口。

## 四、EN 识别多层兜底(从准到糙,命中层级留痕)

| 层级 | 判据 | 说明 |
| --- | --- | --- |
| **L1 途径最准** | bedside `param_肠内营养措施=开始`,或 `param_营养输注方式=开始` 且 `param_肠内营养途径` 有值 | 明确肠内,覆盖匀浆膳/管饲,优先用 |
| **L2 分类** | `configDrug.classification='营养'` **且** 途径(methodCode)/名称判为肠内 | 分类配了才有;须再筛掉肠外 PN |
| **L3 名称兜底** | `drugList[].name` 命中 **EN 白名单** 且 **不命中 PN 黑名单** | 分类没配/配错时的保底 |

三层取**最早的肠内启动时间**,命中即用,并记录命中来源(bedside / 分类 / 名称),供质控下钻与误差收敛。

### EN 白名单(命中 = 肠内)

- **通用名强信号**:名称含「**肠内营养**」(肠内营养混悬液 TPF / 肠内营养乳剂 TP·TPF-D·TPF-T / 肠内营养粉剂 AA·短肽)——可捞到一大批。
- **常见商品名**:能全力、瑞素、瑞能、瑞代、瑞先、百普力、百普素、安素、康全力、佳维体、益菲佳、维沃、全安素。
- **关键词补充**:短肽型、整蛋白型、匀浆膳、鼻饲营养。

### PN 黑名单(命中 = 肠外,剔除)

- 脂肪乳注射液、中长链/结构脂肪乳、复方氨基酸注射液(乐凡命 / 18AA 等)、葡萄糖注射液。
- 三腔袋:卡文、卡全、全合一。
- 通用排除:名称含「注射液 / 静脉」且非「肠内营养」。

<aside>
💡

匹配顺序:**先判正向「肠内营养」关键词,再判负向 PN 黑名单**,正向命中优先,避免误伤「肠内营养乳剂」(含「乳剂」二字但属肠内)。

</aside>

## 五、EN 启动判定逻辑

按优先级取**最早的肠内营养启动时间**,命中即停:

1. **优先 bedside(最可靠)**:`param_肠内营养措施=开始`,或 `param_营养输注方式=开始`(且 `param_肠内营养途径` 为经口/胃管/鼻空肠管/造瘘)。取该记录时间戳。
2. **兜底 drugExe(bedside 未填或医院未配该字段)**:`classification='营养'` 或名称命中 EN 白名单,且途径/名称判为**肠内**、`statusFlag='已执行'` 的首条记录,取 `startTime`/`exeTime`。
3. 两源都有则取**更早**者;记录命中来源与命中关键词。

> 「启动」按**首次给予即算**(不要求达标量),与指标定义一致。
> 

## 六、改造取数(伪代码)

```python
def resolve_en_start_time(patient, ctx):
    """返回 (en_start_time | None, evidence)。多层兜底 + 命中层级留痕。"""
    # L1 bedside(最准,覆盖匀浆膳/管饲)
    t1 = ctx.bedside_en_start(patient)   # param_肠内营养措施=开始 / 营养输注方式=开始 且 有肠内途径
    if t1:
        return t1, {"source": "bedside", "rule": "en_measure_start"}
    # L2 分类(营养)→ 再筛肠内
    rec = ctx.first_nutrition_drugexe(patient)   # classification='营养' 且 已执行
    if rec and ctx.is_enteral_route_or_name(rec):  # methodCode 肠内途径 或 名称含肠内营养
        return rec.start_time, {"source": "classification", "rule": "nutrition_enteral"}
    # L3 名称兜底(分类没配/配错)
    rec2 = ctx.first_drugexe_name_hit(patient, EN_WHITELIST, PN_BLACKLIST)
    if rec2:
        return rec2.start_time, {"source": "name", "rule": "en_name_whitelist", "hit": rec2.hit_kw}
    return None, {"source": "none"}

def get_icu19_data(period, ctx):
    den, num = 0, 0
    for p in ctx.icu_patients(period):
        admit = ctx.icu_admit_time(p)            # 另一张入科表
        if ctx.icu_stay_hours(p, admit) <= 48:    # 仅入住 >48h 的患者进分母
            continue
        den += 1
        en_start, ev = resolve_en_start_time(p, ctx)
        ctx.mark_contraindication_if_any(p)       # 禁忌证仅标注+病程留痕,不剔除分母
        save_decision(p, en_start, ev)            # 一律留痕(启动时间/来源/命中关键词)
        if en_start and (en_start - admit) <= timedelta(hours=48):
            num += 1
    return {"den": den, "num": num, "rate": (num / den * 100) if den else None}
```

## 七、AI 提示词(可直接发编码 AI)

### 7.1 通用上下文补充(ICU-19 专用,接在系统通用上下文之后)

```
本轮负责 ICU-19「48h 内肠内营养(EN)启动率」的数据源核实与取数改造。指标取数集中在 backend/app 的 db.py(参考 get_icu06_data 写法),指标定义/数据源说明在 main.py。
口径:分子=入住 ICU 超过 48h 的患者中 48h 内启动 EN 的人数;分母=同期入住 ICU 超过 48h 的患者总数;启动率=分子/分母×100%。
已确认数据源:① drugExe + configDrug.classification='营养'(含执行时间/剂量/途径 methodCode/执行状态),但「营养」类含肠外营养(PN)需二次筛肠内;② bedside 消化系统评估(param_肠内营养途径/营养输注方式/肠内营养措施 等)明确肠内、可覆盖匀浆膳,但跨院可能未配置;③ 入 ICU 时间在入科/床位记录表(待确认)。
工作纪律同前:先通读 db.py/main.py 与上述集合字段,输出「现状核实」;再出实施计划(改动文件、聚合改法、数据模型、风险、测试点、分步顺序),经我确认后再写代码;不破坏现有结构;判定结果一律留痕。收到回复「已就位」。
```

### 7.2 ICU-19 任务提示词

```
任务:实现/修正 ICU-19「48h 内 EN 启动率」的取数,核心是「多层兜底识别肠内营养启动 + 48h 窗口判定」。
现状核实(先做):
- 定位 db.py 中 ICU-19 取数函数(如 get_icu19_data)与 main.py 的指标定义/SOURCE_DESC;若不存在则新建。
- 核实三件事:① configDrug 是否配置「营养」分类、其下肠内/肠外是否混在一起;② methodCode 途径字典(哪些码=鼻胃管/鼻肠管/口服/造瘘等肠内,哪些=静脉肠外);③ bedside 消化系统评估记录是否带时间戳、字段是否逐院差异;④ 入 ICU 时间来源表名与字段。
实现目标:
1. EN 启动判定做成多层兜底 + 自动降级:L1 bedside(肠内营养措施/输注方式=开始 且有肠内途径)→ L2 classification='营养' 且途径/名称判为肠内 → L3 医嘱名称白名单命中且不命中 PN 黑名单。三层取最早肠内启动时间,记录命中来源与关键词。
2. EN 白名单/PN 黑名单、methodCode 肠内途径码、bedside 字段开关全部走 config/runtime_config,可按院区切换;先判正向「肠内营养」关键词再判 PN 黑名单。
3. 48h 窗口:启动时间 − 入 ICU 时间 ≤ 48h 计入分子;分母=入住 ICU >48h 的患者。
4. 禁忌证:仅标注 + 病程留痕,不自动从分母剔除(遵循指标说明第 2 条)。
5. 不破坏现有数据结构;分母明细每行保留:patient_id、入科时间、EN 启动时间、命中来源(bedside/分类/名称)、命中关键词、是否禁忌证标注。
先输出:现状核实结果、methodCode 肠内途径码清单、EN 白/黑名单初稿、判定与取数方案(含伪代码)、新旧口径对比与测试用例。确认后再编码。
```

## 八、验证与复核计划

1. 选 1–2 个月真实数据跑判定,输出每例的 EN 启动时间 + 命中来源 + 关键词。
2. 抽样核对(建议 ≥50 例/月):bedside 与 drugExe 两源是否一致、肠内/肠外是否误判、匀浆膳是否漏抓。
3. 对比仅 drugExe vs 双源 + 名称兜底两种口径下的启动率差异。
4. 据复核结果迭代白/黑名单与 methodCode 映射。

## 九、待对齐事项

- [ ]  确认 `methodCode` 途径字典,锁定肠内途径码集合。
- [ ]  确认 bedside 消化系统评估记录是否带可用时间戳,以及各院区是否配置。
- [ ]  确认入 ICU 时间的来源表名与字段。
- [ ]  确认 EN 禁忌证的诊断/病程数据来源与标注流程。
- [ ]  确认 configDrug「营养」分类在各院区的配置情况(是否需名称兜底兜全)。