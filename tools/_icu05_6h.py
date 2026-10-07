"""看4例合格患者的 3h/6h 判定明细 + 液体/复测乳酸。"""
import os
import sys

BACKEND = r"D:\icu-quality-dashboard\icu-quality-backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from db import get_bundle_data_v2, get_client  # noqa: E402
from scoring.bundle_engine import set_vaso_wide_labels  # noqa: E402

sc = get_client("SmartCare")["SmartCare"]
vaso = list(sc.configDrug.find({"classification": {"$regex": "血管活性", "$options": "i"}},
                               {"name": 1, "_id": 0}))
set_vaso_wide_labels({d["name"].strip().lower() for d in vaso if d.get("name")})

d = get_bundle_data_v2(["3439"], "2026-08-01", "2026-08-31")
targets = [p for p in d.get("den_patients", [])
           if (p.get("v3") or {}).get("k1") is True and (p.get("v3") or {}).get("k2") is True]

for p in targets:
    v3 = p.get("v3") or {}
    print("=" * 96)
    print(f"pid={p.get('_id')} t0={p.get('t0')}")
    print(f"  lactate_all={[ (x['period_label'], x['value']) for x in (v3.get('lactate_all') or []) ]}")
    print(f"  has_fluid_1h={v3.get('has_fluid_1h')} fluid_3h_ml={v3.get('fluid_3h_ml')} "
          f"recheck_val={v3.get('lactate_recheck_value')} recheck_t={v3.get('lactate_recheck_time')}")
    for w in ("bundle_1h", "bundle_3h", "bundle_6h"):
        b = v3.get(w) or {}
        print(f"  {w}: finish={b.get('finish')} step=({b.get('step1')},{b.get('step2')},{b.get('step3')}) "
              f"path={b.get('finish_path')} reasons={b.get('reasons')} "
              f"abx={b.get('antibiotic_time')} cult={b.get('culture_time')} "
              f"recheck={b.get('has_lactate_recheck')}")
