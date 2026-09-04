"""
氧疗途径映射表。
基于需求文档 7.1 表格逐行填入，一行不漏。
改这个映射会影响 ICU-08 分母(呼吸臂)和 SOFA/SOFA-2 呼吸分项。

三列:
  classic_advanced - 经典 SOFA 1996 是否算高级呼吸支持
  sofa2_advanced  - SOFA-2 2025 是否算高级呼吸支持
  icu08_arm       - ICU-08 ARDS 俯卧位分臂(invasive/noninvasive/hfnc/none)
"""
from __future__ import annotations

import collections
from typing import Optional

# ============================================================
# 1. 单值映射表 (需求文档 7.1 逐行)
# ============================================================
# 值: (classic_advanced, sofa2_advanced, icu08_arm)
# _AIRWAY = 运行时根据 ARTIFICIAL_AIRWAY_AS_ADVANCED 判定

_AIRWAY = "_AIRWAY"

# ⚠️ 全等匹配，禁止子串匹配。
# 理由：无 是 无创 的子串，鼻 会命中鼻罩鼻塞鼻导管，
#       高频 是 HFOV 属有创，文丘里 与 管文切文 自相矛盾。
_ROUTE_TABLE: dict[str, tuple[Optional[bool], Optional[bool], str]] = {
    # ---- 有创机械通气 (管辅/切辅/有创) ----
    # classic_advanced=✅, sofa2_advanced=✅, icu08_arm=invasive
    "管辅":       (_AIRWAY,  True,     "invasive"),
    "切辅":       (_AIRWAY,  True,     "invasive"),
    "有创":       (True,     True,     "invasive"),

    # ---- 无创通气 (无创/无创呼吸机) ----
    # classic_advanced=✅, sofa2_advanced=✅, icu08_arm=noninvasive
    "无创":       (True,     True,     "noninvasive"),
    "无创呼吸机": (True,     True,     "noninvasive"),

    # ---- 高流量 (高流量/管高/切高) ----
    # classic_advanced=❌, sofa2_advanced=✅, icu08_arm=hfnc
    # HFNC 在经典 SOFA 中不算高级支持，在 SOFA-2 中算
    "高流量":     (False,    True,     "hfnc"),
    "管高":       (False,    True,     "hfnc"),
    "切高":       (False,    True,     "hfnc"),

    # ---- 有创但非高级支持 (管氧/切氧/管文/切文/T管/带管自主) ----
    # classic_advanced=❌, sofa2_advanced=❌, icu08_arm=invasive
    "管氧":       (False,    False,    "invasive"),
    "切氧":       (False,    False,    "invasive"),
    "管文":       (False,    False,    "invasive"),
    "切文":       (False,    False,    "invasive"),
    "T管":        (False,    False,    "invasive"),
    "带管自主":   (False,    False,    "invasive"),

    # ---- 普通氧疗/无支持 (无/自主呼吸) ----
    # classic_advanced=❌, sofa2_advanced=❌, icu08_arm=none
    "无":         (False,    False,    "none"),
    "自主呼吸":   (False,    False,    "none"),

    # ---- 普通氧疗/无支持 (鼻导管/鼻塞/面罩/鼻罩/箱氧) ----
    # classic_advanced=❌, sofa2_advanced=❌, icu08_arm=none
    "鼻导管":     (False,    False,    "none"),
    "鼻塞":       (False,    False,    "none"),
    "面罩":       (False,    False,    "none"),
    "鼻罩":       (False,    False,    "none"),
    "箱氧":       (False,    False,    "none"),

    # ---- 以下为历史数据中出现过的补充值 ----
    # 均为普通氧疗/无高级支持
    "储氧面罩":   (False,    False,    "none"),
    "储氧":       (False,    False,    "none"),
    "面罩吸氧":   (False,    False,    "none"),
    "鼻氧":       (False,    False,    "none"),
    "鼻管辅":     (False,    False,    "none"),
    "低流量":     (False,    False,    "none"),
    "低流量用氧": (False,    False,    "none"),
    "低流量箱氧": (False,    False,    "none"),
    "未吸氧":     (False,    False,    "none"),
    "拒绝":       (False,    False,    "none"),
    "拒绝吸氧":   (False,    False,    "none"),
    "暂停吸氧":   (False,    False,    "none"),
    "文丘里":     (False,    False,    "none"),
    "球囊":       (False,    False,    "none"),
    "呼吸球囊":   (False,    False,    "none"),
    "球囊通气":   (False,    False,    "none"),
    "简易呼吸器": (False,    False,    "none"),
    "家用呼吸机": (False,    False,    "none"),
    "家用":       (False,    False,    "none"),

    # ---- 高频相关 ----
    "无创高频":   (False,    True,     "hfnc"),     # 无创高频→HFNC
    "高频":       (True,     True,     "invasive"),  # 高频振荡通气 HFOV→有创

    # ---- 单字兜底 ----
    "鼻":         (False,    False,    "none"),
}

