"""修正 T0 锚点：T0 = 入ICU(admitTime)之后的第一条医嘱，重算 ICU-05。

原实现: _resolve_t0_for_dc_patients 取该 pid 全局最早 orderTime
        → 可能早于入ICU数小时（含急诊/病房医嘱甚至上次住院），
        → Bundle 窗口 [T0, T0+Nh] 在患者进 ICU 前就关闭了。
需求:   T0 = 入科后 VI_ICU_ZYYZ 第一条医嘱 orderTime
"""
import os
import sys
from datetime import timedelta, datetime

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

import db as dbmod  # noqa: E402
from db import get_client, get_bundle_data_v2  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
_dc = get_client("DataCenter")["DataCenter"]
_v = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                             {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in _v if d.get("name")})

DEPTS = ["3439", "2927"]
_orig = dbmod._resolve_t0_for_dc_patients
_stats = {"changed": 0, "total": 0, "pre_icu": 0}


def fixed_resolve(dc, dc_pids, den_patients):
    """T0 = admitTime(入ICU) 之后第一条医嘱；无则退 admitTime；再退回原逻辑。"""
    pid_set = {str(p) for p in dc_pids}
    for pat in den_patients:
        if str(pat.get("_id")) not in pid_set:
            continue
        adm = pat.get("admitTime")
        pid = pat.get("_id")
        _stats["total"] += 1
        if not adm:
            continue
        # 原 T0（全局首条）是否早于入ICU？
        old_doc = dc.VI_ICU_ZYYZ.find_one({"pid": pid}, {"orderTime": 1},
                                          sort=[("orderTime", 1)])
        old_t0 = old_doc.get("orderTime") if old_doc else None
        if old_t0 and old_t0 < adm - timedelta(minutes=1):
            _stats["pre_icu"] += 1
        doc = dc.VI_ICU_ZYYZ.find_one(
            {"pid": pid, "orderTime": {"$gte": adm - timedelta(minutes=5)}},
            {"orderTime": 1}, sort=[("orderTime", 1)])
        new_t0 = (doc.get("orderTime") if doc else None) or adm
        if old_t0 and new_t0 and abs((new_t0 - old_t0).total_seconds()) > 60:
            _stats["changed"] += 1
        pat["t0"] = new_t0
        pat["t0_source"] = "first_order_after_icu"


dbmod._resolve_t0_for_dc_patients = fixed_resolve

# ---------- 修正后重算 4 个月 ----------
from summary import _compute_icu05  # noqa: E402

print("=== 修正 T0 后重算（dept 3439+2927）===")
print(f"{'月份':8} {'1h(num/den)':14} {'6h(num/den)':14} {'old(K1∧K2)':10} {'cand':6} 修正T0数/入ICU前T0数")
for mon, end in (("2026-06", "30"), ("2026-07", "31"), ("2026-08", "31"), ("2026-09", "30")):
    r1 = _compute_icu05(DEPTS, f"{mon}-01", f"{mon}-{end}", "1h")
    _stats.update(changed=0, pre_icu=0, total=0)  # 每月跑两遍，取第二遍计数
    r6 = _compute_icu05(DEPTS, f"{mon}-01", f"{mon}-{end}", "6h")
    ratio1 = f"{r1['num']}/{r1['den']}"
    ratio6 = f"{r6['num']}/{r6['den']}"
    print(f"{mon:8} {ratio1:14} {ratio6:14} "
          f"{r6['old_shock_count']:<10} {r6['candidate_den']:<6} "
          f"{_stats['changed']}/{_stats['pre_icu']}(共{_stats['total']})")
    _stats.update(changed=0, pre_icu=0, total=0)

# ---------- 2026-08 患者级前后对照 ----------
print("\n=== 2026-08 患者级（修正后）===")
d = get_bundle_data_v2(DEPTS, "2026-08-01", "2026-08-31")
for p in d.get("den_patients", []):
    v3 = p.get("v3") or {}
    k1, k2 = v3.get("k1"), v3.get("k2")
    b6 = v3.get("bundle_6h") or {}
    b1 = v3.get("bundle_1h") or {}
    flag = "K1∧K2" if (k1 is True and k2 is True) else "      "
    print(f"  {flag} pid={p.get('_id')} t0={p.get('t0')} src={p.get('t0_source')} "
          f"k1={k1} k2={k2} vaso={v3.get('has_vasopressor')} "
          f"1h={b1.get('finish')}{b1.get('reasons')} 6h={b6.get('finish')}{b6.get('reasons')}")
