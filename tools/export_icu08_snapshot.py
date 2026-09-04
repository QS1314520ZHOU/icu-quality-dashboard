#!/usr/bin/env python3
"""导出 icu_monthly_summary 中 ICU-08 最近12个月记录到 CSV"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "icu-quality-backend"))

from db import get_client, BED_DB_NAMES

def main():
    rows = []
    periods_used = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            coll = db["icu_monthly_summary"]
            # 先取实际存在的 period，再取最后12个
            all_periods = sorted(coll.distinct("period", {"indicator": "ICU-08"}))
            periods = all_periods[-12:] if len(all_periods) > 12 else all_periods
            periods_used = periods
            docs = list(coll.find(
                {"indicator": "ICU-08", "period": {"$in": periods}},
                {"_id": 0, "dept_code": 1, "period": 1, "numerator": 1, "denominator": 1, "value": 1, "updated_at": 1}
            ).sort([("period", 1), ("dept_code", 1)]))
            for d in docs:
                rows.append({
                    "dept_code": d.get("dept_code", ""),
                    "period": d.get("period", ""),
                    "numerator": d.get("numerator", ""),
                    "denominator": d.get("denominator", ""),
                    "value": d.get("value", ""),
                    "updated_at": str(d.get("updated_at", "")),
                })
            break
        except Exception as e:
            print(f"[WARN] db {db_name}: {e}", file=sys.stderr)
            continue

    out_dir = os.path.join(os.path.dirname(__file__), "out")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "icu08_before_snapshot.csv")

    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write("dept_code,period,numerator,denominator,value,updated_at\n")
        for r in rows:
            f.write(f"{r['dept_code']},{r['period']},{r['numerator']},{r['denominator']},{r['value']},{r['updated_at']}\n")

    print(f"Exported {len(rows)} rows to {out_path}")
    print(f"Periods covered: {periods_used}")

if __name__ == "__main__":
    main()
