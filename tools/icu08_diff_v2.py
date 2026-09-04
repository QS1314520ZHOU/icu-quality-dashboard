"""
ICU-08 before/after 患者级 diff（E-1d 验证）。
用法: python tools/icu08_diff_v2.py
产出: tools/out/icu08_arm_fix_v2.md
"""
import sys, os, io, json
from datetime import datetime as dt, timedelta
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join('.', 'icu-quality-backend'))

from bson import ObjectId
from db import iter_bed_dbs, _pf_ratio_from_bedsides

# 取一个 DB 连接
for _, db in iter_bed_dbs():
    sc = db
    break

# ---- 配置 ----
DEPT = "3439"
MONTHS = [
    ("2026-06", dt(2026, 6, 1), dt(2026, 6, 30, 23, 59, 59)),
    ("2026-07", dt(2026, 7, 1), dt(2026, 7, 31, 23, 59, 59)),
    ("2026-08", dt(2026, 8, 1), dt(2026, 8, 31, 23, 59, 59)),
]

# ---- BEFORE 版本：旧逻辑（INVASIVE_ROUTES + is_invasive_by_o2route + 60min） ----
def run_before(start_dt, end_dt):
    """旧逻辑：60min 窗口，INVASIVE_ROUTES 子串匹配，PEEP 全部臂都需要。"""
    from config.o2_route_map import _SINGLE_MAP, _split_routes, _SOFATIER, _ICU08TIER, _AIRWAY_ADVANCED

    # 旧的 INVASIVE_ROUTES
    INVASIVE_ROUTES = {"管辅", "切辅", "管氧", "切氧", "管文", "切文", "管高", "切高", "有创"}
    NON_INVASIVE_KW = {"无创"}

    den_patients = []
    seen_pids = set()

    bgas = list(sc.bGATemp.find(
        {"deptCode": DEPT,
         "eventExe.startTime": {"$gte": start_dt, "$lte": end_dt},
         "bedsides": {"$elemMatch": {"code": {"$in": ["param_bg_P/Fratio", "param_bg_OI", "param_bg_po2"]}, "valid": "valid"}}},
        {"eventExe.pid": 1, "eventExe.startTime": 1, "bedsides": 1, "mrn": 1},
    ).sort("eventExe.startTime", 1))

    funnel_bga = len(bgas)
    funnel_pids = set(b['eventExe']['pid'] for b in bgas)
    funnel_pf150 = set()

    for bga in bgas:
        pid = bga["eventExe"]["pid"]
        if pid in seen_pids:
            continue
        pf_time = bga["eventExe"]["startTime"]
        pf_ratio = _pf_ratio_from_bedsides(bga.get("bedsides", []))
        if pf_ratio is None:
            continue
        if pf_ratio < 150:
            funnel_pf150.add(pid)

        win = pf_time - timedelta(minutes=60)  # 旧逻辑固定 60min

        # PEEP（旧逻辑：所有臂都需要）
        peep_doc = sc.bedside.find_one(
            {"pid": pid, "code": "param_vent_peep", "valid": True,
             "time": {"$gte": win, "$lte": pf_time}},
            {"strVal": 1}, sort=[("time", -1)])
        if not peep_doc:
            continue
        try:
            peep_val = float(peep_doc.get("strVal", "0"))
        except (ValueError, TypeError):
            continue

        # o2route（旧逻辑：子串匹配）
        o2_doc = sc.bedside.find_one(
            {"pid": pid, "code": "param_XiYangTuJing", "valid": True,
             "time": {"$gte": win, "$lte": pf_time}},
            {"strVal": 1}, sort=[("time", -1)])
        o2_raw = o2_doc.get("strVal", "") if o2_doc else ""

        # 旧的判定逻辑
        arm = None
        routes = set(r.strip() for r in o2_raw.replace("、", ",").replace("，", ",").replace("/", ",").replace("+", ",").replace(" ", "").split(",") if r.strip())
        o2_invasive = bool(routes & INVASIVE_ROUTES)
        o2_noninv = any("无创" in r for r in routes)
        o2_hfnc = any("高流量" in r for r in routes)

        if o2_invasive and peep_val >= 5.0 and pf_ratio < 150.0:
            arm = "有创"
        elif o2_noninv and peep_val >= 5.0 and pf_ratio <= 200.0:
            arm = "无创"
        elif o2_hfnc:
            flow_doc = sc.bedside.find_one(
                {"pid": pid, "code": "param_吸氧流速", "valid": True,
                 "time": {"$gte": win, "$lte": pf_time}},
                {"strVal": 1}, sort=[("time", -1)])
            flow_val = 0
            if flow_doc:
                try:
                    fv = flow_doc.get("strVal", "0")
                    fv = fv.replace("L/min", "").replace("l/min", "").strip()
                    flow_val = float(fv)
                except (ValueError, TypeError):
                    pass
            if flow_val >= 30.0 and pf_ratio <= 200.0:
                arm = "高流量"

        if not arm:
            continue

        seen_pids.add(pid)
        den_patients.append({
            "pid": pid, "arm": arm, "o2route": o2_raw,
            "pf_ratio": pf_ratio, "peep": peep_val,
        })

    return {
        "bga_count": funnel_bga,
        "patient_count": len(funnel_pids),
        "pf150_count": len(funnel_pf150),
        "den_count": len(den_patients),
        "patients": den_patients,
    }


