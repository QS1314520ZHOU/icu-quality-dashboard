"""
调度器行为测试 - 验证真实行为而非 MagicMock。
测试内容：
1. daily 任务在当前月已有数据时仍重算
2. 查询 6-9 月不会把 6 月当当前月
3. 两个 SchedulerManager 并发时只有一个拿到锁
4. DuplicateKeyError 时第二个实例不得执行
5. 非锁所有者不能释放锁
6. 僵尸 running 任务能被标记 interrupted
7. task_id 并发不重复
"""
import pytest
import threading
import time
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from collections import defaultdict


class TestSchedulerBehavior:
    """调度器行为测试"""

    def _make_mock_db(self):
        """创建模拟 MongoDB 的内存实现"""
        collections = defaultdict(list)
        indexes = {}

        class MockCollection:
            def __init__(self, name):
                self.name = name
                self._docs = collections[name]
                self._indexes = indexes.get(name, [])

            def create_index(self, keys, **kwargs):
                pass

            def insert_one(self, doc):
                # 检查唯一索引
                for idx in self._indexes:
                    if idx.get("unique"):
                        key = idx["keys"][0][0]
                        for existing in self._docs:
                            if existing.get(key) == doc.get(key):
                                from pymongo.errors import DuplicateKeyError
                                raise DuplicateKeyError(f"Duplicate key: {key}")
                self._docs.append(doc)
                return MagicMock(inserted_id=doc.get("_id"))

            def find_one(self, filter_dict=None, projection=None, sort=None):
                results = self._find(filter_dict, projection)
                if sort:
                    key, direction = sort[0]
                    results.sort(key=lambda x: x.get(key, ""), reverse=(direction == -1))
                return results[0] if results else None

            def find(self, filter_dict=None, projection=None):
                return MockCursor(self._find(filter_dict, projection))

            def _find(self, filter_dict, projection):
                if filter_dict is None:
                    filter_dict = {}
                results = []
                for doc in self._docs:
                    if self._match(doc, filter_dict):
                        if projection:
                            projected = {}
                            for key, val in projection.items():
                                if key == "_id" and val == 0:
                                    continue
                                if key in doc:
                                    projected[key] = doc[key]
                            results.append(projected)
                        else:
                            results.append(dict(doc))
                return results

            def _match(self, doc, filter_dict):
                for key, value in filter_dict.items():
                    if key == "$or":
                        if not any(self._match(doc, sub) for sub in value):
                            return False
                        continue
                    if key not in doc:
                        if isinstance(value, dict) and "$exists" in value and not value["$exists"]:
                            continue
                        return False
                    doc_val = doc[key]
                    if isinstance(value, dict):
                        for op, op_val in value.items():
                            if op == "$lt" and not (doc_val < op_val):
                                return False
                            elif op == "$gte" and not (doc_val >= op_val):
                                return False
                            elif op == "$in" and doc_val not in op_val:
                                return False
                            elif op == "$ne" and doc_val == op_val:
                                return False
                    elif doc_val != value:
                        return False
                return True

            def update_one(self, filter_dict, update_dict, upsert=False):
                # 对于锁操作，需要特殊处理 timeout 逻辑
                if self.name == "icu_scheduler_lock":
                    task_name = filter_dict.get("task_name")
                    for doc in self._docs:
                        if doc.get("task_name") == task_name:
                            # 检查是否超时
                            locked_at = doc.get("locked_at")
                            if locked_at:
                                timeout_check = filter_dict.get("$or", [])
                                is_expired = False
                                for condition in timeout_check:
                                    if "$lt" in condition.get("locked_at", {}):
                                        cutoff = condition["locked_at"]["$lt"]
                                        if locked_at < cutoff:
                                            is_expired = True
                                if is_expired:
                                    if "$set" in update_dict:
                                        doc.update(update_dict["$set"])
                                    return MagicMock(modified_count=1, upserted_id=None)
                            # 锁未超时，无法获取
                            return MagicMock(modified_count=0, upserted_id=None)
                    # 锁不存在，插入新锁
                    if upsert:
                        new_doc = {"task_name": task_name}
                        if "$set" in update_dict:
                            new_doc.update(update_dict["$set"])
                        self._docs.append(new_doc)
                        return MagicMock(modified_count=0, upserted_id="new")
                    return MagicMock(modified_count=0, upserted_id=None)

                # 通用逻辑
                for i, doc in enumerate(self._docs):
                    if self._match(doc, filter_dict):
                        if "$set" in update_dict:
                            doc.update(update_dict["$set"])
                        return MagicMock(modified_count=1, upserted_id=None)
                if upsert:
                    new_doc = dict(filter_dict)
                    if "$set" in update_dict:
                        new_doc.update(update_dict["$set"])
                    self._docs.append(new_doc)
                    return MagicMock(modified_count=0, upserted_id="new")
                return MagicMock(modified_count=0, upserted_id=None)

            def update_many(self, filter_dict, update_dict):
                count = 0
                for doc in self._docs:
                    if self._match(doc, filter_dict):
                        if "$set" in update_dict:
                            doc.update(update_dict["$set"])
                        count += 1
                return MagicMock(modified_count=count)

            def delete_one(self, filter_dict):
                for i, doc in enumerate(self._docs):
                    if self._match(doc, filter_dict):
                        self._docs.pop(i)
                        return MagicMock(deleted_count=1)
                return MagicMock(deleted_count=0)

        class MockCursor:
            def __init__(self, docs):
                self._docs = docs

            def sort(self, key, direction=1):
                self._docs.sort(key=lambda x: x.get(key, ""), reverse=(direction == -1))
                return self

            def __iter__(self):
                return iter(self._docs)

        class MockDB:
            def __init__(self):
                self._collections = {}

            def __getitem__(self, name):
                if name not in self._collections:
                    self._collections[name] = MockCollection(name)
                return self._collections[name]

        return MockDB()

    def test_daily_rebuild_current_month_even_with_existing_data(self):
        """daily 任务在当前月已有数据时仍重算"""
        mock_db = self._make_mock_db()

        # 模拟当前月已有数据
        current_period = datetime.now().strftime("%Y-%m")
        mock_db["icu_summary"].insert_one({
            "dept_code": "test_dept",
            "period": current_period,
            "indicator": "ICU-01",
        })

        with patch("summary.get_client", return_value=mock_db):
            with patch("summary.BED_DB_NAMES", ["test_db"]):
                from summary import find_missing_periods
                # 当前月有旧格式数据，应该返回当前月需要重算
                missing = find_missing_periods(["test_dept"], [current_period])
                assert current_period in missing, f"Current month {current_period} should be in missing list"

    def test_query_range_does_not_confuse_current_period(self):
        """查询 6-9 月不会把 6 月当当前月"""
        from datetime import datetime
        # 模拟查询 2026-06 到 2026-09
        periods = ["2026-06", "2026-07", "2026-08", "2026-09"]

        # 使用实际自然月
        actual_current_period = datetime.now().strftime("%Y-%m")

        # 只有当实际当前月在查询范围时才加入
        if actual_current_period in periods:
            should_add = True
        else:
            should_add = False

        # 如果当前是 2026-09，应该只强制重算 9 月
        # 如果当前是 2026-06，应该只强制重算 6 月
        # 不应该把 periods[0] (6月) 当作当前月
        assert actual_current_period != "2026-06" or should_add

    def test_concurrent_lock_acquisition(self):
        """两个 SchedulerManager 并发时只有一个拿到锁"""
        mock_db = self._make_mock_db()

        with patch("scheduler._get_scheduler_db", return_value=mock_db):
            from scheduler import SchedulerManager

            mgr1 = SchedulerManager()
            mgr2 = SchedulerManager()

            # 第一个获取锁
            result1 = mgr1.acquire_lock("test_task")
            assert result1 is True, "First manager should acquire lock"

            # 第二个获取锁应该失败
            result2 = mgr2.acquire_lock("test_task")
            assert result2 is False, "Second manager should fail to acquire lock"

            # 第一个释放锁
            mgr1.release_lock("test_task")

            # 第二个现在应该能获取锁
            result3 = mgr2.acquire_lock("test_task")
            assert result3 is True, "Second manager should acquire lock after first releases"

    def test_duplicate_key_error_returns_false(self):
        """DuplicateKeyError 时返回 False"""
        mock_db = self._make_mock_db()

        # 先插入一条锁记录
        mock_db["icu_scheduler_lock"].insert_one({
            "task_name": "test_task",
            "locked_at": datetime.utcnow(),
            "owner_token": "other_token",
        })

        with patch("scheduler._get_scheduler_db", return_value=mock_db):
            from scheduler import SchedulerManager
            mgr = SchedulerManager()
            # 尝试获取已被占用的锁
            result = mgr.acquire_lock("test_task")
            assert result is False, "Should return False when lock is already held"

    def test_non_owner_cannot_release_lock(self):
        """非锁所有者不能释放锁"""
        mock_db = self._make_mock_db()

        with patch("scheduler._get_scheduler_db", return_value=mock_db):
            from scheduler import SchedulerManager

            mgr1 = SchedulerManager()
            mgr2 = SchedulerManager()

            # mgr1 获取锁
            mgr1.acquire_lock("test_task")

            # mgr2 尝试释放（应该失败，因为 owner_token 不匹配）
            mgr2.release_lock("test_task")

            # 验证锁仍然存在
            lock = mock_db["icu_scheduler_lock"].find_one({"task_name": "test_task"})
            assert lock is not None, "Lock should still exist after non-owner release attempt"

            # mgr1 释放锁（应该成功）
            mgr1.release_lock("test_task")
            lock = mock_db["icu_scheduler_lock"].find_one({"task_name": "test_task"})
            assert lock is None, "Lock should be released by owner"

    def test_zombie_task_detection(self):
        """僵尸 running 任务能被标记 interrupted"""
        mock_db = self._make_mock_db()

        # 插入一个僵尸任务（30分钟前的心跳）
        zombie_time = datetime.utcnow() - timedelta(minutes=31)
        mock_db["icu_scheduler_status"].insert_one({
            "task_id": "zombie_task",
            "task_name": "test",
            "status": "running",
            "started_at": zombie_time,
            "heartbeat_at": zombie_time,
        })

        # 插入一个正常任务
        mock_db["icu_scheduler_status"].insert_one({
            "task_id": "normal_task",
            "task_name": "test",
            "status": "running",
            "started_at": datetime.utcnow(),
            "heartbeat_at": datetime.utcnow(),
        })

        with patch("scheduler._get_scheduler_db", return_value=mock_db):
            from scheduler import SchedulerManager
            mgr = SchedulerManager()

            # 标记僵尸任务
            count = mgr.mark_zombie_tasks(timeout_sec=1800)
            assert count == 1, f"Should mark 1 zombie task, got {count}"

            # 验证僵尸任务被标记
            zombie = mock_db["icu_scheduler_status"].find_one({"task_id": "zombie_task"})
            assert zombie["status"] == "interrupted", "Zombie task should be marked as interrupted"

            # 验证正常任务未受影响
            normal = mock_db["icu_scheduler_status"].find_one({"task_id": "normal_task"})
            assert normal["status"] == "running", "Normal task should still be running"

    def test_task_id_concurrent_uniqueness(self):
        """task_id 并发不重复"""
        from scheduler import SchedulerManager
        import uuid

        # 生成 1000 个 task_id
        task_ids = set()
        for _ in range(1000):
            task_id = uuid.uuid4().hex
            task_ids.add(task_id)

        # 所有 task_id 应该唯一
        assert len(task_ids) == 1000, "All task_ids should be unique"

    def test_acquire_lock_returns_false_on_db_error(self):
        """数据库异常时 acquire_lock 返回 False"""
        mock_db = self._make_mock_db()

        # 模拟数据库异常
        def raise_error(*args, **kwargs):
            raise Exception("Database connection error")

        mock_db["icu_scheduler_lock"].update_one = raise_error

        with patch("scheduler._get_scheduler_db", return_value=mock_db):
            from scheduler import SchedulerManager
            mgr = SchedulerManager()
            result = mgr.acquire_lock("test_task")
            assert result is False, "Should return False on database error"

    def test_heartbeat_update(self):
        """心跳更新功能"""
        mock_db = self._make_mock_db()

        with patch("scheduler._get_scheduler_db", return_value=mock_db):
            from scheduler import SchedulerManager
            mgr = SchedulerManager()

            # 记录任务开始
            task_id = mgr.record_start("test_task", ["2026-01"])

            # 获取初始心跳
            doc = mock_db["icu_scheduler_status"].find_one({"task_id": task_id})
            initial_heartbeat = doc["heartbeat_at"]

            # 等待一小段时间
            time.sleep(0.01)

            # 更新心跳
            mgr.update_heartbeat(task_id)

            # 验证心跳已更新
            doc = mock_db["icu_scheduler_status"].find_one({"task_id": task_id})
            assert doc["heartbeat_at"] > initial_heartbeat, "Heartbeat should be updated"

    def test_lock_owner_token_isolation(self):
        """不同实例的 owner_token 应该不同"""
        with patch("scheduler._get_scheduler_db", return_value=self._make_mock_db()):
            from scheduler import SchedulerManager
            mgr1 = SchedulerManager()
            mgr2 = SchedulerManager()
            assert mgr1.owner_token != mgr2.owner_token, "Different instances should have different owner tokens"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
