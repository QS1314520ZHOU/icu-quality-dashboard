#!/usr/bin/env python3
"""
ICU-05 实库对账脚本
使用完整生产链: _compute_icu05 -> get_bundle_data_v2 -> judge_bundle_v3_for_patient
从 patient 表中查找有 drugExe/bedside 数据的科室，取第一个患者做端到端校验
输出 ICU05_RESULT= 前缀的 JSON
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'icu-quality-backend'))

from db import get_client, get_bundle_data_v2
from bson import ObjectId


def find_dept_with_data(sc):
    """找一个有 drugExe + bedside 数据的科室"""
    de_doc = sc.drugExe.find_one({}, {"pid": 1, "startTime": 1})
    if not de_doc:
        return None, None
    sample_pid = de_doc.get("pid", "")

    # pid -> patient -> deptCode
    pat = None
    if sample_pid:
        try:
            pat = sc.patient.find_one({"_id": ObjectId(str(sample_pid))}, {"deptCode": 1})
        except Exception:
            pass
    if not pat:
        pat = sc.patient.find_one({"_id": sample_pid}, {"deptCode": 1})
    if not pat or not pat.get("deptCode"):
        return None, None
    return pat["deptCode"], sample_pid


def main():
    sc = get_client("SmartCare")["SmartCare"]
    dc = get_client("DataCenter")["DataCenter"]

    # 找最新有数据的月份
    latest_de = sc.drugExe.find_one({}, {"startTime": 1}, sort=[("startTime", -1)])
    if not latest_de or not latest_de.get("startTime"):
        result = {"status": "no_data", "reason": "drugExe 为空"}
        print("ICU05_RESULT=" + json.dumps(result, ensure_ascii=False))
        return

    st = latest_de["startTime"]
    year, month = st.year, st.month
    # 往前一个月
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"

    dept_code, _ = find_dept_with_data(sc)
    if not dept_code:
        result = {"status": "no_dept", "reason": "找不到有数据的科室"}
        print("ICU05_RESULT=" + json.dumps(result, ensure_ascii=False))
        return

    # 调用完整生产链
    result = get_bundle_data_v2([dept_code], start, end)

    if not result:
        out = {"status": "no_data", "dept": dept_code}
        print("ICU05_RESULT=" + json.dumps(out, ensure_ascii=False))
        return

    den_patients = result.get("den_patients", [])
    h6_items = result.get("h6_patients", [])
    h1_items = result.get("h1_patients", [])
    h3_items = result.get("h3_patients", [])

    # 取第一个分母患者
    first_pid = den_patients[0] if den_patients else None
    first_status = None
    first_vaso = None
    first_sofa_classic = None
    first_sofa2 = None
    if first_pid and h6_items:
        for it in h6_items:
            if it.get("pid") == first_pid:
                first_status = it.get("v3", {}).get("sepsis_onset", {}).get("6h_status")
                first_vaso = it.get("v3", {}).get("vasopressor_status")
                sofa_data = it.get("v3", {}).get("sofa", {})
                first_sofa_classic = sofa_data.get("classic", {}).get("score")
                first_sofa2 = sofa_data.get("sofa2", {}).get("score")
                break

    out = {
        "status": "ok",
        "dept": dept_code,
        "den_patients": len(den_patients),
        "month": f"{year}-{month:02d}",
        "sepsis_num": result.get("total", 0),
        "6h_status": first_status,
        "vasopressor_status": first_vaso,
        "sofa_classic_score": first_sofa_classic,
        "sofa2_score": first_sofa2,
        "1h_num": len(h1_items),
        "3h_num": len(h3_items),
        "6h_num": len(h6_items),
    }
    print("ICU05_RESULT=" + json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
