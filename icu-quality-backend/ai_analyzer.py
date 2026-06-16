# ai_analyzer.py
# 规则引擎判定异常 + LLM 生成质控报告（LLM只做解读，不碰诊疗）

# ---- 指标元数据（与前端 indicators.js 保持同源，真实项目应抽到共享配置）----
INDICATOR_META = {
    "ICU-01": {"name": "ICU床位使用率", "unit": "%", "good": (75, 90), "warn": (60, 95), "dir": "range"},
    "ICU-02": {"name": "ICU医师床位比", "unit": ":1", "good": (0.8, 99), "warn": (0.5, 99), "dir": "higher"},
    "ICU-03": {"name": "ICU护士床位比", "unit": ":1", "good": (3.0, 99), "warn": (2.5, 99), "dir": "higher"},
    "ICU-04": {"name": "APACHEⅡ≥15分收治率", "unit": "%", "good": (50, 100), "warn": (30, 100), "dir": "higher"},
    "ICU-05": {"name": "感染性休克bundle完成率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-06": {"name": "抗菌药物前病原学送检率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-07": {"name": "DVT预防率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-08": {"name": "中重度ARDS俯卧位通气实施率", "unit": "%", "good": (80, 100), "warn": (60, 100), "dir": "higher"},
    "ICU-09": {"name": "ICU镇痛评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-10": {"name": "ICU镇静评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-11": {"name": "ICU患者标化病死指数(SMR)", "unit": "", "good": (0, 1.0), "warn": (0, 1.2), "dir": "lower"},
    "ICU-12": {"name": "非计划气管插管拔管率", "unit": "%", "good": (0, 5), "warn": (0, 10), "dir": "lower"},
    "ICU-13": {"name": "拔管后48h再插管率", "unit": "%", "good": (0, 5), "warn": (0, 12), "dir": "lower"},
    "ICU-14": {"name": "非计划转入ICU率", "unit": "%", "good": (0, 5), "warn": (0, 10), "dir": "lower"},
    "ICU-15": {"name": "转出ICU后48h重返率", "unit": "%", "good": (0, 3), "warn": (0, 6), "dir": "lower"},
    "ICU-16": {"name": "VAP发病率", "unit": "‰", "good": (0, 8), "warn": (0, 14), "dir": "lower"},
    "ICU-17": {"name": "CRBSI发病率", "unit": "‰", "good": (0, 1), "warn": (0, 3.5), "dir": "lower"},
    "ICU-18": {"name": "急性脑损伤意识评估率", "unit": "%", "good": (90, 100), "warn": (70, 100), "dir": "higher"},
    "ICU-19": {"name": "48h内肠内营养启动率", "unit": "%", "good": (80, 100), "warn": (60, 100), "dir": "higher"},
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


# ============================================================
# ICU-06 AI 判定：抗菌药使用目的分类（治疗性 vs 预防性）
# ============================================================

import json
import hashlib
import re
import threading
from datetime import datetime as _dt

# AI 并发控制
_AI_SEMAPHORE = threading.Semaphore(5)

# AI 提示词模板 — 强制 JSON 输出
ABX_PURPOSE_SYSTEM_PROMPT = """你是ICU临床药师，辅助判断住院患者使用抗菌药物的真实目的（治疗性 vs 预防性）。

【判断规则】
- 治疗性：有明确感染证据（临床诊断含感染关键词、体温≥38.5℃、WBC/CRP/PCT显著升高），或临床场景高度指向活动性感染。
- 预防性：围术期短程用药、无感染相关症状体征、炎症指标正常或仅轻微波动、给药次数少且疗程极短。

【输入上下文】
你将收到患者的诊断、手术史、抗菌药名称、疗程小时数、给药次数、炎症指标摘要。

【输出要求】
严格输出以下JSON格式，不得包含任何其他文字：
{"purpose":"治疗性"|"预防性","confidence":0.0-1.0,"reason":"一句话依据（≤50字）"}

其中：
- purpose: 必须是"治疗性"或"预防性"二选一
- confidence: 0.0~1.0，表示你的判定确信度
- reason: 用一句话说明判定依据，引用输入中的关键信息"""


# ============================================================
# 脓毒症早期预警 AI 判定（Sepsis-3 / qSOFA 辅助识别）
# 定位：质控分诊提示，NOT 临床诊疗决策。只判"是否需要临床团队评估"。
# ============================================================

SEPSIS_ALERT_SYSTEM_PROMPT = """你是ICU质控辅助分析助手，依据 Sepsis-3 国际共识与 qSOFA 标准，辅助判断住院患者当前数据是否提示【疑似脓毒症 / 需临床团队尽快评估】。

【判断依据（Sepsis-3 + qSOFA）】
1. qSOFA 三项（每项1分，≥2分提示预后不良、需警惕脓毒症）：
   - 呼吸频率 ≥ 22 次/分
   - 收缩压 ≤ 100 mmHg
   - 意识改变（GCS < 15 / 新发意识障碍）
2. 感染证据：临床诊断含感染关键词、体温 ≥38.3℃ 或 <36℃、WBC异常、PCT/CRP/乳酸显著升高。
3. 器官功能恶化趋势：乳酸 ≥2 mmol/L、少尿、新发或加重的器官功能指标异常。
4. 脓毒性休克警示：在充分液体复苏后仍需升压药维持 MAP≥65 且乳酸>2 —— 但你【不评估是否已复苏、不建议是否用升压药】，仅标记该数据组合为高危。

【风险分级】
- high：qSOFA≥2 且有感染证据，或乳酸≥4，或已出现休克数据组合 —— 提示尽快床旁评估。
- medium：qSOFA=1 伴感染证据，或炎症指标显著升高但 qSOFA 未达标 —— 提示加强监测。
- low：无明确感染证据且生命体征平稳。

【绝对禁止】
- 禁止给出任何诊断结论（不得说"该患者已是脓毒症"）。
- 禁止给出任何治疗/用药/液体复苏/抗菌药建议。
- 你的输出只能是"是否建议临床团队评估"的分诊提示，最终诊断与处置由临床医师负责。

【输出要求】
严格输出以下JSON，不得包含任何其他文字：
{"risk":"high"|"medium"|"low","qsofa":0-3,"suspect_sepsis":true|false,"reason":"一句话依据（≤60字，引用输入关键数据）","action":"建议措辞，仅限'建议临床团队尽快床旁评估'/'建议加强监测与复查'/'暂无预警，常规监测'"}"""


def parse_llm_json(text: str) -> dict | None:
    """
    容错 JSON 解析：剥 markdown 代码块、正则提取首个 {...}、归一中文标点。
    返回解析后的 dict，失败返回 None。
    """
    if not text:
        return None
    text = text.strip()

    # 1. 剥除 ```json / ``` 代码块标记
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")

    # 2. 归一中文标点（LLM 有时用中文引号/冒号）
    text = text.replace("“", '"').replace("”", '"')  # "  "
    text = text.replace("：", ":").replace("，", ",")  # ： ，

    # 3. 正则提取首个 {...} 片段（支持嵌套）
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# AI 重试次数（可配置常量）
AI_MAX_RETRY = 1


def call_llm_json_with_system(system_prompt: str, prompt: str, max_tokens: int = 200) -> dict | None:
    """
    调用 LLM 返回结构化 JSON。
    复用现有 OpenAI client 配置，强制 JSON 输出。
    返回解析后的 dict，失败返回 None。
    """
    import os
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,       # 极低温度，保证判定一致
        max_tokens=max_tokens,
        response_format={"type": "json_object"},  # 强制 JSON
    )
    raw = resp.choices[0].message.content.strip()
    return parse_llm_json(raw)


def call_llm_json(prompt: str) -> dict | None:
    return call_llm_json_with_system(ABX_PURPOSE_SYSTEM_PROMPT, prompt)


# ============================================================
# ai_decision_cache 缓存表
# ============================================================

AI_CACHE_COLLECTION = "ai_decision_cache"


def ensure_ai_cache_collection():
    """
    创建 ai_decision_cache 集合及唯一索引 (hisPid, task)。
    幂等 — 多次调用安全。
    """
    from db import BED_DB_NAMES, get_client
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db[AI_CACHE_COLLECTION]
            # 唯一索引: 同一患者同一任务只判一次
            try:
                coll.create_index(
                    [("hisPid", 1), ("task", 1)],
                    unique=True, background=True,
                    name="idx_hispid_task",
                )
            except Exception:
                pass
            # 辅助索引: 按时间查
            try:
                coll.create_index(
                    [("created_at", -1)],
                    background=True,
                    name="idx_created_at",
                )
            except Exception:
                pass
            break
        except Exception:
            continue


def get_ai_cache(hispid: str, task: str = "abx_purpose") -> dict | None:
    """读取 AI 判定缓存。返回 result 子文档或 None。"""
    from db import BED_DB_NAMES, get_client
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            doc = db[AI_CACHE_COLLECTION].find_one(
                {"hisPid": hispid, "task": task},
                {"result": 1, "_id": 0},
            )
            if doc:
                return doc.get("result")
        except Exception:
            continue
    return None


def set_ai_cache(hispid: str, task: str, result: dict, prompt_snapshot: str):
    """写入 AI 判定缓存。幂等 upsert，缓存命中时直接返回不重调。"""
    from db import BED_DB_NAMES, get_client
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            doc = {
                "hisPid": hispid,
                "task": task,
                "result": result,
                "prompt_snapshot": prompt_snapshot,
                "created_at": _dt.utcnow(),
            }
            db[AI_CACHE_COLLECTION].update_one(
                {"hisPid": hispid, "task": task},
                {"$set": doc},
                upsert=True,
            )
            break
        except Exception:
            continue


def _build_abx_prompt(ctx: dict) -> str:
    """构造抗菌药目的判定提示词"""
    return f"""请判断以下ICU患者使用抗菌药的真实目的。

【患者信息】
诊断：{ctx.get('diagnosis', '未知')}
手术史：{ctx.get('surgery', '无')}
抗菌药：{ctx.get('antibiotics', '未知')}
疗程：{ctx.get('course_hours', '?')} 小时
给药次数：{ctx.get('dose_count', '?')} 次
炎症指标：{ctx.get('inflammation', '未查')}

请按要求输出JSON判定结果。"""


def _build_sepsis_prompt(ctx: dict) -> str:
    """构造脓毒症预警判定提示词（精简版，规则已在 system prompt）"""
    return f"""判断该ICU患者是否疑似脓毒症、是否需评估，按要求输出JSON。

诊断：{ctx.get('diagnosis', '未知')}
T={ctx.get('temperature', '?')}℃ RR={ctx.get('resp_rate', '?')} SBP={ctx.get('sbp', '?')} MAP={ctx.get('map', '?')} 意识={ctx.get('consciousness', '?')}
WBC={ctx.get('wbc', '?')} PCT={ctx.get('pct', '?')} CRP={ctx.get('crp', '?')} 乳酸={ctx.get('lactate', '?')}mmol/L
尿量={ctx.get('urine_output', '?')} 升压药={ctx.get('vasopressor', '?')}"""


def _fallback_sepsis_alert(ctx: dict, reason: str) -> dict:
    return {
        "risk": "medium",
        "qsofa": 0,
        "suspect_sepsis": False,
        "reason": reason[:60],
        "action": "建议加强监测与复查",
        "by": "fallback",
        "need_review": True,
    }


def classify_sepsis_alert_with_ai(ctx: dict) -> dict | None:
    """
    调用 AI 做脓毒症早期预警分诊提示。

    返回:
      {risk, qsofa, suspect_sepsis, reason, action, by, need_review}

    仅用于质控分诊提示，不输出诊断或治疗建议。
    """
    hispid = ctx.get("hisPid", "")
    if not hispid:
        return None

    cache_task = "sepsis_alert"
    cache_key = f"{hispid}:{ctx.get('sample_time') or ctx.get('time') or ''}"
    cached = get_ai_cache(cache_key, cache_task)
    if cached:
        return cached

    acquired = _AI_SEMAPHORE.acquire(timeout=30)
    if not acquired:
        return _fallback_sepsis_alert(ctx, "AI并发已满，需人工复核预警数据")

    try:
        prompt = _build_sepsis_prompt(ctx)
        llm_result = call_llm_json_with_system(SEPSIS_ALERT_SYSTEM_PROMPT, prompt, max_tokens=220)
        if not llm_result:
            retry_prompt = prompt + (
                "\n\n【重要提醒】严格只输出一个 JSON 对象，不要 markdown 代码块，不要解释。"
                "仅输出: {\"risk\":\"high|medium|low\",\"qsofa\":0,\"suspect_sepsis\":false,"
                "\"reason\":\"...\",\"action\":\"...\"}"
            )
            llm_result = call_llm_json_with_system(SEPSIS_ALERT_SYSTEM_PROMPT, retry_prompt, max_tokens=220)

        if not llm_result:
            result = _fallback_sepsis_alert(ctx, "AI解析失败，需人工复核预警数据")
        else:
            risk = str(llm_result.get("risk", "medium")).lower()
            if risk not in {"high", "medium", "low"}:
                risk = "medium"

            try:
                qsofa = int(llm_result.get("qsofa", 0))
                qsofa = max(0, min(3, qsofa))
            except (ValueError, TypeError):
                qsofa = 0

            action = str(llm_result.get("action", "")).strip()
            allowed_actions = {
                "建议临床团队尽快床旁评估",
                "建议加强监测与复查",
                "暂无预警，常规监测",
            }
            if action not in allowed_actions:
                action = {
                    "high": "建议临床团队尽快床旁评估",
                    "medium": "建议加强监测与复查",
                    "low": "暂无预警，常规监测",
                }[risk]

            result = {
                "risk": risk,
                "qsofa": qsofa,
                "suspect_sepsis": bool(llm_result.get("suspect_sepsis", risk != "low")),
                "reason": str(llm_result.get("reason", ""))[:60],
                "action": action,
                "by": "ai",
                "need_review": risk in {"high", "medium"},
            }

        set_ai_cache(cache_key, cache_task, result, prompt)
        return result
    except Exception:
        return _fallback_sepsis_alert(ctx, "AI调用异常，需人工复核预警数据")
    finally:
        _AI_SEMAPHORE.release()


def classify_abx_with_ai(ctx: dict) -> dict | None:
    """
    调用 AI 判定抗菌药使用目的（治疗性 vs 预防性）。

    ctx 需包含:
      - hisPid: 患者住院号（缓存键）
      - diagnosis: 临床诊断
      - surgery: 手术史摘要
      - antibiotics: 抗菌药名称
      - course_hours: 疗程小时数
      - dose_count: 给药次数
      - inflammation: 炎症指标摘要

    流程:
      1. 查 ai_decision_cache，命中直接返回
      2. 未命中 → 调 LLM（受并发上限 Semaphore(5) 控制）
      3. 解析失败 → 重试一次（AI_MAX_RETRY=1），重试 prompt 追加强约束
      4. 两次都失败 → fallback 兜底
      5. 结果写缓存

    返回: {purpose, confidence, reason, by: "ai"|"fallback", need_review: bool} 或 None
    """
    hispid = ctx.get("hisPid", "")
    if not hispid:
        return None

    # Step 1: 查缓存
    cached = get_ai_cache(hispid, "abx_purpose")
    if cached:
        return cached

    # Step 2: 调 LLM（并发控制）
    acquired = _AI_SEMAPHORE.acquire(timeout=30)
    if not acquired:
        return {"purpose": "治疗性", "confidence": 0.3,
                "reason": "AI并发已满,保守归为治疗", "by": "fallback",
                "need_review": True}

    try:
        prompt = _build_abx_prompt(ctx)
        llm_result = call_llm_json(prompt)

        # Step 3: 解析失败 → 重试一次
        if not llm_result:
            retry_prompt = prompt + (
                "\n\n【重要提醒】严格只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。"
                "仅输出: {\"purpose\":\"...\",\"confidence\":...,\"reason\":\"...\"}"
            )
            llm_result = call_llm_json(retry_prompt)

        # Step 4: 判定结果
        course_hours = ctx.get("course_hours", 0)
        dose_count = ctx.get("dose_count", 0)
        antibiotics = ctx.get("antibiotics", "")

        if not llm_result:
            result = {
                "purpose": "治疗性", "confidence": 0.3,
                "reason": f"AI解析失败兜底(疗程{course_hours:.0f}h/{dose_count}次/{antibiotics[:30]})",
                "by": "fallback", "need_review": True,
            }
        else:
            purpose_raw = str(llm_result.get("purpose", "治疗性"))
            if "预防" in purpose_raw:
                purpose = "预防性"
            else:
                purpose = "治疗性"

            try:
                conf = float(llm_result.get("confidence", 0.5))
                conf = max(0.0, min(1.0, conf))
            except (ValueError, TypeError):
                conf = 0.5

            reason = str(llm_result.get("reason", ""))[:200]
            result = {
                "purpose": purpose,
                "confidence": conf,
                "reason": reason,
                "by": "ai",
                "need_review": conf < 0.6,
            }

        # Step 5: 写缓存
        set_ai_cache(hispid, "abx_purpose", result, prompt)

        return result

    except Exception:
        course_hours = ctx.get("course_hours", 0)
        dose_count = ctx.get("dose_count", 0)
        antibiotics = ctx.get("antibiotics", "")
        return {"purpose": "治疗性", "confidence": 0.3,
                "reason": f"AI调用异常兜底(疗程{course_hours:.0f}h/{dose_count}次/{antibiotics[:30]})",
                "by": "fallback", "need_review": True}
    finally:
        _AI_SEMAPHORE.release()


def get_all_ai_decisions(dept_codes: list = None, period_start: str = None,
                         period_end: str = None, min_confidence: float = None,
                         limit: int = 500) -> list:
    """
    查询 ai_decision_cache 中的 AI 判定记录。
    支持按科室、时间范围、置信度阈值筛选。
    用于前端 AI 决策复核界面。
    """
    from db import BED_DB_NAMES, get_client
    results = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            query = {"task": "abx_purpose"}
            if period_start:
                query["created_at"] = query.get("created_at", {})
                query["created_at"]["$gte"] = _dt.fromisoformat(period_start)
            if period_end:
                query["created_at"] = query.get("created_at", {})
                query["created_at"]["$lte"] = _dt.fromisoformat(
                    f"{period_end}-31" if len(period_end) == 7 else period_end)
            if min_confidence is not None:
                query["result.confidence"] = {"$lte": float(min_confidence)}

            docs = list(db[AI_CACHE_COLLECTION].find(
                query,
                {"hisPid": 1, "task": 1, "result": 1, "created_at": 1, "_id": 0},
            ).sort("created_at", -1).limit(limit))
            if docs:
                results = docs
                break
        except Exception:
            continue

    # 格式化返回
    return [{
        "hisPid": d["hisPid"],
        "task": d["task"],
        "purpose": d.get("result", {}).get("purpose", ""),
        "confidence": d.get("result", {}).get("confidence", 0),
        "reason": d.get("result", {}).get("reason", ""),
        "decided_by": d.get("result", {}).get("by", "ai"),
        "created_at": d.get("created_at").isoformat() if d.get("created_at") else "",
    } for d in results]


def override_ai_decision(hispid: str, purpose: str, reason: str,
                         overridden_by: str = "主任") -> dict:
    """
    人工推翻 AI 判定。
    写回 ai_decision_cache，标记 by='manual_override'。
    返回更新后的文档。
    """
    from db import BED_DB_NAMES, get_client
    result = {
        "purpose": purpose,
        "confidence": 1.0,
        "reason": f"[人工推翻({overridden_by})] {reason}",
        "by": "manual_override",
    }
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            doc = {
                "hisPid": hispid,
                "task": "abx_purpose",
                "result": result,
                "prompt_snapshot": f"manual_override by {overridden_by}",
                "created_at": _dt.utcnow(),
            }
            db[AI_CACHE_COLLECTION].update_one(
                {"hisPid": hispid, "task": "abx_purpose"},
                {"$set": doc},
                upsert=True,
            )
            return {"success": True, "hisPid": hispid, "result": result}
        except Exception as e:
            continue
    return {"success": False, "error": "Database not available"}
