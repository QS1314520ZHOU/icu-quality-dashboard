"""Integration coverage for the exclusion update against a real isolated mongod."""
import socket
import subprocess
import time

import pytest


@pytest.fixture(scope="module")
def mongo(tmp_path_factory):
    pytest.importorskip("pymongo")
    from pymongo import MongoClient
    port_socket = socket.socket()
    port_socket.bind(("127.0.0.1", 0))
    port = port_socket.getsockname()[1]
    port_socket.close()
    dbpath = tmp_path_factory.mktemp("mongo")
    proc = subprocess.Popen([
        r"C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe",
        "--dbpath", str(dbpath), "--port", str(port), "--bind_ip", "127.0.0.1", "--quiet",
    ])
    client = MongoClient(f"mongodb://127.0.0.1:{port}", serverSelectionTimeoutMS=200)
    for _ in range(50):
        try:
            client.admin.command("ping")
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("isolated mongod did not start")
    yield client
    client.close()
    proc.terminate()
    proc.wait(timeout=10)


def test_exclusion_save_restore_resave_preserves_audit(monkeypatch, mongo):
    import main

    monkeypatch.setattr(main, "BED_DB_NAMES", ["test"])
    monkeypatch.setattr(main, "get_client", lambda name: {name: mongo[name]})
    monkeypatch.setattr(main, "_trigger_summary_rebuild", lambda *args, **kwargs: None)
    main.ensure_exclusion_collection()
    body = {
        "period": "2026-01", "exclusion_key": "event-1", "patient_id": "event-1",
        "reason_code": "other", "operator": "tester", "icu_unit": "all",
    }
    assert main.add_exclusion("ICU-05-1h", dict(body))["ok"] is True
    coll = mongo.test.icu_indicator_exclusion
    first = coll.find_one({"exclusion_key": "event-1"})
    assert first["excluded"] is True and len(first["history"]) == 1
    assert main.remove_exclusion("ICU-05-1h", "event-1", "2026-01", "all")["ok"] is True
    assert main.add_exclusion("ICU-05-1h", dict(body))["ok"] is True
    final = coll.find_one({"exclusion_key": "event-1"})
    assert final["excluded"] is True
    assert final["created_at"] == first["created_at"]
    assert [x["action"] for x in final["history"]] == ["exclude", "restore", "exclude"]