# 分隔符(实际数据中出现过的全部)
_SPLIT_CHARS = set("、，/+ ")

# 优先级: ECMO > IMV > NIV > HFNC > NONE
_CLASSIC_TIER = {True: 3, False: 0}           # advanced=3, not advanced=0
_SOFATIER     = {"ECMO": 6, "IMV": 5, "NIV": 4, "CPAP": 3, "BIPAP": 3, "HFNC": 2, "NONE": 1}
_ICU08TIER    = {"invasive": 3, "noninvasive": 2, "hfnc": 1, "none": 0}

# 模块级计数器: 记录未知取值次数，供阶段 9 打印
_unknown_counter: collections.Counter = collections.Counter()


def _split_routes(raw: str) -> list[str]:
    """拆分组合值,去空,保序。"""
    if not raw:
        return []
    s = raw.strip()
    for ch in _SPLIT_CHARS:
        s = s.replace(ch, ",")
    return [x.strip() for x in s.split(",") if x.strip()]


def classify_o2_route(
    raw: str,
    airway_as_advanced: bool = False,
    hfnc_as_advanced_classic: bool = False,
    hfnc_as_advanced_sofa2: bool = True,
) -> dict:
    """
    对单条 param_XiYangTuJing 原始值做三列分类。

    参数:
        raw:                    原始氧疗途径字符串
        airway_as_advanced:     人工气道(管辅/切辅)是否算高级支持
        hfnc_as_advanced_classic: 经典 SOFA 是否把 HFNC 算高级支持
        hfnc_as_advanced_sofa2:   SOFA-2 是否把 HFNC 算高级支持

    返回:
        classic_advanced: bool 或 None(未知值返回 None)
        sofa2_advanced:  bool 或 None(未知值返回 None)
        icu08_arm:       str (invasive/noninvasive/hfnc/none/unknown)
        unknown_tokens:  list (未在映射表中的原始值)
    """
    parts = _split_routes(raw)
    if not parts:
        return {
            "classic_advanced": False,
            "sofa2_advanced": False,
            "icu08_arm": "none",
            "unknown_tokens": [],
        }

    unknown_tokens: list[str] = []
    classic_adv = False
    sofa2_adv = False
    icu08_best = "none"
    icu08_tier = 0

    for part in parts:
        if part not in _ROUTE_TABLE:
            unknown_tokens.append(part)
            _unknown_counter[part] += 1
            continue

        c_adv, s2_adv, arm = _ROUTE_TABLE[part]

        # 运行时解析 _AIRWAY 标记
        if c_adv == _AIRWAY:
            c_adv = airway_as_advanced

        # HFNC 可由配置覆盖
        if arm == "hfnc":
            if not hfnc_as_advanced_classic:
                c_adv = False
            if not hfnc_as_advanced_sofa2:
                s2_adv = False

        # classic_advanced: 任一成分为 True 即 True
        if c_adv:
            classic_adv = True

        # sofa2_advanced: 任一成分为 True 即 True
        if s2_adv:
            sofa2_adv = True

        # icu08_arm: 取最高级别
        tier = _ICU08TIER.get(arm, 0)
        if tier > icu08_tier:
            icu08_tier = tier
            icu08_best = arm

    # 有未知值: advanced 返回 None(不是 False), icu08_arm 返回 unknown
    if unknown_tokens:
        return {
            "classic_advanced": None,
            "sofa2_advanced": None,
            "icu08_arm": "unknown",
            "unknown_tokens": unknown_tokens,
        }

    return {
        "classic_advanced": classic_adv,
        "sofa2_advanced": sofa2_adv,
        "icu08_arm": icu08_best,
        "unknown_tokens": [],
    }


