"""dept 3439+2927 重跑 ICU-05，并核查 T0 锚点 / 抗生素时序。"""
import os
import sys
from datetime import timedelta

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client, get_bundle_data_v2  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
dc = get_client("DataCenter")["DataCenter"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

DEPTS = ["3439", "2927"]

# ---------- 0. 这两个科室到底有多少脓毒症住院 ----------
print("=== 0. 分母池规模（ZYBR 脓毒症关键词 + deptCode）===")
KW = "感染性休克|脓毒性休克|脓毒症休克|脓毒血症|败血症|脓毒症"
for dc_ in DEPTS:
    n = dc.VI_ICU_ZYBR.count_documents({"deptCode": dc_, "diagnose": {"$regex": KW, "$options": "i"},
                                        "admitTime": {"$gte": __import__("datetime").datetime(2026, 6, 1),
                                                      "$lt": __import__("datetime").datetime(2026, 10, 1)}})
    n_all = dc.VI_ICU_ZYBR.count_documents({"deptCode": dc_})
    print(f"  dept {dc_}: 2026-06~09 脓毒症诊断 {n} 人 / 该科总住院 {n_all} 人")

# ---------- 1. 两科室重算 ----------
from summary import _compute_icu05  # noqa: E402

print("\n=== 1. _compute_icu05(dept=3439+2927) ===")
for mon, end in (("2026-06", "30"), ("2026-07", "31"), ("2026-08", "31"), ("2026-09", "30")):
    line = []
    for hour in ("1h", "6h"):
        r = _compute_icu05(DEPTS, f"{mon}-01", f"{mon}-{end}", hour)
        line.append(f"{hour}: num={r['num']} den={r['den']} old={r['old_shock_count']} "
                    f"cand={r['candidate_den']} mode={r['candidate_mode']}")
    print(f"  {mon}  " + " | ".join(line))

# ---------- 2. 2026-08 患者级：T0 对比入ICU时间 ----------
print("\n=== 2. 2026-08 T0 锚点核查（T0 vs 入ICU admitTime）===")
d = get_bundle_data_v2(DEPTS, "2026-08-01", "2026-08-31")
den = d.get("den_patients", [])
print(f"den_patients={len(den)}  old_shock={d.get('old_shock_count')}")

ABX_KW = ['头孢', '培南', '青霉', '万古', '阿奇', '左氧', '莫西', '甲硝唑', '奥硝唑',
          '利奈', '替考', '磷霉素', '美罗', '亚胺', '厄他', '哌酮', '他唑', '舒巴坦',
          '氨苄', '哌拉', '阿莫', '克拉', '多西', '米诺', '替加', '达托', '夫西',
          '磺胺', '呋喃', '吡哌', '诺氟', '环丙', '氧氟']
NON = ['肝素', '低分子', '华法林', '阿司匹林', '氯吡格雷', '维生素', '氯化钾', '胰岛素',
       '碳酸氢钠', '呋塞米', '甘露醇', '地塞米松', '甲泼尼龙', '丙泊酚', '咪达唑仑',
       '芬太尼', '瑞芬太尼', '右美托咪定', '吗啡', '布洛芬', '对乙酰氨基酚', '皮试', '皮试剂']


def first_abx(pid, lo, hi):
    docs = sc.drugExe.find({"pid": pid, "startTime": {"$gte": lo, "$lte": hi}},
                           {"drugList.name": 1, "startTime": 1}).sort("startTime", 1)
    for dd in docs:
        st = dd.get("startTime")
        for dl in (dd.get("drugList") or []):
            nm = str(dl.get("name") or "")
            if any(k in nm for k in ABX_KW) and not any(k in nm for k in NON):
                return st, nm[:30]
    return None, None


for p in den:
    v3 = p.get("v3") or {}
    src = p.get("source", "sc")
    t0 = p.get("t0")
    pid = p.get("_id")
    admit = inpat = None
    if src == "vi_zybr" or str(pid).isdigit():
        row = dc.VI_ICU_ZYBR.find_one({"pid": pid},
                                      {"admitTime": 1, "inPatientTime": 1, "deptCode": 1})
        if row:
            admit, inpat = row.get("admitTime"), row.get("inPatientTime")
    k1, k2 = v3.get("k1"), v3.get("k2")
    flag = "K1∧K2" if (k1 is True and k2 is True) else ""
    gap = ""
    if t0 and admit:
        gap = f"  T0-入ICU={(t0 - admit).total_seconds()/60:+.0f}min"
    # 首剂抗生素（入ICU前后各48h）
    abx_t, abx_n = (None, None)
    if admit:
        abx_t, abx_n = first_abx(p.get("sc_pid") or pid, admit - timedelta(hours=48),
                                 admit + timedelta(hours=72))
    abx_gap = ""
    if abx_t and admit:
        abx_gap = f" 首剂abx(相对入ICU)={(abx_t - admit).total_seconds()/3600:+.1f}h"
    print(f"  {flag:6} pid={pid} dept={p.get('deptCode')} src={src} "
          f"t0={t0} admit={admit}{gap} vaso={v3.get('has_vasopressor')} "
          f"lac={v3.get('lactate_initial')}{abx_gap} {abx_n or ''}")
