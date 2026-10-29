"""ICU-08 新口径：入科 24h P/F 均值 + 诊断 AND 过滤（纯函数，不连库）。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from db import _ards_diag_hit, _ards_diag_hits, _mean_of, _cn_period_bounds
from config.indicator_windows import ARDS_PF_AVG_HOURS, ARDS_DIAG_KEYWORDS


def test_mean_of_basic():
    assert _mean_of([100, 200, 300]) == 200
    assert abs(_mean_of([120.5, 180.5]) - 150.5) < 1e-9


def test_mean_of_ignores_non_numeric():
    assert _mean_of([100, None, "x", 200]) == 150
    assert _mean_of([]) is None
    assert _mean_of([None]) is None


def test_diag_hit_keywords():
    for kw in ARDS_DIAG_KEYWORDS:
        assert _ards_diag_hit(f"入院诊断：{kw}相关"), kw
    assert _ards_diag_hit("ARDS")
    assert not _ards_diag_hit("高血压 冠心病")
    assert not _ards_diag_hit("")


def test_diag_hit_require_false_passthrough():
    assert _ards_diag_hit("", require=False) is True
    assert _ards_diag_hit("无相关诊断", require=False) is True


def test_diag_hits_list():
    assert _ards_diag_hits("重症肺炎|I型呼吸衰竭") == ["重症肺炎"]
    # 中文全称命中时不重复报「急性呼吸窘迫」前缀
    hits = _ards_diag_hits("急性呼吸窘迫综合征")
    assert hits == ["急性呼吸窘迫综合征"]
    assert _ards_diag_hits("") == []


def test_period_bounds_are_wallclock_days():
    s, e = _cn_period_bounds("2026-09-01", "2026-09-30")
    assert s == datetime(2026, 9, 1, 0, 0, 0)
    assert e == datetime(2026, 9, 30, 23, 59, 59)


def test_period_bounds_aware_input_converted_to_cn():
    # 2026-08-31T23:00:00+00:00 = 东八区 2026-09-01 07:00
    aware = datetime(2026, 8, 31, 23, 0, 0, tzinfo=timezone.utc)
    s, e = _cn_period_bounds(aware.isoformat(), "2026-09-30")
    assert s == datetime(2026, 9, 1, 0, 0, 0)


def test_config_defaults_match_requirement():
    assert ARDS_PF_AVG_HOURS == 24
    for kw in ("ARDS", "肺损伤", "重症肺炎", "创伤性湿肺"):
        assert kw in ARDS_DIAG_KEYWORDS


def test_pf_avg_window_threshold_semantics():
    """均值口径：窗口内多条 P/F 先平均再比阈值。"""
    # 旧口径首条 240 不达标；均值 140 达标
    samples = [240.0, 100.0, 80.0]
    assert _mean_of(samples) == 140.0
    assert _mean_of(samples) < 150.0

    admit = datetime(2026, 9, 1, 8, 0, 0)
    win_end = admit + timedelta(hours=ARDS_PF_AVG_HOURS)
    inside = [admit + timedelta(hours=1), admit + timedelta(hours=12), win_end - timedelta(minutes=1)]
    outside = admit + timedelta(hours=25)
    assert admit <= inside[0] <= win_end
    assert not (admit <= outside <= win_end)