# ---- AFTER 版本：E-1 修复后逻辑 ----
def run_after(start_dt, end_dt):
    """新逻辑：480min LOCF 窗口，o2_route_map 全等映射，PEEP 仅 invasive/noninvasive。"""
    from config.o2_route_map import classify_o2_route
    from config.indicator_windows import ICU08_PAIR_MODE

    window_min = 480 if ICU08_PAIR_MODE == "locf_8h" else 60

    den_patients = []
    seen_pids = set()
    unknown_hits = Counter()

    bgas = list(sc.bGATemp.find(
        {"deptCode": DEPT,
         "eventExe.startTime": {"$gte": start_dt, "$lte": end_dt},
         "bedsides": {"$elemMatch": {"code": {"$in": ["param_bg_P/Fratio", "param_bg_OI", "param_bg_po2"]}, "valid": "valid"}}},
        {"eventExe.pid": 1, "eventExe.startTime": 1, "bedsides": 1, "mrn": 1},
    ).sort("eventExe.startTime", 1))

    funnel_bga = len(bgas)
    funnel_pids = set(b['eventExe']['pid'] for b in bgas)
    funnel_pf150 = set()

    for bga in bgas:
        pid = bga["eventExe"]["pid"]
        if pid in seen_pids:
            continue
        pf_time = bga["eventExe"]["startTime"]
        pf_ratio = _pf_ratio_from_bedsides(bga.get("bedsides", []))
        if pf_ratio is None:
            continue
        if pf_ratio < 150:
            funnel_pf150.add(pid)

        win = pf_time - timedelta(minutes=window_min)

        # o2_route_map 分类
        o2_doc = sc.bedside.find_one(
            {"pid": pid, "code": "param_XiYangTuJing", "valid": True,
             "time": {"$gte": win, "$lte": pf_time}},
            {"strVal": 1}, sort=[("time", -1)])
        o2_raw = o2_doc.get("strVal", "") if o2_doc else ""
        o2_cls = classify_o2_route(o2_raw)
        icu08_arm = o2_cls["icu08_arm"]

        if o2_cls["unknown"]:
            for u in o2_cls["unknown"]:
                unknown_hits[u] += 1

        # PEEP — 仅 invasive 和 noninvasive
        peep_val = None
        if icu08_arm in ("invasive", "noninvasive"):
            peep_doc = sc.bedside.find_one(
                {"pid": pid, "code": "param_vent_peep", "valid": True,
                 "time": {"$gte": win, "$lte": pf_time}},
                {"strVal": 1}, sort=[("time", -1)])
            if not peep_doc:
                continue
            try:
                peep_val = float(peep_doc.get("strVal", "0"))
            except (ValueError, TypeError):
                continue

        arm = None
        if icu08_arm == "invasive" and peep_val is not None and peep_val >= 5.0 and pf_ratio < 150.0:
            arm = "有创"
        elif icu08_arm == "noninvasive" and peep_val is not None and peep_val >= 5.0 and pf_ratio <= 200.0:
            arm = "无创"
        elif icu08_arm == "hfnc":
            flow_doc = sc.bedside.find_one(
                {"pid": pid, "code": "param_吸氧流速", "valid": True,
                 "time": {"$gte": win, "$lte": pf_time}},
                {"strVal": 1}, sort=[("time", -1)])
            flow_val = 0
            if flow_doc:
                try:
                    fv = flow_doc.get("strVal", "0")
                    fv = fv.replace("L/min", "").replace("l/min", "").strip()
                    flow_val = float(fv)
                except (ValueError, TypeError):
                    pass
            if flow_val >= 30.0 and pf_ratio <= 200.0:
                arm = "高流量"

        if not arm:
            continue

        seen_pids.add(pid)
        den_patients.append({
            "pid": pid, "arm": arm, "o2route": o2_raw,
            "pf_ratio": pf_ratio, "peep": peep_val,
        })

    return {
        "bga_count": funnel_bga,
        "patient_count": len(funnel_pids),
        "pf150_count": len(funnel_pf150),
        "den_count": len(den_patients),
        "patients": den_patients,
        "unknown_hits": unknown_hits,
    }


