# ICU-05 v3 数据探查报告摘要
运行时间: 2026-09-04 10:39:12

## 一、数据概况

| 数据源 | 文档量 | 说明 |
|---|---|---|
| bedside(param_ibp_m) | 592,063 | 有创MAP |
| bedside(param_nibp_m) | 1,799,659 | 无创MAP |
| bedside(param_score_gcs_obs) | 981,576 | GCS编码 |
| bedside(param_niaoLiang) | 514,304 | 尿量 |
| bGATemp(param_bg_P/Fratio) | 93,210 | P/F ratio |
| bGATemp(param_bg_Lac) | 98,311 | 乳酸 |
| bGATemp(param_bg_FiO2) | 80,993 | FiO2(百分数) |
| score(gcsScore) | 987,279 | GCS总分 |
| score(sofa) | 1,670 | SmartCare SOFA |
| patient | 27,094 | 患者(weight字符串,19.6%有值) |
| configDrug | 1,500 | 药物字典(classification8类) |
| drugExe | 2,145,960 | 药物执行 |
| infectionShockV2 | 30 | 现有感染性休克记录 |
| diseaseDiagnosis | 517 | 诊断 |
| DC:VI_ICU_ZYYZ | 7,836,629 | 医嘱 |
| DC:VI_ICU_EXAM_ITEM | 1,591,141 | 检验 |

## 二、脓毒症器官障碍(S1-S4)

| ID | 判定项 | 数据源 | 非空率 | 关键发现 |
|---|---|---|---|---|
| S1 | P/F ratio | bGATemp param_bg_P/Fratio | 93,210条 | P50=310,可直接使用;FiO2为百分数(0-100) |
| S2 | GCS | bedside param_score_gcs_obs | 981,576条 | strVal编码(E1VTM1),需解析;score表有total但样例total=2异常 |
| S3 | MAP | bedside param_ibp_m/nibp_m | 592K/1.8M | 实测值;有创+无创混合 |
| S4 | 血管活性药 | configDrug classification | 29个code | 含错误药(浓氯化钠/氯化钾);status=finished |

## 三、脓毒症休克(K1-K2)

| ID | 判定项 | 非空率 | 关键发现 |
|---|---|---|---|
| K1 | Lac | 995/1000(99.5%) | P50=1.6mmol/L;不区分动脉/静脉 |
| K2 | 血管活性药 | 同S4 | startTime非空92%;exeTime不可用 |

## 四、感染部位

- diseaseDiagnosis 无部位字段(site/infectionSite/部位均不存在)
- 诊断名含感染关键词: 脓毒性休克112/脓毒症9/VAP8/CRBSI6/CAUTI1
- 病原学送检: 痰培养33%/血培养34%/尿培养4%（标本类型嵌入医嘱名）
- **需要新建感染部位字段**

## 五、Bundle第二步(血培养+抗生素)

- VI_ZYYZ 不存在,仅 VI_ICU_ZYYZ
- VI_ICU_ZYYZ: 28字段,reviewTime非空99.7%,无startTime/exeTime
- 血培养(已执行): 13,552条
- 抗生素: 85个code
- 多条抗生素: 18/20例(90%);首剂-最晚剂差P50=54.9h

## 六、Bundle第三步(液体)

- 剂量单位: ml(46.4%)/mg(19.7%)/g(18.1%)/支(6.6%)
- 可直接累加ml: 766/1,652(46.4%)
- 液体分类: 晶体557/胶体1/其他208（靠药名正则,无分类字段）

## 七、SOFA/SOFA-2

| 分项 | 数据源 | code | 单位 | 关键发现 |
|---|---|---|---|---|
| P/F ratio | bGATemp | param_bg_P/Fratio | mmHg | 98%直接可用 |
| 血小板 | VI_ICU_EXAM_ITEM | PLT | 10^9/L | 12,799条,单位统一 |
| 总胆红素 | VI_ICU_EXAM_ITEM | TBIL | umol/L(58%)/micromol/L(42%) | 2种变体,需统一 |
| 肌酐 | VI_ICU_EXAM_ITEM | sCr | umol/L | 7,624条,SOFA-2需÷88.4换算 |
| 钾 | VI_ICU_EXAM_ITEM | K | mmol/L | 6,777条 |
| HCO3 | VI_ICU_EXAM_ITEM | HCO3 | mmol/L | 6,067条 |
| 乳酸 | VI_ICU_EXAM_ITEM | LAC | mmol/L | 20,024条 |
| MAP | bedside | param_ibp_m/nibp_m | mmHg | 实测值 |
| GCS | bedside+score | param_score_gcs_obs/gcsScore | 分 | 编码需解析 |
| 体重 | patient | weight | kg(字符串) | 19.6%有值,max=810需清洗 |
| 尿量 | bedside | param_niaoLiang | ml | 514K条,间隔2-8h(P50=4h),可插值 |

- SmartCare SOFA: 仅2条记录,无法做影子比对
- SOFA-2 尿量路径可行(间隔2-8h可插值),但体重仅19.6%有值需注意
- FiO2为百分数,SOFA-2需÷100转小数
- 升压药剂量换算: dose/liquid×speed→mg/h可行,但speed覆盖仅30%

## 八、现有实现(infectionShockV2)

- 总文档: 30条
- group1H/group3H/group6H 各有49个子字段
- fill率: finish 63-67%, baStandard 10-33%, lacVal 23-30%
- 现有口径与v3差异: baStandard=bundle达标,lacGte4=乳酸≥4,lacStandard=乳酸达标
