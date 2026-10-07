"""ICU-05 现场诊断：跑一次 _compute_icu05 并钻到患者级找分子=0的原因。"""
import os
import sys
import time
from collections import Counter

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

# db.py 从 cwd 的 .env 读配置；.env 在仓库根目录
import shutil
from pathlib import Path
root_env = Path(r"D:\icu-quality-dashboard\.env")
if not (Path(BACKEND) / ".env").exists() and root_env.exists():
    shutil.copy(root_env, Path(BACKEND) / ".env")
    print(f"[setup] copied .env -> {BACKEND}")

from db import get_bundle_data_v2  # noqa: E402

# —— 关键：正常服务启动时会注入 VASO_WIDE_LABELS，单独跑必须补 ——
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402
_sc = get_client = None
from db import get_client as _gc  # noqa: E402
_sc = _gc("SmartCare")["SmartCare"]
_vaso = list(_sc.configDrug.find(
    {"classification": {"$regex": "血管活性", "$options": "i"}}, {"name": 1, "_id": 0}))
_labels = {d["name"].strip().lower() for d in _vaso if d.get("name")}
set_vaso_wide_labels(_labels)
print(f"[setup] VASO_WIDE_LABELS injected: {len(_labels)} drugs")

PERIOD = "2026-08"
START, END = "2026-08-01", "2026-08-31"

# 用汇总表里 ICU-05 记录的 dept_code
from db import get_client  # noqa: E402
coll = get_client("SmartCare")["SmartCare"]["icu_monthly_summary"]
sample = coll.find_one({"indicator": "ICU-05-1h", "period": PERIOD,
                        "denominator": {"$gt": 0}})
DEPT = sample["dept_code"] if sample else ""
dept_codes = DEPT.split(",") if DEPT else []
print(f"[setup] period={PERIOD} dept_codes({len(dept_codes)})={dept_codes[:6]}...")

t0 = time.time()
d = get_bundle_data_v2(dept_codes, START, END)
print(f"[get_bundle_data_v2] {time.time()-t0:.1f}s  den={len(d.get('den_patients', []))} "
      f"h1={len(d.get('h1_patients', []))} h3={len(d.get('h3_patients', []))} "
      f"h6={len(d.get('h6_patients', []))} old_shock={d.get('old_shock_count')}")

den = d.get("den_patients", [])
print(f"\n=== 患者级 {len(den)} 例 ===")
reason_ctr = Counter()
for p in den:
    v3 = p.get("v3") or {}
    b1 = v3.get("bundle_1h") or {}
    gate_reason = v3.get("reason") or (v3.get("gate") or {}).get("reason") or "-"
    k1, k2 = v3.get("k1"), v3.get("k2")
    cand = p.get("candidate_status", "-")
    reason_ctr[gate_reason] += 1

    has_vaso = v3.get("has_vasopressor")
    lac = v3.get("lactate_initial")
    reasons = b1.get("reasons")
    print(
        f"pid={str(p.get('_id'))[:12]} k1={k1} k2={k2} vaso={has_vaso} "
        f"lac={lac} gate={gate_reason} cand={cand} "
        f"finish1h={b1.get('finish')} step=({b1.get('step1')},{b1.get('step2')},{b1.get('step3')}) "
        f"reasons={reasons}"
    )

print("\n=== gate 失败原因分布 ===")
for k, v in reason_ctr.most_common():
    print(f"  {k}: {v}")

# 分母口径统计
official = [p for p in den if (p.get("v3") or {}).get("k1") is True
            and (p.get("v3") or {}).get("k2") is True]
cand = [p for p in den if p.get("candidate_status") not in (None, "not_candidate")]
print(f"\n=== 口径 ===\nK1∧K2(旧分母): {len(official)}\n候选(新分母): {len(cand)}")
