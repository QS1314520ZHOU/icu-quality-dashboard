#!/usr/bin/env python3
"""
ICU-08/09/10 窗口审计脚本 — 患者级明细 CSV
用途：逐患者检查分子/分母的时间窗口命中情况，标出三类越界患者。
输出：tools/out/window_audit.csv
"""
import csv
import os
import sys
from datetime import datetime as dt, timedelta
from pathlib import Path

# 把项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "icu-quality-backend"))

from db import (
    get_icu08_data, get_icu09_data, get_icu10_data,
    iter_bed_dbs, BEDSIDE_PAIN_CODES, SCORE_PAIN_TYPES,
    BEDSIDE_SEDATION_CODE, SCORE_SEDATION_TYPES,
)
from bson import ObjectId


def month_range(n_months: int = 3):
    """返回最近 n_months 个自然月的 (start_date, end_date, period_label) 列表。"""
    today = dt.now()
    # 从上个月开始往前推
    first_of_this_month = dt(today.year, today.month, 1)
    ranges = []
    for i in range(1, n_months + 1):
        # 前 i 个月的第一天
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start = dt(y, m, 1)
        # 当月最后一天
        if m == 12:
            end = dt(y + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = dt(y, m + 1, 1) - timedelta(seconds=1)
        label = f"{y}-{m:02d}"
        ranges.append((start.isoformat(), end.isoformat(), label))
    return ranges


def get_all_icu_depts():
    """获取全部 ICU 科室代码。"""
    depts = set()
    for db_name, db in iter_bed_dbs():
        try:
            docs = list(db.patient.distinct("deptCode", {"deptCode": {"$ne": None}}))
            depts.update(docs)
        except Exception:
            continue
    return list(depts)


def audit_indicator(indicator: str, start_date: str, end_date: str, period_label: str, dept_codes: list):
    """
    审计单个指标，返回患者级明细行列表。
    每行: [indicator, period, pid, mrn, name, icu_admit, icu_discharge,
           den_hit, num_hit, num_event_time, num_event_in_month,
           num_event_before_admit, num_event_after_month_end, note]
    """
    start_dt = dt.fromisoformat(start_date)
    end_dt = dt.fromisoformat(end_date)
    end_dt_wide = dt(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    rows = []

    if indicator == "ICU-08":
        data = get_icu08_data(dept_codes, start_date, end_date)
        den_map = {p["pid"]: p for p in data.get("den_patients", [])}
        num_map = {p["pid"]: p for p in data.get("num_patients", [])}

        # 获取分母患者（包括未命中的）以便审计
        all_den_pids = set(den_map.keys())
        all_num_pids = set(num_map.keys())

        for pid in all_den_pids:
            p = den_map[pid]
            mrn = p.get("mrn", "")
            name = p.get("name", "")
            icu_admit = ""
            icu_discharge = ""

            # 查患者住院区间
            for db_name, db in iter_bed_dbs():
                try:
                    pat = db.patient.find_one({"_id": ObjectId(pid)}, {"icuAdmissionTime": 1, "icuDischargeTime": 1})
                    if pat:
                        icu_admit = str(pat.get("icuAdmissionTime", ""))
                        icu_discharge = str(pat.get("icuDischargeTime", ""))
                    break
                except Exception:
                    continue

            den_hit = "Y"
            num_hit = "Y" if pid in all_num_pids else "N"
            num_event_time = ""
            num_event_in_month = ""
            num_event_before_admit = ""
            num_event_after_month_end = ""
            note = ""

            if pid in num_map:
                prone_times = num_map[pid].get("prone_times", [])
                if prone_times:
                    # 取最早的俯卧位时间
                    earliest = min(prone_times)
                    num_event_time = str(earliest)
                    num_event_in_month = "Y" if start_dt <= earliest <= end_dt_wide else "N"
                    if icu_admit:
                        admit_dt = dt.fromisoformat(icu_admit) if isinstance(icu_admit, str) else icu_admit
                        num_event_before_admit = "Y" if earliest < admit_dt else "N"
                    num_event_after_month_end = "Y" if earliest > end_dt_wide else "N"

                    if num_event_in_month == "N":
                        note = "跨月充值: 事件不在统计月内"
                    if num_event_before_admit == "Y":
                        note = "事件早于入科时间"
                    if num_event_after_month_end == "Y" and not icu_discharge:
                        note = "未来数据倒灌: 未出科患者事件在月末后"

            rows.append([
                indicator, period_label, pid, mrn, name, icu_admit, icu_discharge,
                den_hit, num_hit, num_event_time, num_event_in_month,
                num_event_before_admit, num_event_after_month_end, note
            ])

    else:
        # ICU-09 / ICU-10
        get_fn = get_icu09_data if indicator == "ICU-09" else get_icu10_data
        data = get_fn(dept_codes, start_date, end_date)
        den_map = {p["pid"]: p for p in data.get("den_patients", [])}
        num_map = {p["pid"]: p for p in data.get("num_patients", [])}

        all_den_pids = set(den_map.keys())
        all_num_pids = set(num_map.keys())

        # 获取全部分母患者（含未命中的）以便审计
        for db_name, db in iter_bed_dbs():
            try:
                patients = list(db.patient.find(
                    {"deptCode": {"$in": dept_codes}, "status": {"$ne": "invalid"},
                     "icuAdmissionTime": {"$lte": end_dt_wide},
                     "$or": [{"icuDischargeTime": {"$gte": start_dt}},
                             {"icuDischargeTime": None},
                             {"icuDischargeTime": {"$exists": False}}]},
                    {"_id": 1, "mrn": 1, "name": 1, "icuAdmissionTime": 1, "icuDischargeTime": 1},
                ))

                for pat in patients:
                    pid = str(pat["_id"])
                    mrn = pat.get("mrn", "")
                    name = pat.get("name", "")
                    icu_admit = str(pat.get("icuAdmissionTime", ""))
                    icu_discharge = str(pat.get("icuDischargeTime", ""))

                    den_hit = "Y"
                    num_hit = "Y" if pid in all_num_pids else "N"
                    num_event_time = ""
                    num_event_in_month = ""
                    num_event_before_admit = ""
                    num_event_after_month_end = ""
                    note = ""

                    if pid in num_map:
                        assess_time = num_map[pid].get("assess_time")
                        if assess_time:
                            num_event_time = str(assess_time)
                            num_event_in_month = "Y" if start_dt <= assess_time <= end_dt_wide else "N"
                            if icu_admit:
                                admit_dt = dt.fromisoformat(icu_admit) if isinstance(icu_admit, str) else icu_admit
                                num_event_before_admit = "Y" if assess_time < admit_dt else "N"
                            num_event_after_month_end = "Y" if assess_time > end_dt_wide else "N"

                            if num_event_in_month == "N":
                                note = "跨月充值: 评估时间不在统计月内"
                            if num_event_before_admit == "Y":
                                note = "评估早于入科时间"
                            if num_event_after_month_end == "Y" and not icu_discharge:
                                note = "未来数据倒灌: 未出科患者评估在月末后"

                    rows.append([
                        indicator, period_label, pid, mrn, name, icu_admit, icu_discharge,
                        den_hit, num_hit, num_event_time, num_event_in_month,
                        num_event_before_admit, num_event_after_month_end, note
                    ])

                break
            except Exception as e:
                print(f"[{indicator}] Error in db {db_name}: {e}")
                continue

    return rows


def main():
    output_dir = ROOT / "tools" / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "window_audit.csv"

    indicators = ["ICU-08", "ICU-09", "ICU-10"]
    months = month_range(3)
    depts = get_all_icu_depts()

    print(f"[审计] 指标: {indicators}")
    print(f"[审计] 月份: {[m[2] for m in months]}")
    print(f"[审计] 科室数: {len(depts)}")

    header = [
        "indicator", "period", "pid", "mrn", "name",
        "icu_admit", "icu_discharge",
        "den_hit", "num_hit", "num_event_time",
        "num_event_in_month", "num_event_before_admit", "num_event_after_month_end",
        "note"
    ]

    all_rows = []
    for start_date, end_date, period_label in months:
        for indicator in indicators:
            print(f"[审计] 处理 {indicator} {period_label} ...")
            rows = audit_indicator(indicator, start_date, end_date, period_label, depts)
            all_rows.extend(rows)
            print(f"  → {len(rows)} 行")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)

    print(f"\n[完成] 写入 {csv_path}，共 {len(all_rows)} 行")


if __name__ == "__main__":
    main()