# ---- 主流程 ----
lines = []
lines.append("# ICU-08 修复患者级验证 v2\n")
lines.append(f"科室: {DEPT} | 配对窗口: before=60min, after=8h(LOCf_8h)\n")

all_unknown = Counter()

for label, start_dt, end_dt in MONTHS:
    lines.append(f"\n## {label}\n")

    before = run_before(start_dt, end_dt)
    after = run_after(start_dt, end_dt)

    # 漏斗
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|---|")
    lines.append(f"| bGA 记录条数 | {after['bga_count']} |")
    lines.append(f"| 涉及患者数 | {after['patient_count']} |")
    lines.append(f"| P/F<150 患者数 | {after['pf150_count']} |")
    lines.append(f"| before 分母 | {before['den_count']} |")
    lines.append(f"| after 分母 | {after['den_count']} |")

    # 患者级 diff
    before_pids = {p["pid"]: p for p in before["patients"]}
    after_pids = {p["pid"]: p for p in after["patients"]}

    added = []
    for pid, p in after_pids.items():
        if pid not in before_pids:
            added.append(p)

    removed = []
    for pid, p in before_pids.items():
        if pid not in after_pids:
            removed.append(p)

    lines.append(f"\n### 新增 pid（after 有 before 没有）: {len(added)} 人\n")
    if added:
        lines.append("| pid | o2route | P/F | 命中臂 | PEEP |")
        lines.append("|-----|---------|-----|--------|------|")
        for p in added:
            peep_str = f"{p['peep']:.0f}" if p['peep'] is not None else "缺失"
            lines.append(f"| {p['pid'][:12]}... | {p['o2route']} | {p['pf_ratio']:.0f} | {p['arm']} | {peep_str} |")
    else:
        lines.append("（空集）\n")

    lines.append(f"\n### 消失 pid（before 有 after 没有）: {len(removed)} 人\n")
    if removed:
        lines.append("| pid | o2route | P/F | 旧命中臂 | 被排除原因 |")
        lines.append("|-----|---------|-----|----------|-----------|")
        for p in removed:
            # 分析被排除原因：重跑 after 逻辑看哪个环节失败
            reason = "见分析"
            lines.append(f"| {p['pid'][:12]}... | {p['o2route']} | {p['pf_ratio']:.0f} | {p['arm']} | {reason} |")
    else:
        lines.append("（空集）\n")

    # unknown 命中
    all_unknown.update(after.get("unknown_hits", {}))
    lines.append(f"\n### unknown 命中: {sum(after.get('unknown_hits', {}).values())} 次\n")
    if after.get("unknown_hits"):
        for val, cnt in after["unknown_hits"].most_common():
            lines.append(f"  - `{val}`: {cnt} 次")

    # 结论行
    lines.append(f'\n> 2026-{label[5:]}：分母 before {before["den_count"]} 人 after {after["den_count"]} 人，'
                 f'新增 {len(added)} 人，消失 {len(removed)} 人，'
                 f'unknown 命中 {sum(after.get("unknown_hits", {}).values())} 次，'
                 f'漏斗为 血气 {after["bga_count"]} 条 / 患者 {after["patient_count"]} 人 / '
                 f'P/F<150 {after["pf150_count"]} 人 / 入分母 {after["den_count"]} 人\n')

# ---- 第 4 步：unknown 全量审计 ----
lines.append("\n## 第 4 步：unknown 全量审计\n")
if all_unknown:
    for val, cnt in all_unknown.most_common():
        lines.append(f"  - `{val}`: {cnt} 次")
else:
    lines.append("无 unknown 命中。\n")

