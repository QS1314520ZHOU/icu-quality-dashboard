# ai_analyzer.py
# 规则引擎判定异常 + LLM 生成质控报告（LLM只做解读，不碰诊疗）

# ---- 指标元数据（与前端 indicators.js 保持同源，真实项目应抽到共享配置）----
INDICATOR_META = {
    "ICU-01": {"name": "ICU床位使用率", "unit": "%", "good": (75, 85), "warn": (60, 95), "dir": "range"},
    "ICU-02": {"name": "ICU医师床位比", "unit": ":1", "good": (0.8, 99), "warn": (0.5, 99), "dir": "higher"},
    "ICU-03": {"name": "ICU护士床位比", "unit": ":1", "good": (2.5, 99), "warn": (2.0, 99), "dir": "higher"},
    "ICU-04": {"name": "APACHEⅡ≥15分收治率", "unit": "%", "good": (50, 100), "warn": (30, 100), "dir": "higher"},
    "ICU-05": {"name": "感染性休克bundle完成率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-06": {"name": "抗菌药物前病原学送检率", "unit": "%", "good": (90, 100), "warn": (50, 100), "dir": "higher"},
    "ICU-07": {"name": "DVT预防率", "unit": "%", "good": (85, 100), "warn": (60, 100), "dir": "higher"},
    "ICU-08": {"name": "中重度ARDS俯卧位通气实施率", "unit": "%", "good": (80, 100), "warn": (50, 100), "dir": "higher"},
    "ICU-09": {"name": "ICU镇痛评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-10": {"name": "ICU镇静评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-11": {"name": "ICU患者标化病死指数(SMR)", "unit": "", "good": (0, 1.0), "warn": (0, 1.2), "dir": "lower"},
    "ICU-12": {"name": "非计划气管插管拔管率", "unit": "%", "good": (0, 5), "warn": (0, 10), "dir": "lower"},
    "ICU-13": {"name": "拔管后48h再插管率", "unit": "%", "good": (0, 5), "warn": (0, 12), "dir": "lower"},
    "ICU-14": {"name": "非计划转入ICU率", "unit": "%", "good": (0, 5), "warn": (0, 10), "dir": "lower"},
    "ICU-15": {"name": "转出ICU后48h重返率", "unit": "%", "good": (0, 3), "warn": (0, 6), "dir": "lower"},
    "ICU-16": {"name": "VAP发病率", "unit": "‰", "good": (0, 8), "warn": (0, 15), "dir": "lower"},
    "ICU-17": {"name": "CRBSI发病率", "unit": "‰", "good": (0, 2), "warn": (0, 5), "dir": "lower"},
    "ICU-18": {"name": "急性脑损伤意识评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-19": {"name": "48h内肠内营养启动率", "unit": "%", "good": (80, 100), "warn": (50, 100), "dir": "higher"},
}

# 已知的指标关联关系（用于归因提示，不是因果断言）
CORRELATIONS = [
    {
        "trigger": "ICU-16", "related": "ICU-06",
        "hint": "VAP发病率上升常与病原学送检/感控流程依从性下降相关"
    },
    {
        "trigger": "ICU-17", "related": "ICU-06",
        "hint": "CRBSI上升提示导管置入与维护流程可能存在问题"
    },
]


def detect_abnormal(values: dict) -> list:
    """规则引擎：纯确定性逻辑判定每个指标状态，不依赖LLM"""
    results = []
    for code, val in values.items():
        meta = INDICATOR_META.get(code)
        if not meta or val is None:
            continue
        status = _eval_status(meta, val)
        if status != "good":
            results.append({
                "code": code, "name": meta["name"],
                "value": val, "unit": meta["unit"], "level": status,
            })
    return results


def _eval_status(meta, val) -> str:
    g_lo, g_hi = meta["good"]
    w_lo, w_hi = meta["warn"]
    if g_lo <= val <= g_hi:
        return "good"
    if w_lo <= val <= w_hi:
        return "warn"
    return "danger"


def build_attribution(abnormal: list, values: dict) -> list:
    """基于预设关联关系，给异常指标补充归因线索（确定性，不靠LLM瞎猜）"""
    abnormal_codes = {a["code"] for a in abnormal}
    hints = []
    for rel in CORRELATIONS:
        if rel["trigger"] in abnormal_codes:
            related_val = values.get(rel["related"])
            hints.append({
                "trigger": rel["trigger"],
                "related": rel["related"],
                "related_value": related_val,
                "hint": rel["hint"],
            })
    return hints


def build_prompt(period: str, abnormal: list, hints: list, all_good_count: int) -> str:
    """构造给LLM的prompt——把确定性结论喂进去，约束它只做翻译解读"""
    abnormal_txt = "\n".join(
        f"- {a['name']}({a['code']}): {a['value']}{a['unit']}，状态：{'预警' if a['level']=='warn' else '严重异常'}"
        for a in abnormal
    ) or "无异常指标"

    hints_txt = "\n".join(
        f"- {h['trigger']} 与 {h['related']}(当前值{h['related_value']})：{h['hint']}"
        for h in hints
    ) or "无关联线索"

    return f"""你是医院重症医学科的质控数据分析助手。以下是 {period} 的ICU质控指标分析结果，请基于这些【已经判定好的确定性结论】生成一段简洁、专业的中文质控总结报告。

【异常指标（系统已判定，请勿改动判定结论）】
{abnormal_txt}

【指标关联线索（供归因参考，仅为统计关联，非因果结论）】
{hints_txt}

【正常指标数量】{all_good_count} 项

请严格遵守以下要求：
1. 只对上述数据做解读和归因提示，不要编造未提供的数据或指标。
2. 【绝对禁止】给出任何针对具体患者的临床诊疗建议、用药建议或治疗方案。
3. 可以提出"流程层面"的管理改进方向（如建议核查某项流程依从性），但措辞应为"建议核查/关注"，不可下定论。
4. 归因时必须说明这是"统计关联，需临床团队进一步核实"，不可断言因果。
5. 报告控制在150字以内，语气客观专业。

请输出报告："""


# ---- LLM 调用（以 OpenAI 兼容接口为例，可换成你自己的模型）----
def call_llm(prompt: str) -> str:
    import os
    from openai import OpenAI  # pip install openai

    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "你是严谨的医疗质控数据分析助手，绝不提供临床诊疗建议。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,  # 低温度，减少发挥
        max_tokens=400,
    )
    return resp.choices[0].message.content.strip()


def analyze(period: str, values: dict) -> dict:
    """对外总入口"""
    abnormal = detect_abnormal(values)
    hints = build_attribution(abnormal, values)
    good_count = sum(1 for c, v in values.items()
                     if c in INDICATOR_META and v is not None
                     and _eval_status(INDICATOR_META[c], v) == "good")
    prompt = build_prompt(period, abnormal, hints, good_count)

    try:
        summary = call_llm(prompt)
    except Exception as e:
        # LLM 挂了也不能让看板崩，降级成规则文本
        summary = _fallback_summary(abnormal, good_count)

    return {"summary": summary, "abnormal": abnormal, "hints": hints}


def _fallback_summary(abnormal: list, good_count: int) -> str:
    """LLM不可用时的兜底（纯规则生成，不依赖AI）"""
    if not abnormal:
        return f"本期共 {good_count} 项指标全部达标，整体平稳。"
    names = "、".join(f"{a['name']}({a['value']}{a['unit']})" for a in abnormal)
    return f"本期 {good_count} 项达标，{len(abnormal)} 项需关注：{names}。建议质控团队核查相关流程依从性。"
