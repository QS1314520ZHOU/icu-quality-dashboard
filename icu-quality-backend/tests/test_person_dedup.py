"""
人数口径去重测试（ICU-04 / ICU-07 / ICU-09 / ICU-10 共用）。

INDICATORS_CONFIG 里这四个指标的分子分母定义都是「患者数」，
而 SmartCare patient 表一行 = 一次 ICU 入住，直接 len() 得到的是人次。
dedup_persons 是把「人次」折算成「人数」的唯一入口，行为必须稳定。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

from db import person_key_of, dedup_persons


def _stay(mrn, admit, his_pid=None, **kw):
    row = {"mrn": mrn, "icuAdmissionTime": admit, "name": kw.get("name", "张三")}
    if his_pid:
        row["hisPid"] = his_pid
    row.update({k: v for k, v in kw.items() if k != "name"})
    return row


# ---------------------------------------------------------------- person_key_of

def test_key_prefers_mrn():
    assert person_key_of({"mrn": "2069620", "hisPid": "1751489"}) == "2069620"


def test_key_falls_back_to_hispid_then_pid():
    assert person_key_of({"mrn": "", "hisPid": "1751489"}) == "1751489"
    assert person_key_of({"mrn": None, "hisPid": None, "pid": "p1"}) == "p1"
    assert person_key_of({"_id": "abc"}) == "abc"


def test_key_empty_rows_never_collapse_together():
    """所有键都为空时必须各自成行 —— 宁可不去重，也不能把两个人并成一个。"""
    a, b = {}, {}
    assert person_key_of(a) != person_key_of(b)


# ---------------------------------------------------------------- dedup_persons

def test_empty_input():
    assert dedup_persons([]) == []


def test_distinct_patients_all_kept():
    rows = [_stay("m1", datetime(2026, 9, 1)), _stay("m2", datetime(2026, 9, 5))]
    assert len(dedup_persons(rows)) == 2


def test_same_patient_two_admissions_keeps_earliest():
    """同一患者 9 月两次入科 → 一人，且代表行是入科最早那次。"""
    late = _stay("2069620", datetime(2026, 9, 24, 1, 55), stay_id="late")
    early = _stay("2069620", datetime(2026, 9, 8, 11, 30), stay_id="early")
    out = dedup_persons([late, early])          # 乱序传入也要取到早的那条
    assert len(out) == 1
    assert out[0]["icuAdmissionTime"] == datetime(2026, 9, 8, 11, 30)


def test_representative_row_matches_denominator_detail():
    """分子明细与分母明细必须挑中同一条在科记录，detail_id 才能逐行对上。"""
    stays = [_stay("m1", datetime(2026, 9, 24)), _stay("m1", datetime(2026, 9, 8)),
             _stay("m2", datetime(2026, 9, 3))]
    den = dedup_persons(stays)
    # 分子只含 m1 的两条在科记录（m2 未纳入分子）
    num = dedup_persons([r for r in stays if r["mrn"] == "m1"])
    assert {r["mrn"] for r in num} == {"m1"}
    den_m1 = next(r for r in den if r["mrn"] == "m1")
    assert num[0]["icuAdmissionTime"] == den_m1["icuAdmissionTime"]


def test_count_matches_distinct_mrn():
    rows = [_stay("m1", datetime(2026, 9, 1)), _stay("m1", datetime(2026, 9, 20)),
            _stay("m1", datetime(2026, 9, 28)), _stay("m2", datetime(2026, 9, 4))]
    assert len(dedup_persons(rows)) == len({r["mrn"] for r in rows}) == 2


def test_custom_time_key_keeps_earliest_score():
    """ICU-04 分子按「首次评分」取，用 score_time 而不是入科时间挑行。"""
    a = {"mrn": "m1", "icuAdmissionTime": datetime(2026, 9, 1),
         "score_time": datetime(2026, 9, 20), "score": 18}
    b = {"mrn": "m1", "icuAdmissionTime": datetime(2026, 9, 10),
         "score_time": datetime(2026, 9, 5), "score": 22}
    out = dedup_persons([a, b], time_key="score_time")
    assert len(out) == 1
    assert out[0]["score_time"] == datetime(2026, 9, 5)


def test_missing_time_loses_to_present_time():
    """一条没时间、一条有时间 → 保留有时间的（否则明细会显示空入科时间）。"""
    rows = [{"mrn": "m1", "icuAdmissionTime": None},
            {"mrn": "m1", "icuAdmissionTime": datetime(2026, 9, 7)}]
    assert dedup_persons(rows)[0]["icuAdmissionTime"] == datetime(2026, 9, 7)


def test_both_times_missing_keeps_first_seen():
    rows = [{"mrn": "m1", "icuAdmissionTime": None, "tag": 1},
            {"mrn": "m1", "icuAdmissionTime": None, "tag": 2}]
    assert len(dedup_persons(rows)) == 1


def test_unkeyed_rows_not_merged():
    rows = [{"name": "无键A"}, {"name": "无键B"}]
    assert len(dedup_persons(rows)) == 2


def test_output_sorted_by_time():
    rows = [_stay("m3", datetime(2026, 9, 30)),
            _stay("m1", datetime(2026, 9, 1)),
            _stay("m2", datetime(2026, 9, 15))]
    out = dedup_persons(rows)
    assert [r["mrn"] for r in out] == ["m1", "m2", "m3"]


def test_none_time_sorts_last():
    rows = [{"mrn": "m1", "icuAdmissionTime": None},
            {"mrn": "m2", "icuAdmissionTime": datetime(2026, 9, 1)}]
    assert [r["mrn"] for r in dedup_persons(rows)] == ["m2", "m1"]