# 核对四个值
lines.append("\n### 关键值核对\n")
from config.o2_route_map import _SINGLE_MAP
for v in ["T管", "带管自主", "有创", "鼻罩"]:
    status = "✓ 已在映射表" if v in _SINGLE_MAP else "✗ 不在映射表"
    lines.append(f"  - `{v}`: {status}")

# ---- 第 5 步 ----
lines.append("\n## 第 5 步：新漏人点核查\n")

# 5.1 PEEP strVal 带单位
lines.append("### 5.1 PEEP strVal 取值\n")
peep_vals = list(sc.bedside.distinct("strVal", {"code": "param_vent_peep", "valid": True}))
peep_vals_str = [str(v) for v in peep_vals if v is not None]
has_unit = [v for v in peep_vals_str if not v.replace(".", "").replace("-", "").isdigit()]
lines.append(f"distinct strVal 数: {len(peep_vals_str)}")
if has_unit:
    lines.append(f"带单位的取值（前30）: {has_unit[:30]}")
    lines.append("→ **需加清洗**")
else:
    lines.append("无带单位取值，当前 float() 转换安全。")

# 5.2 HFNC 流速覆盖率
lines.append("\n### 5.2 HFNC 流速覆盖率\n")
# 统计 o2route=hfnc 的血气时刻中，同窗口有流速的比例
hfnc_total = 0
hfnc_with_flow = 0
for month_label, start_dt, end_dt in MONTHS:
    bgas = list(sc.bGATemp.find(
        {"deptCode": DEPT,
         "eventExe.startTime": {"$gte": start_dt, "$lte": end_dt},
         "bedsides": {"$elemMatch": {"code": {"$in": ["param_bg_P/Fratio", "param_bg_OI", "param_bg_po2"]}, "valid": "valid"}}},
        {"eventExe.pid": 1, "eventExe.startTime": 1, "bedsides": 1},
    ))
    for bga in bgas:
        pid = bga["eventExe"]["pid"]
        pf_time = bga["eventExe"]["startTime"]
        win = pf_time - timedelta(minutes=480)
        o2_doc = sc.bedside.find_one(
            {"pid": pid, "code": "param_XiYangTuJing", "valid": True,
             "time": {"$gte": win, "$lte": pf_time}},
            {"strVal": 1}, sort=[("time", -1)])
        if not o2_doc or "strVal" not in o2_doc:
            continue
        from config.o2_route_map import classify_o2_route
        cls = classify_o2_route(o2_doc["strVal"])
        if cls["icu08_arm"] != "hfnc":
            continue
        hfnc_total += 1
        flow_doc = sc.bedside.find_one(
            {"pid": pid, "code": "param_吸氧流速", "valid": True,
             "time": {"$gte": win, "$lte": pf_time}},
            {"strVal": 1}, sort=[("time", -1)])
        if flow_doc and "strVal" in flow_doc:
            hfnc_with_flow += 1

if hfnc_total > 0:
    lines.append(f"HFNC 血气时刻: {hfnc_total}，有流速: {hfnc_with_flow} ({hfnc_with_flow/hfnc_total*100:.1f}%)")
else:
    lines.append("无 HFNC 血气时刻。")

# ---- 第 6 步 ----
lines.append("\n## 第 6 步：关键词表四项确认\n")
from config.o2_route_map import _SINGLE_MAP

checks = [
    # 高频振荡通气应归为有创(IMV)，不是无创
    ("高频→IMV/invasive", _SINGLE_MAP.get("高频") == ("IMV", "invasive")),
    # 文丘里在映射表中且为NONE/none，不再通过子串匹配与管文/切文冲突
    ("文丘里→NONE/none(全等匹配无冲突)", _SINGLE_MAP.get("文丘里") == ("NONE", "none")),
    ("T管 不落 unknown", "T管" in _SINGLE_MAP),
    ("带管自主 不落 unknown", "带管自主" in _SINGLE_MAP),
    # 单字'鼻'在映射表中为NONE/none，全等匹配不会误中鼻塞/鼻导管/鼻罩
    ("鼻→NONE/none(全等匹配)", _SINGLE_MAP.get("鼻") == ("NONE", "none")),
]
for desc, ok in checks:
    status = "✓ 已消灭" if ok else "✗ 仍存在"
    lines.append(f"  - {desc}: {status}")

# ---- 写出 ----
output = "\n".join(lines)
out_path = os.path.join(".", "tools", "out", "icu08_arm_fix_v2.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(output)
print(f"已写入 {out_path}")
print(f"共 {len(lines)} 行")
