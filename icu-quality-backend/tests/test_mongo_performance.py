"""
MongoDB 性能测试脚本。
验证索引创建、批量查询和查询失败与数据缺失区分。
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from scoring.lab_batch import batch_fetch_lab_observations, batch_fetch_lab_observations_with_status
from scoring.data_adapter import _fetch_lab_observations, fetch_patient_obs_meds


class TestMongoIndexes:
    """测试 MongoDB 索引"""

    def test_check_existing_indexes(self):
        """检查现有索引"""
        from db import get_client, BED_DB_NAMES

        # 尝试连接数据库
        db = None
        for db_name in BED_DB_NAMES:
            try:
                client = get_client(db_name)
                db = client[db_name]
                db.command("ping")
                break
            except Exception:
                continue

        if db is None:
            pytest.skip("Cannot connect to database")

        # 检查 VI_ICU_EXAM 索引
        exam_indexes = list(db.VI_ICU_EXAM.list_indexes())
        print("\n[VI_ICU_EXAM] 索引列表:")
        for idx in exam_indexes:
            print(f"  - {idx.get('name')}: {idx.get('key')}")

        # 检查 VI_ICU_EXAM_ITEM 索引
        item_indexes = list(db.VI_ICU_EXAM_ITEM.list_indexes())
        print("\n[VI_ICU_EXAM_ITEM] 索引列表:")
        for idx in item_indexes:
            print(f"  - {idx.get('name')}: {idx.get('key')}")

        # 验证关键索引存在
        exam_keys = [idx.get("key") for idx in exam_indexes]
        item_keys = [idx.get("key") for idx in item_indexes]

        # 应该有 {pid: 1, collectTime: -1} 索引
        assert {"pid": 1, "collectTime": -1} in exam_keys, \
            "VI_ICU_EXAM 缺少 {pid: 1, collectTime: -1} 索引"

        # 应该有 {examID: 1, itemCode: 1} 索引
        assert {"examID": 1, "itemCode": 1} in item_keys, \
            "VI_ICU_EXAM_ITEM 缺少 {examID: 1, itemCode: 1} 索引"


class TestBatchQuery:
    """测试批量查询"""

    def test_batch_query_no_timeout(self):
        """测试批量查询不再超时"""
        from db import get_client, BED_DB_NAMES

        # 尝试连接数据库
        db = None
        for db_name in BED_DB_NAMES:
            try:
                client = get_client(db_name)
                db = client[db_name]
                db.command("ping")
                break
            except Exception:
                continue

        if db is None:
            pytest.skip("Cannot connect to database")

        # 报错患者列表
        his_pids = ["1752815", "1686820", "1703360", "1686271", "1706236", "1706466"]

        eval_time = datetime.now(timezone.utc)
        lookback_hours = 24

        result = batch_fetch_lab_observations(db, his_pids, eval_time, lookback_hours)

        # 验证无超时
        for pid in his_pids:
            assert pid in result, f"Patient {pid} missing from result"
            print(f"Patient {pid}: {len(result[pid])} observations")

    def test_batch_query_with_status(self):
        """测试带状态的批量查询"""
        from db import get_client, BED_DB_NAMES

        # 尝试连接数据库
        db = None
        for db_name in BED_DB_NAMES:
            try:
                client = get_client(db_name)
                db = client[db_name]
                db.command("ping")
                break
            except Exception:
                continue

        if db is None:
            pytest.skip("Cannot connect to database")

        his_pids = ["1752815", "1686820"]
        eval_time = datetime.now(timezone.utc)

        result, status, failed = batch_fetch_lab_observations_with_status(
            db, his_pids, eval_time, 24
        )

        print(f"\n批量查询结果:")
        for pid in his_pids:
            print(f"  {pid}: {len(result[pid])} observations, status={status[pid]}")

        # 验证状态
        for pid in his_pids:
            assert pid in status, f"Patient {pid} missing from status"
            assert status[pid] in ["success", "no_data", "timeout", "query_error"], \
                f"Invalid status for {pid}: {status[pid]}"


class TestQueryStatus:
    """测试查询状态区分"""

    def test_fetch_lab_observations_status(self):
        """测试 _fetch_lab_observations 返回状态"""
        from db import get_client, BED_DB_NAMES

        # 尝试连接数据库
        db = None
        for db_name in BED_DB_NAMES:
            try:
                client = get_client(db_name)
                db = client[db_name]
                db.command("ping")
                break
            except Exception:
                continue

        if db is None:
            pytest.skip("Cannot connect to database")

        eval_time = datetime.now(timezone.utc)

        # 测试一个已知患者
        result = _fetch_lab_observations(db, "1752815", eval_time)

        # 验证返回结构
        assert "observations" in result, "Missing 'observations' key"
        assert "status" in result, "Missing 'status' key"
        assert "error" in result, "Missing 'error' key"
        assert "data_complete" in result, "Missing 'data_complete' key"

        # 验证状态值
        assert result["status"] in ["success", "no_data", "timeout", "query_error"], \
            f"Invalid status: {result['status']}"

        print(f"\n_fetch_lab_observations 结果:")
        print(f"  observations: {len(result['observations'])}")
        print(f"  status: {result['status']}")
        print(f"  error: {result['error']}")
        print(f"  data_complete: {result['data_complete']}")

    def test_fetch_patient_obs_meds_with_cache(self):
        """测试 fetch_patient_obs_meds 使用批量缓存"""
        from db import get_client, BED_DB_NAMES

        # 尝试连接数据库
        sc_db = None
        dc_db = None
        for db_name in BED_DB_NAMES:
            try:
                client = get_client(db_name)
                db = client[db_name]
                db.command("ping")
                if db_name == "SmartCare":
                    sc_db = db
                elif db_name == "DataCenter":
                    dc_db = db
            except Exception:
                continue

        if sc_db is None or dc_db is None:
            pytest.skip("Cannot connect to database")

        # 获取一个测试患者
        test_patient = sc_db.patient.find_one({"hisPid": {"$exists": True}})
        if not test_patient:
            pytest.skip("No test patient found")

        sc_pid = str(test_patient["_id"])
        mrn = test_patient.get("mrn", "")
        his_pid = test_patient.get("hisPid", "")

        eval_time = datetime.now(timezone.utc)
        t0 = eval_time - timedelta(hours=24)

        # 创建批量缓存
        batch_cache = {
            his_pid: {
                "observations": [
                    {
                        "code": "PLT",
                        "value_number": 150.0,
                        "unit": "10^9/L",
                        "observed_at": eval_time,
                        "item_name": "血小板",
                        "source": "VI_ICU_EXAM_ITEM"
                    }
                ],
                "status": "success",
                "error": None,
                "data_complete": True
            }
        }

        # 使用缓存
        result = fetch_patient_obs_meds(
            sc_pid=sc_pid,
            mrn=mrn,
            dc_pid=his_pid,
            t0=t0,
            eval_time=eval_time,
            batch_lab_cache=batch_cache
        )

        # 验证使用了缓存
        assert result["fetch_meta"].get("lab_source") == "batch_cache", \
            "Should use batch cache"
        assert result["fetch_meta"].get("lab_count") == 1, \
            "Should have 1 observation from cache"

        print(f"\nfetch_patient_obs_meds 使用缓存结果:")
        print(f"  lab_source: {result['fetch_meta'].get('lab_source')}")
        print(f"  lab_count: {result['fetch_meta'].get('lab_count')}")
        print(f"  lab_status: {result['fetch_meta'].get('lab_status')}")


class TestConcurrencyControl:
    """测试并发控制"""

    def test_scheduler_lock(self):
        """测试 SchedulerManager 锁机制"""
        from scheduler import SchedulerManager

        mgr = SchedulerManager()

        # 测试获取锁
        task_name = "test_concurrent_task"

        # 由于没有数据库连接，测试会跳过
        if mgr.db is None:
            pytest.skip("No database connection")

        # 获取锁
        result1 = mgr.acquire_lock(task_name)
        assert result1, "Should acquire lock"

        # 尝试再次获取（应该失败）
        result2 = mgr.acquire_lock(task_name)
        assert not result2, "Should not acquire lock twice"

        # 释放锁
        mgr.release_lock(task_name)

        # 再次获取（应该成功）
        result3 = mgr.acquire_lock(task_name)
        assert result3, "Should acquire lock after release"

        # 清理
        mgr.release_lock(task_name)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
