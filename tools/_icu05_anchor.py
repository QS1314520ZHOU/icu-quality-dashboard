"""决定性分析：把 T0 换成"休克识别时刻"重判 2026-08 的 K1∧K2 患者。

时间线对照: 入院 / 入ICU / 系统T0 / 首剂抗生素 / 血培养 / 首次乳酸≥2 / 首次升压药
休克识别 = min(首次乳酸≥2, 首次升压药执行)
"""
import os
import sys
from datetime import timedelta

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_client, get_bundle_data_v2, judge_bundle_v3_for_patient  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
dc = get_client("DataCenter")["DataCenter"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

DEPTS = ["3439", "2927"]
ABX_KW = ['头孢', '培南', '青霉', '万古', '阿奇', '左氧', '莫西', '甲硝唑', '奥硝唑',
          '利奈', '替考', '磷霉素', '美罗', '亚胺', '厄他', '哌酮', '他唑', '舒巴坦',
          '氨苄', '哌拉', '阿莫', '克拉', '多西', '米诺', '替加', '达托', '夫西',
          '磺胺', '呋喃', '吡哌', '诺氟', '环丙', '氧氟']
NON = ['肝素', '低分子', '华法林', '阿司匹林', '氯吡格雷', '维生素', '氯化钾', '胰岛素',
       '碳酸氢钠', '呋塞米', '甘露醇', '地塞米松', '甲泼尼龙', '丙泊酚', '咪达唑仑',
       '芬太尼', '瑞芬太尼', '右美托咪定', '吗啡', '布洛芬', '对乙酰氨基酚', '皮试', '皮试剂']


def h(t):
    return t.strftime("%m-%d %H:%M") if t else "-"


d = get_bundle_data_v2(DEPTS, "2026-08-01", "2026-08-31")
den = d.get("den_patients", [])
targets = [p for p in den
           if (p.get("v3") or {}).get("k1") is True and (p.get("v3") or {}).get("k2") is True]
print(f"2026-08 den={len(den)} K1∧K2={len(targets)}\n")

for p in targets:
    v3 = p.get("v3") or {}
    pid, sc_pid = p.get("_id"), p.get("sc_pid") or p.get("_id")
    t0 = p.get("t0")
    row = dc.VI_ICU_ZYBR.find_one({"pid": pid},
                                  {"admitTime": 1, "inPatientTime": 1})
    adm = row.get("admitTime") if row else None
    inp = row.get("inPatientTime") if row else None

    # 时间线
    abx = None
    for dd in sc.drugExe.find({"pid": sc_pid, "startTime": {"$gte": (adm or t0) - timedelta(hours=48),
                                                            "$lte": (adm or t0) + timedelta(hours=72)}},
                              {"drugList.name": 1, "startTime": 1}).sort("startTime", 1):
        for dl in (dd.get("drugList") or []):
            nm = str(dl.get("name") or "")
            if any(k in nm for k in ABX_KW) and not any(k in nm for k in NON):
                abx = dd.get("startTime")
                break
        if abx:
            break
    cult = None
    cdoc = dc.VI_ICU_ZYYZ.find_one({"pid": pid, "orderName": {"$regex": "血培养"}},
                                    {"orderTime": 1}, sort=[("orderTime", 1)])
    if cdoc:
        cult = cdoc.get("orderTime")

    # 首次乳酸≥2（血气 param_bg_Lac）
    lac_ge2 = None
    for doc in sc.bGATemp.find({"mrn": p.get("mrn"),
                                "bedsides": {"$elemMatch": {"code": "param_bg_Lac",
                                                           "valid": "valid"}}},
                               {"bedsides": 1}):
        for bs in doc.get("bedsides", []):
            val, tt = bs.get("fVal"), bs.get("time")
            if val is not None and tt and val >= 2:
                if lac_ge2 is None or tt < lac_ge2:
                    lac_ge2 = tt
    # 首次升压药
    vaso = None
    for dd in sc.drugExe.find({"pid": sc_pid, "startTime": {"$gte": (adm or t0) - timedelta(hours=48),
                                                            "$lte": (adm or t0) + timedelta(hours=72)}},
                              {"drugList.name": 1, "startTime": 1}).sort("startTime", 1):
        hit = False
        for dl in (dd.get("drugList") or []):
            nm = str(dl.get("name") or "")
            low = nm.strip().lower()
            from scoring.bundle_engine import _classify_vasopressor
            w, s = _classify_vasopressor(nm)
            if w or s:
                hit = True
                break
        if hit:
            vaso = dd.get("startTime")
            break

    onset_candidates = [x for x in (lac_ge2, vaso) if x]
    onset = min(onset_candidates) if onset_candidates else None

    b6 = v3.get("bundle_6h") or {}
    print("=" * 110)
    print(f"pid={pid}  入院={h(inp)} 入ICU={h(adm)} 系统T0={h(t0)}({p.get('t0_source')})")
    print(f"  时间线: 首剂abx={h(abx)} 血培养={h(cult)} 首次Lac≥2={h(lac_ge2)} 首次升压药={h(vaso)}")
    print(f"  >> 休克识别(onset)={h(onset)}   系统T0到onset差="
          f"{(onset - t0).total_seconds()/3600:+.1f}h" if onset else "  >> onset无法确定")
    if abx and onset:
        print(f"  首剂abx相对onset: {(abx - onset).total_seconds()/3600:+.1f}h"
              f"  血培养相对onset: {(cult - onset).total_seconds()/3600:+.1f}h" if cult else "")
    print(f"  系统T0下 6h判定: finish={b6.get('finish')} reasons={b6.get('reasons')}")

    # 用 onset 作 T0 重判
    if onset:
        try:
            v3b = judge_bundle_v3_for_patient(
                sc_pid, pid, p.get("mrn"), onset.replace(tzinfo=None),
                p.get("diagnose", ""))
            b6b = v3b.get("bundle_6h") or {}
            b1b = v3b.get("bundle_1h") or {}
            b3b = v3b.get("bundle_3h") or {}
            print(f"  >> onset作T0重判: 1h={b1b.get('finish')}{b1b.get('reasons')} "
                  f"3h={b3b.get('finish')}{b3b.get('reasons')} "
                  f"6h={b6b.get('finish')}{b6b.get('reasons')}")
        except Exception as e:
            print(f"  >> onset重判失败: {e}")
