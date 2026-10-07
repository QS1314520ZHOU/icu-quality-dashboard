"""深挖：4例 K1∧K2 合格患者为什么 step2=AB_MISSING。查 T0、窗口内 drugExe、血培养医嘱。"""
import os
import sys
from datetime import timedelta

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_bundle_data_v2, get_client  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
dc = get_client("DataCenter")["DataCenter"]

vaso = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                               {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in vaso if d.get("name")})

PERIOD_START, PERIOD_END = "2026-08-01", "2026-08-31"
dept_codes = ["3439"]

d = get_bundle_data_v2(dept_codes, PERIOD_START, PERIOD_END)
den = d.get("den_patients", [])

ABX_KW = ['头孢', '培南', '青霉', '万古', '阿奇', '左氧', '莫西', '甲硝唑', '奥硝唑',
          '利奈', '替考', '磷霉素', '美罗', '亚胺', '厄他', '哌酮', '他唑', '舒巴坦',
          '氨苄', '哌拉', '阿莫', '克拉', '多西', '米诺', '替加', '达托', '夫西',
          '磺胺', '呋喃', '吡哌', '诺氟', '环丙', '氧氟']
NON_ABX = ['肝素', '低分子', '华法林', '阿司匹林', '氯吡格雷', '维生素', '氯化钾',
           '胰岛素', '碳酸氢钠', '呋塞米', '甘露醇', '地塞米松', '甲泼尼龙',
           '丙泊酚', '咪达唑仑', '芬太尼', '瑞芬太尼', '右美托咪定', '吗啡',
           '布洛芬', '对乙酰氨基酚', '皮试', '皮试剂']

targets = [p for p in den
           if (p.get("v3") or {}).get("k1") is True and (p.get("v3") or {}).get("k2") is True]
print(f"K1∧K2 患者 {len(targets)} 例\n")

for p in targets:
    v3 = p.get("v3") or {}
    t0 = p.get("t0")
    sc_pid = p.get("sc_pid") or p.get("_id")
    dc_pid = p.get("dc_pid") or p.get("_id")
    mrn = p.get("mrn")
    b1 = v3.get("bundle_1h") or {}
    print("=" * 100)
    print(f"pid={p.get('_id')} sc_pid={sc_pid} mrn={mrn} t0={t0} t0_src={p.get('t0_source')}")
    print(f"  diagnose={str(p.get('diagnose'))[:60]}")
    print(f"  antibiotic_time={v3.get('antibiotic_time')} name={v3.get('antibiotic_name')}")
    print(f"  culture_time={v3.get('culture_time')} blood_culture_time={v3.get('blood_culture_time')}")
    print(f"  has_antibiotic={v3.get('has_antibiotic')} has_culture={v3.get('has_culture')} "
          f"has_blood_culture={v3.get('has_blood_culture')}")
    print(f"  finish1h={b1.get('finish')} step=({b1.get('step1')},{b1.get('step2')},{b1.get('step3')}) "
          f"reasons={b1.get('reasons')}")
    if not t0:
        print("  !! t0 为空")
        continue
    t0_6h = t0 + timedelta(hours=6)

    # 1) 窗口内所有 drugExe（看有没有任何药，以及有没有抗生素）
    docs = list(sc.drugExe.find(
        {"pid": sc_pid, "startTime": {"$gte": t0 - timedelta(hours=2), "$lte": t0_6h}},
        {"drugList.name": 1, "startTime": 1}).sort("startTime", 1).limit(40))
    abx_hits, all_names = [], []
    for dd in docs:
        st = dd.get("startTime")
        for dl in (dd.get("drugList") or []):
            nm = str(dl.get("name") or "")
            all_names.append(f"{st:%m-%d %H:%M} {nm[:28]}")
            is_abx = any(k in nm for k in ABX_KW)
            real = is_abx and not any(k in nm for k in NON_ABX)
            if real:
                abx_hits.append(f"{st:%m-%d %H:%M} {nm[:40]}")
    print(f"  [drugExe T0-2h~T0+6h] 记录 {len(docs)} 条, 命中抗生素 {len(abx_hits)} 条")
    for a in abx_hits[:6]:
        print(f"      ABX> {a}")
    if not abx_hits:
        print(f"      (窗口内全部药品前12条)")
        for n in all_names[:12]:
            print(f"        {n}")

    # 2) 放宽：T0 前后 48h 内有没有抗生素？
    wide = list(sc.drugExe.find(
        {"pid": sc_pid, "startTime": {"$gte": t0 - timedelta(hours=24), "$lte": t0 + timedelta(hours=48)}},
        {"drugList.name": 1, "startTime": 1}).sort("startTime", 1).limit(200))
    wide_abx = []
    for dd in wide:
        st = dd.get("startTime")
        for dl in (dd.get("drugList") or []):
            nm = str(dl.get("name") or "")
            if any(k in nm for k in ABX_KW) and not any(k in nm for k in NON_ABX):
                delta = (st - t0).total_seconds() / 3600
                wide_abx.append(f"{st:%m-%d %H:%M} (T0{delta:+.1f}h) {nm[:36]}")
    print(f"  [T0-24h~T0+48h] 抗生素 {len(wide_abx)} 条")
    for a in wide_abx[:8]:
        print(f"      > {a}")

    # 3) 血培养医嘱
    cult = list(dc.VI_ICU_ZYYZ.find(
        {"pid": dc_pid, "orderName": {"$regex": "血培养"}},
        {"orderName": 1, "orderTime": 1, "reviewTime": 1}).sort("orderTime", 1).limit(10))
    print(f"  [VI_ICU_ZYYZ 血培养医嘱 pid={dc_pid}] {len(cult)} 条")
    for cc in cult[:6]:
        print(f"      order={cc.get('orderTime')} review={cc.get('reviewTime')} {str(cc.get('orderName'))[:30]}")
