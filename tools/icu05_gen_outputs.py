#!/usr/bin/env python3
"""生成 ICU-05 v3 探查产出文件（只读）"""
import sys, os, io, json, csv, re
from datetime import datetime, timedelta
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from db import get_datacenter_db, iter_bed_dbs, EXECUTED_ORDER_STATUSES, LAB_ORDER_TYPES

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

def sc():
    for _, db in iter_bed_dbs(): return db
def dc():
    try: return get_datacenter_db()
    except: return None

def fmt_dt(v):
    if v is None: return ""
    if hasattr(v, 'strftime'): return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:25]

def pcts(vals):
    if not vals: return {}
    s = sorted(vals); n = len(s)
    return {"n": n, "min": round(s[0],2), "P5": round(s[int(n*.05)],2),
            "P50": round(s[int(n*.50)],2), "P95": round(s[int(n*.95)],2), "max": round(s[-1],2)}

db = sc()
dc_db = dc()

# ============================================================
# 1. summary.md
# ============================================================
print("生成 icu05_v3_summary.md ...")
summary = []
def s(s=""): summary.append(s)

s("# ICU-05 v3 数据探查报告摘要")
s(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
s("")

s("## 一、数据概况")
s("")
s("| 数据源 | 文档量 | 说明 |")
s("|---|---|---|")
s(f"| bedside(param_ibp_m) | {db.bedside.count_documents({'code':'param_ibp_m','valid':True}):,} | 有创MAP |")
s(f"| bedside(param_nibp_m) | {db.bedside.count_documents({'code':'param_nibp_m','valid':True}):,} | 无创MAP |")
s(f"| bedside(param_score_gcs_obs) | {db.bedside.count_documents({'code':'param_score_gcs_obs','valid':True}):,} | GCS编码 |")
s(f"| bedside(param_niaoLiang) | {db.bedside.count_documents({'code':'param_niaoLiang','valid':True}):,} | 尿量 |")
s(f"| bGATemp(param_bg_P/Fratio) | {db.bGATemp.count_documents({'bedsides.code':'param_bg_P/Fratio'}):,} | P/F ratio |")
s(f"| bGATemp(param_bg_Lac) | {db.bGATemp.count_documents({'bedsides.code':'param_bg_Lac'}):,} | 乳酸 |")
s(f"| bGATemp(param_bg_FiO2) | {db.bGATemp.count_documents({'bedsides.code':'param_bg_FiO2'}):,} | FiO2(百分数) |")
s(f"| score(gcsScore) | {db.score.count_documents({'scoreType':'gcsScore'}):,} | GCS总分 |")
s(f"| score(sofa) | {db.score.count_documents({'scoreType':'sofa'}):,} | SmartCare SOFA |")
s(f"| patient | {db.patient.count_documents({}):,} | 患者(weight字符串,19.6%有值) |")
s(f"| configDrug | {db.configDrug.count_documents({}):,} | 药物字典(classification8类) |")
s(f"| drugExe | {db.drugExe.count_documents({}):,} | 药物执行 |")
s(f"| infectionShockV2 | {db.infectionShockV2.count_documents({}):,} | 现有感染性休克记录 |")
s(f"| diseaseDiagnosis | {db.diseaseDiagnosis.count_documents({}):,} | 诊断 |")
if dc_db is not None:
    s(f"| DC:VI_ICU_ZYYZ | {dc_db['VI_ICU_ZYYZ'].count_documents({}):,} | 医嘱 |")
    s(f"| DC:VI_ICU_EXAM_ITEM | {dc_db['VI_ICU_EXAM_ITEM'].count_documents({}):,} | 检验 |")
s("")

s("## 二、脓毒症器官障碍(S1-S4)")
s("")
s("| ID | 判定项 | 数据源 | 非空率 | 关键发现 |")
s("|---|---|---|---|---|")
s("| S1 | P/F ratio | bGATemp param_bg_P/Fratio | 93,210条 | P50=310,可直接使用;FiO2为百分数(0-100) |")
s("| S2 | GCS | bedside param_score_gcs_obs | 981,576条 | strVal编码(E1VTM1),需解析;score表有total但样例total=2异常 |")
s("| S3 | MAP | bedside param_ibp_m/nibp_m | 592K/1.8M | 实测值;有创+无创混合 |")
s("| S4 | 血管活性药 | configDrug classification | 29个code | 含错误药(浓氯化钠/氯化钾);status=finished |")
s("")

s("## 三、脓毒症休克(K1-K2)")
s("")
s("| ID | 判定项 | 非空率 | 关键发现 |")
s("|---|---|---|---|")
s("| K1 | Lac | 995/1000(99.5%) | P50=1.6mmol/L;不区分动脉/静脉 |")
s("| K2 | 血管活性药 | 同S4 | startTime非空92%;exeTime不可用 |")
s("")

s("## 四、感染部位")
s("")
s("- diseaseDiagnosis 无部位字段(site/infectionSite/部位均不存在)")
s("- 诊断名含感染关键词: 脓毒性休克112/脓毒症9/VAP8/CRBSI6/CAUTI1")
s("- 病原学送检: 痰培养33%/血培养34%/尿培养4%（标本类型嵌入医嘱名）")
s("- **需要新建感染部位字段**")
s("")

s("## 五、Bundle第二步(血培养+抗生素)")
s("")
s("- VI_ZYYZ 不存在,仅 VI_ICU_ZYYZ")
s("- VI_ICU_ZYYZ: 28字段,reviewTime非空99.7%,无startTime/exeTime")
s("- 血培养(已执行): 13,552条")
s("- 抗生素: 85个code")
s("- 多条抗生素: 18/20例(90%);首剂-最晚剂差P50=54.9h")
s("")

s("## 六、Bundle第三步(液体)")
s("")
s("- 剂量单位: ml(46.4%)/mg(19.7%)/g(18.1%)/支(6.6%)")
s("- 可直接累加ml: 766/1,652(46.4%)")
s("- 液体分类: 晶体557/胶体1/其他208（靠药名正则,无分类字段）")
s("")

s("## 七、SOFA/SOFA-2")
s("")
s("| 分项 | 数据源 | code | 单位 | 关键发现 |")
s("|---|---|---|---|---|")
s("| P/F ratio | bGATemp | param_bg_P/Fratio | mmHg | 98%直接可用 |")
s("| 血小板 | VI_ICU_EXAM_ITEM | PLT | 10^9/L | 12,799条,单位统一 |")
s("| 总胆红素 | VI_ICU_EXAM_ITEM | TBIL | umol/L(58%)/micromol/L(42%) | 2种变体,需统一 |")
s("| 肌酐 | VI_ICU_EXAM_ITEM | sCr | umol/L | 7,624条,SOFA-2需÷88.4换算 |")
s("| 钾 | VI_ICU_EXAM_ITEM | K | mmol/L | 6,777条 |")
s("| HCO3 | VI_ICU_EXAM_ITEM | HCO3 | mmol/L | 6,067条 |")
s("| 乳酸 | VI_ICU_EXAM_ITEM | LAC | mmol/L | 20,024条 |")
s("| MAP | bedside | param_ibp_m/nibp_m | mmHg | 实测值 |")
s("| GCS | bedside+score | param_score_gcs_obs/gcsScore | 分 | 编码需解析 |")
s("| 体重 | patient | weight | kg(字符串) | 19.6%有值,max=810需清洗 |")
s("| 尿量 | bedside | param_niaoLiang | ml | 514K条,24h汇总(非小时) |")
s("")
s("- SmartCare SOFA: 仅2条记录,无法做影子比对")
s("- SOFA-2 尿量路径不可行(体重19.6%+尿量非小时序列)")
s("- FiO2为百分数,SOFA-2需÷100转小数")
s("- 升压药剂量换算: dose/liquid×speed→mg/h可行,但speed覆盖仅30%")
s("")

s("## 八、现有实现(infectionShockV2)")
s("")
s("- 总文档: 30条")
s("- group1H/group3H/group6H 各有49个子字段")
s("- fill率: finish 63-67%, baStandard 10-33%, lacVal 23-30%")
s("- 现有口径与v3差异: baStandard=bundle达标,lacGte4=乳酸≥4,lacStandard=乳酸达标")
s("")

with open(os.path.join(OUT, "icu05_v3_summary.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(summary))

# ============================================================
# 2. questions.md
# ============================================================
print("生成 icu05_v3_questions.md ...")
questions = []
def q(n, phen, impact, count, suggest):
    questions.append(f"### Q{n}. {phen}")
    questions.append(f"- **现象**: {phen}")
    questions.append(f"- **影响**: {impact}")
    questions.append(f"- **影响例数**: {count}")
    questions.append(f"- **建议**: {suggest}")
    questions.append("")

questions.append("# ICU-05 v3 口径问题清单")
questions.append("")

q(1, "FiO2是百分数(0-100)而非小数(0-1)",
   "SOFA呼吸分项P/F ratio计算需FiO2为小数;若不转换会导致P/F被高估100倍",
   "全部80,993条FiO2记录",
   "代码中强制÷100,并加白名单校验: FiO2>1.5时自动÷100")

q(2, "GCS bedside是编码字符串(E1VTM1),score表total样例=2异常",
   "SOFA神经分项需要数字GCS总分;编码需解析E+V+M;score表total=2说明可能不是标准GCS",
   "981,576条bedside +5,636条score",
   "优先从bedside strVal解析E+V+M求和;score表作为备用但需验证total含义")

q(3, "TBIL单位有两种变体: umol/L(58%) vs micromol/L(42%)",
   "SOFA肝分项阈值按μmol/L定义;若不统一会导致42%的记录单位不匹配",
   "9,933条TBIL记录",
   "统一为μmol/L: umol/L和micromol/L视为等价(都是μmol/L);代码加白名单{'umol/L','micromol/L','μmol/L'}")

q(4, "patient.weight是字符串类型,19.6%有值,max=810异常",
   "SOFA-2尿量路径(mL/kg/h)需要体重;19.6%覆盖不足以支撑;810kg需清洗",
   "27,094患者,5,315有体重",
   "SOFA-2尿量路径不可行,走肌酐路径;体重仅用于升压药剂量换算(65%有值)")

q(5, "尿量是24h汇总而非小时序列",
   "SOFA-2需要'<0.5持续6-12h'判定,无法从24h总量还原连续小时序列",
   "514,304条尿量记录",
   "SOFA-2尿量分项标记为insufficient;仅用肌酐路径")

q(6, "Lac不区分动脉血/静脉血",
   "需求文档要求'动脉血乳酸';静脉血乳酸通常偏高0.3-0.5mmol/L",
   "全部乳酸记录",
   "默认按动脉血处理(临床ICU多为动脉血气);详情标注'未区分'")

q(7, "血管活性药物分类含错误药(浓氯化钠/氯化钾/胺碘酮片)",
   "S4/K2判定会误判为使用了血管活性药;胺碘酮是抗心律失常不是升压药",
   "configDrug 29个血管活性code中约5个异常",
   "人工复核configDrug分类;排除浓氯化钠/氯化钾/胺碘酮片/口服药")

q(8, "升压药speed覆盖仅30%",
   "ug/(kg·min)换算需要speed(ml/h);70%的执行记录无法计算剂量",
   "2,000条升压药记录",
   "speed缺失时标记为不可计算;仅对三者齐备的记录出剂量值")

q(9, "去甲肾上腺素盐型无法从药品名识别",
   "SOFA-2要求换算为NE base;酒石酸盐×0.50/盐酸盐×(1/1.22)/base×1.0",
   "全部去甲肾上腺素记录",
   "从剂量推断: 16mg/18mg→可能base,但不确切;需外部字典补充ampoule规格")

q(10, "SmartCare SOFA仅2条记录",
   "无法做影子比对",
   "仅2条",
   "影子比对功能暂不可用;后续积累数据后再启用")

q(11, "呼吸支持分类太粗(管辅/切辅/高流量/无创)",
   "SOFA-2需要识别HFNC/CPAP/BiPAP/NIV/IMV/ECMO;当前分类粒度不够",
   "1,668,121条吸氧途径",
   "需要从多个字段组合判定: param_XiYangTuJing+param_vent_mode+param_vent_type;或新建精细分类")

q(12, "ECMO无法区分呼吸指征vs循环指征",
   "SOFA-2规定: 呼吸指征→呼吸4;循环指征→呼吸4且循环4",
   "100+条ECMO记录",
   "需要新增ECMO指征字段或从医嘱备注中提取")

q(13, "RRT无法区分肾脏指征vs非肾脏指征",
   "SOFA-2规定: 非肾脏指征RRT不计4分",
   "100+条透析记录",
   "需要新增RRT指征字段")

with open(os.path.join(OUT, "icu05_v3_questions.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(questions))

# ============================================================
# 3. sofa_shadow.csv (SmartCare SOFA影子比对)
# ============================================================
print("生成 sofa_shadow.csv ...")
with open(os.path.join(OUT, "sofa_shadow.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["pid", "time", "smartcare_total", "platform_total", "delta", "note"])
    # SmartCare SOFA只有2条
    for doc in db.score.find({"scoreType": "sofa"}, {"pid": 1, "total": 1, "time": 1}):
        w.writerow([
            doc.get("pid", ""),
            fmt_dt(doc.get("time")),
            doc.get("total", ""),
            "",  # platform_total (需要SOFA计算模块)
            "",
            "SmartCare SOFA仅2条,无法比对"
        ])
    # 写一行说明
    w.writerow(["说明", "SmartCare score表仅有2条SOFA记录,影子比对暂不可用", "", "", "", ""])

# ============================================================
# 4. sofa_trace_sample.json
# ============================================================
print("生成 sofa_trace_sample.json ...")
# 取5个有bGATemp的患者做样例
trace_samples = []
bga_pids = []
for doc in db.bGATemp.find({}, {"eventExe.pid": 1}).limit(30):
    pid = (doc.get("eventExe") or {}).get("pid")
    if pid and pid not in bga_pids: bga_pids.append(pid)
    if len(bga_pids) >= 5: break

for pid in bga_pids:
    sample = {"pid": pid, "components": {}}

    # P/F ratio
    pf_docs = list(db.bGATemp.find(
        {"eventExe.pid": pid, "bedsides.code": "param_bg_P/Fratio"},
        {"eventExe": 1, "bedsides": 1}
    ).sort("eventExe.startTime", -1).limit(10))
    pf_records = []
    for doc in pf_docs:
        evt = doc.get("eventExe", {})
        for b in doc.get("bedsides", []):
            if b.get("code") == "param_bg_P/Fratio":
                pf_records.append({
                    "value": b.get("fVal"),
                    "time": fmt_dt(evt.get("startTime")),
                    "record_id": str(doc.get("_id", "")),
                })
                break
    sample["components"]["PF_ratio"] = {
        "source": "bGATemp", "code": "param_bg_P/Fratio",
        "unit": "mmHg", "max_staleness_h": 4,
        "records": pf_records[:5],
        "selected": pf_records[0] if pf_records else None,
    }

    # MAP
    map_doc = db.bedside.find_one(
        {"pid": pid, "code": "param_ibp_m", "valid": True},
        sort=[("time", -1)])
    if map_doc:
        sample["components"]["MAP"] = {
            "source": "bedside", "code": "param_ibp_m",
            "unit": "mmHg", "max_staleness_h": 1,
            "records": [{"value": map_doc.get("strVal"), "time": fmt_dt(map_doc.get("time")),
                         "record_id": str(map_doc.get("_id", ""))}],
            "selected": {"value": map_doc.get("strVal"), "time": fmt_dt(map_doc.get("time"))},
        }

    # GCS
    gcs_doc = db.bedside.find_one(
        {"pid": pid, "code": "param_score_gcs_obs", "valid": True},
        sort=[("time", -1)])
    if gcs_doc:
        sample["components"]["GCS"] = {
            "source": "bedside", "code": "param_score_gcs_obs",
            "unit": "分", "max_staleness_h": 8,
            "records": [{"value": gcs_doc.get("strVal"), "time": fmt_dt(gcs_doc.get("time")),
                         "record_id": str(gcs_doc.get("_id", ""))}],
            "selected": {"value": gcs_doc.get("strVal"), "time": fmt_dt(gcs_doc.get("time"))},
            "note": "strVal是编码(E1VTM1),需解析为数字总分",
        }

    # Lac
    lac_docs = list(db.bGATemp.find(
        {"eventExe.pid": pid, "bedsides.code": "param_bg_Lac"},
        {"eventExe": 1, "bedsides": 1}
    ).sort("eventExe.startTime", -1).limit(10))
    lac_records = []
    for doc in lac_docs:
        evt = doc.get("eventExe", {})
        for b in doc.get("bedsides", []):
            if b.get("code") == "param_bg_Lac":
                lac_records.append({
                    "value": b.get("fVal"),
                    "time": fmt_dt(evt.get("startTime")),
                    "record_id": str(doc.get("_id", "")),
                })
                break
    sample["components"]["Lactate"] = {
        "source": "bGATemp", "code": "param_bg_Lac",
        "unit": "mmol/L",
        "records": lac_records[:5],
        "selected": lac_records[0] if lac_records else None,
        "note": "不区分动脉/静脉",
    }

    trace_samples.append(sample)

with open(os.path.join(OUT, "sofa_trace_sample.json"), "w", encoding="utf-8") as f:
    json.dump(trace_samples, f, ensure_ascii=False, indent=2, default=str)

# ============================================================
# 5. detail.csv (逐例明细 — 用infectionShockV2的30条)
# ============================================================
print("生成 icu05_v3_detail.csv ...")
with open(os.path.join(OUT, "icu05_v3_detail.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow([
        "diseaseId", "pid", "hisPid",
        "group1H_finish", "group1H_baStandard", "group1H_lacVal", "group1H_lacStandard",
        "group1H_mapVal", "group1H_antExeTime", "group1H_bcExeTime", "group1H_drugAmountVal",
        "group3H_finish", "group3H_baStandard", "group3H_lacVal", "group3H_lacStandard",
        "group3H_mapVal", "group3H_antExeTime", "group3H_bcExeTime", "group3H_drugAmountVal",
        "group6H_finish", "group6H_baStandard", "group6H_boost", "group6H_lacVal",
        "group6H_mapVal", "group6H_antExeTime", "group6H_bcExeTime", "group6H_drugAmountVal",
        "group6H_cvpVal", "group6H_scvO2Val",
    ])
    for doc in db.infectionShockV2.find():
        g1 = doc.get("group1H") or {}
        g3 = doc.get("group3H") or {}
        g6 = doc.get("group6H") or {}
        w.writerow([
            doc.get("diseaseId", ""), doc.get("pid", ""), doc.get("hisPid", ""),
            g1.get("finish", ""), g1.get("baStandard", ""), g1.get("lacVal", ""), g1.get("lacStandard", ""),
            g1.get("mapVal", ""), g1.get("antExeTime", ""), g1.get("bcExeTime", ""), g1.get("drugAmountVal", ""),
            g3.get("finish", ""), g3.get("baStandard", ""), g3.get("lacVal", ""), g3.get("lacStandard", ""),
            g3.get("mapVal", ""), g3.get("antExeTime", ""), g3.get("bcExeTime", ""), g3.get("drugAmountVal", ""),
            g6.get("finish", ""), g6.get("baStandard", ""), g6.get("boost", ""), g6.get("lacVal", ""),
            g6.get("mapVal", ""), g6.get("antExeTime", ""), g6.get("bcExeTime", ""), g6.get("drugAmountVal", ""),
            g6.get("cvpVal", ""), g6.get("scvO2Val", ""),
        ])

print("\n全部5份文件生成完成:")
for name in ["icu05_v3_summary.md", "icu05_v3_questions.md", "icu05_v3_detail.csv",
             "sofa_shadow.csv", "sofa_trace_sample.json"]:
    path = os.path.join(OUT, name)
    size = os.path.getsize(path)
    print(f"  {name}: {size:,} bytes")
