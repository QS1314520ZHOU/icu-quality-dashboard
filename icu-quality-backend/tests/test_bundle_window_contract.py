from datetime import datetime, timedelta

import scoring.bundle_engine as engine


def _patient(t0, **overrides):
    data = {
        "t0": t0,
        "diagnosis_text": "sepsis",
        "has_antibiotic": True,
        "has_culture": True,
        "has_vasopressor": True,
        "lactate_initial": 2.5,
        "map_min": 65,
        "w1h": {},
        "w3h": {},
    }
    data.update(overrides)
    return data


def setup_module():
    engine.set_vaso_wide_labels({"norepinephrine"})


def test_window_contract_has_no_ambiguous_top_level_finish():
    t0 = datetime(2026, 1, 1, 8)
    result = engine.judge_bundle_v3(_patient(t0))
    assert set(result) == {"bundle_1h", "bundle_3h", "bundle_6h", "gate"}
    assert "finish" not in result


def test_1h_and_3h_use_independent_evidence():
    t0 = datetime(2026, 1, 1, 8)
    result = engine.judge_bundle_v3(_patient(t0, w1h={
        "lactate_initial": 2.5, "lactate_max": 2.5, "map_min": 65,
        "antibiotic_time": t0 + timedelta(minutes=30),
        "culture_time": t0 + timedelta(minutes=20), "has_fluid": True,
    }, w3h={
        "lactate_initial": 2.5, "lactate_max": 8, "map_min": 55,
        "antibiotic_time": t0 + timedelta(hours=2),
        "culture_time": t0 + timedelta(minutes=20), "fluid_ml": 0,
    }))
    assert result["bundle_1h"]["finish"] is True
    assert result["bundle_3h"]["finish"] is False
    assert result["bundle_1h"]["c2"] is False
    assert result["bundle_3h"]["c2"] is True


def test_missing_trigger_evidence_stays_pending_not_completed():
    t0 = datetime(2026, 1, 1, 8)
    result = engine.judge_bundle_v3(_patient(t0, w1h={
        "lactate_initial": 2.5,
        "antibiotic_time": t0 + timedelta(minutes=30),
        "culture_time": t0 + timedelta(minutes=20),
        "has_fluid": None,
    }))
    assert result["bundle_1h"]["c1"] is None
    assert result["bundle_1h"]["finish"] is None