def get_unknown_stats() -> dict:
    """返回未知取值统计，供阶段 9 打印。"""
    return dict(_unknown_counter.most_common())


# ============================================================
# 2. 快捷接口(兼容现有调用)
# ============================================================

def is_invasive(raw_route: str) -> bool:
    """兼容 db.py is_invasive_by_o2route 的布尔返回。"""
    r = classify_o2_route(raw_route)
    return r["icu08_arm"] == "invasive"


# ============================================================
# 3. 全量测试(开发期可选运行)
# ============================================================

if __name__ == "__main__":
    _ALL_SINGLE = [
        "无", "自主呼吸", "管辅", "管氧", "切辅", "鼻塞", "切氧", "鼻导管",
        "切文", "管文", "面罩", "管高", "切高", "高流量", "T管", "无创",
        "有创", "无创呼吸机", "箱氧", "鼻罩", "带管自主",
        "储氧面罩", "储氧", "面罩吸氧", "鼻氧", "鼻管辅",
        "低流量", "低流量用氧", "低流量箱氧", "未吸氧",
        "拒绝", "拒绝吸氧", "暂停吸氧", "文丘里",
        "球囊", "呼吸球囊", "球囊通气", "简易呼吸器",
        "家用呼吸机", "家用", "无创高频", "高频", "鼻",
    ]

    print("=== 单值三列映射 ===")
    for v in _ALL_SINGLE:
        r = classify_o2_route(v, airway_as_advanced=False)
        r2 = classify_o2_route(v, airway_as_advanced=True)
        flag = " ⚠️ unknown" if r["unknown_tokens"] else ""
        c_flag = "✅" if r["classic_advanced"] else "❌"
        s_flag = "✅" if r["sofa2_advanced"] else "❌"
        print(f"  {v:8s} → classic={c_flag}  sofa2={s_flag}  arm={r['icu08_arm']:12s}{flag}")

    print("\n=== 组合值测试 ===")
    combos = [
        "管辅+自主呼吸", "高流量、面罩", "管辅、无创",
        "自主呼吸+管文", "管高+自主呼吸",
    ]
    for v in combos:
        r = classify_o2_route(v, airway_as_advanced=False)
        flag = " ⚠️ unknown" if r["unknown_tokens"] else ""
        c_flag = "✅" if r["classic_advanced"] else "❌"
        s_flag = "✅" if r["sofa2_advanced"] else "❌"
        print(f"  {v:20s} → classic={c_flag}  sofa2={s_flag}  arm={r['icu08_arm']:12s}{flag}")

    print("\n=== 未知值测试 ===")
    for v in ["垃圾值", "123", "未知"]:
        r = classify_o2_route(v)
        print(f"  {v:8s} → classic={r['classic_advanced']}  sofa2={r['sofa2_advanced']}  "
              f"arm={r['icu08_arm']:12s}  unknown={r['unknown_tokens']}")

    print("\n=== 未知取值统计 ===")
    for k, v in get_unknown_stats().items():
        print(f"  {k}: {v}")
