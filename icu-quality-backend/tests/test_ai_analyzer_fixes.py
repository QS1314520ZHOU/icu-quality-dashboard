"""ai_analyzer 调用侧修复：JSON 解析、兜底不缓存、索引含 key。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_analyzer as aa  # noqa: E402


def test_parse_keeps_chinese_quotes_inside_strings():
    raw = '{"purpose":"治疗性","confidence":0.8,"reason":"诊断“肺部感染”，疗程72h"}'
    assert aa.parse_llm_json(raw)["reason"] == "诊断“肺部感染”，疗程72h"


def test_parse_code_fence_and_dict_passthrough():
    assert aa.parse_llm_json('```json\n{"a":1}\n```') == {"a": 1}
    assert aa.parse_llm_json({"a": 1}) == {"a": 1}


def test_parse_still_normalizes_chinese_punctuation_when_needed():
    assert aa.parse_llm_json('{“risk”：“low”}') == {"risk": "low"}


def test_abx_brief_tolerates_missing_numbers():
    assert aa._abx_brief({"course_hours": None, "antibiotics": None}).startswith("疗程?h")
    assert aa._abx_brief({"course_hours": "48.4", "dose_count": 3}).startswith("疗程48h/3次")


def test_fallback_not_cached(monkeypatch):
    writes = []
    monkeypatch.setattr(aa, "get_ai_cache", lambda *a, **k: None)
    monkeypatch.setattr(aa, "set_ai_cache", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(aa, "call_llm_json_with_system", lambda *a, **k: None)
    monkeypatch.setattr(aa, "call_llm_json", lambda *a, **k: None)
    r = aa.classify_abx_with_ai({"hisPid": "P1", "course_hours": None})
    assert r["by"] == "fallback"
    r = aa.classify_sepsis_alert_with_ai({"hisPid": "P1"})
    assert r["by"] == "fallback"
    assert writes == []


def test_ai_result_cached(monkeypatch):
    writes = []
    monkeypatch.setattr(aa, "get_ai_cache", lambda *a, **k: None)
    monkeypatch.setattr(aa, "set_ai_cache", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(aa, "call_llm_json", lambda *a, **k: {"purpose": "预防性", "confidence": 0.9})
    assert aa.classify_abx_with_ai({"hisPid": "P1"})["purpose"] == "预防性"
    assert len(writes) == 1


class _Coll:
    def __init__(self, existing):
        self.idx = {"idx_hispid_task": {"key": existing}} if existing else {}
        self.dropped, self.created = [], []

    def index_information(self):
        return self.idx

    def drop_index(self, name):
        self.dropped.append(name)

    def create_index(self, keys, **kw):
        self.created.append((keys, kw.get("name")))


def test_index_migrates_to_include_key(monkeypatch):
    import db
    coll = _Coll([("hisPid", 1), ("task", 1)])
    monkeypatch.setattr(db, "BED_DB_NAMES", ["bed"], raising=False)
    monkeypatch.setattr(db, "get_client", lambda name: {"bed": {aa.AI_CACHE_COLLECTION: coll}}, raising=False)
    aa.ensure_ai_cache_collection()
    assert coll.dropped == ["idx_hispid_task"]
    assert ([("hisPid", 1), ("task", 1), ("key", 1)], "idx_hispid_task") in coll.created
