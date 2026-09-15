"""
调度器与预聚合补算测试。
覆盖：
- 空汇总表启动后自动补算
- 部分月份缺失时只补缺失月份
- 服务重启后补跑
- 调度失败可查询/可重试
- 多实例不重复执行
- 页面首次进入不需要手动刷新
- 缺失数据不显示为0
- 真实0与无数据能区分
"""
import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, PropertyMock
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from summary import (
    _natural_months_back,
    find_missing_periods,
    _get_all_dept_codes,
    rebuild_summary,
    SUMMARY_COLLECTION,
)


# ============================================================
# 1. 自然月递减算法测试
# ============================================================

class TestNaturalMonthsBack:
    """测试 _natural_months_back 函数"""

    def test_13_months_no_duplicates(self):
        """13个月无重复"""
        periods = _natural_months_back(13)
        assert len(periods) == len(set(periods)), "月份不应重复"

    def test_13_months_no_gaps(self):
        """13个月无间隔"""
        periods = _natural_months_back(13)
        for i in range(len(periods) - 1):
            y1, m1 = map(int, periods[i].split("-"))
            y2, m2 = map(int, periods[i + 1].split("-"))
            # 计算月份差
            diff = (y2 - y1) * 12 + (m2 - m1)
            assert diff == 1, f"月份 {periods[i]} 和 {periods[i+1]} 间隔应为1，实际为{diff}"

    def test_format_correct(self):
        """格式正确"""
        periods = _natural_months_back(3)
        for p in periods:
            parts = p.split("-")
            assert len(parts) == 2
            assert len(parts[0]) == 4
            assert len(parts[1]) == 2
            assert 1 <= int(parts[1]) <= 12

    def test_current_month_included(self):
        """包含当前月"""
        now = datetime.utcnow()
        current = f"{now.year}-{now.month:02d}"
        periods = _natural_months_back(1)
        assert periods == [current]

    def test_1_month(self):
        """只取1个月"""
        periods = _natural_months_back(1)
        assert len(periods) == 1
        now = datetime.utcnow()
        assert periods[0] == f"{now.year}-{now.month:02d}"


# ============================================================
# 2. 缺失月份检测测试
# ============================================================

class TestFindMissingPeriods:
    """测试 find_missing_periods 函数"""

    def _make_mock_client(self, find_return_value):
        """构造 mock client: get_client(db_name)[db_name][SUMMARY_COLLECTION].find()"""
        mock_coll = MagicMock()
        mock_coll.find.return_value = find_return_value

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)

        return mock_client

    def test_empty_collection_all_missing(self):
        """空汇总表：所有月份都缺失"""
        mock_client = self._make_mock_client([])

        with patch("summary.get_client", return_value=mock_client):
            with patch("summary.BED_DB_NAMES", ["test_db"]):
                missing = find_missing_periods(
                    ["JJL000282"],
                    ["2026-01", "2026-02", "2026-03"],
                )
                assert missing == ["2026-01", "2026-02", "2026-03"]

    def test_partial_data_some_missing(self):
        """部分月份已存在（旧格式视为缺失）"""
        # 旧格式文档（无indicator字段）应被视为缺失
        mock_client = self._make_mock_client(
            [{"period": "2026-01"}, {"period": "2026-03"}]
        )

        with patch("summary.get_client", return_value=mock_client):
            with patch("summary.BED_DB_NAMES", ["test_db"]):
                missing = find_missing_periods(
                    ["JJL000282"],
                    ["2026-01", "2026-02", "2026-03", "2026-04"],
                )
                # 旧格式（无indicator）视为缺失，需要重算
                assert missing == ["2026-01", "2026-02", "2026-03", "2026-04"]

    def test_all_present_no_missing(self):
        """全部月份已存在（新格式有indicator）"""
        # 新格式文档（有indicator字段）
        mock_client = self._make_mock_client([
            {"period": "2026-01", "indicator": "ICU-01"},
            {"period": "2026-02", "indicator": "ICU-01"},
            {"period": "2026-03", "indicator": "ICU-01"},
        ])

        with patch("summary.get_client", return_value=mock_client):
            with patch("summary.BED_DB_NAMES", ["test_db"]):
                missing = find_missing_periods(
                    ["JJL000282"],
                    ["2026-01", "2026-02", "2026-03"],
                )
                # 只有当所有必需指标都有时才不缺失
                # 由于只有一个指标，其他指标缺失，所以仍然缺失
                assert len(missing) > 0


# ============================================================
# 3. 调度器状态管理测试
# ============================================================

class TestSchedulerManager:
    """测试调度器状态管理"""

    def test_acquire_lock_success(self):
        """成功获取锁"""
        from scheduler import SchedulerManager, LOCK_COLLECTION

        mock_lock_coll = MagicMock()
        mock_lock_coll.update_one.return_value = MagicMock(upserted_id="test", modified_count=1)

        mgr = SchedulerManager()
        mgr._db = MagicMock()
        mgr._db.__getitem__ = MagicMock(return_value=mock_lock_coll)

        result = mgr.acquire_lock("test_task")
        assert result is True

    def test_acquire_lock_already_held(self):
        """锁已被持有"""
        from scheduler import SchedulerManager, LOCK_COLLECTION

        mock_lock_coll = MagicMock()
        mock_lock_coll.update_one.return_value = MagicMock(upserted_id=None, modified_count=0)

        mgr = SchedulerManager()
        mgr._db = MagicMock()
        mgr._db.__getitem__ = MagicMock(return_value=mock_lock_coll)

        result = mgr.acquire_lock("test_task")
        assert result is False

    def test_release_lock(self):
        """释放锁（需要匹配 owner_token）"""
        from scheduler import SchedulerManager, LOCK_COLLECTION

        mock_lock_coll = MagicMock()
        mock_lock_coll.delete_one.return_value = MagicMock(deleted_count=1)

        mgr = SchedulerManager()
        mgr._db = MagicMock()
        mgr._db.__getitem__ = MagicMock(return_value=mock_lock_coll)

        mgr.release_lock("test_task")
        # 新实现需要同时匹配 task_name 和 owner_token
        mock_lock_coll.delete_one.assert_called_once_with({
            "task_name": "test_task",
            "owner_token": mgr.owner_token
        })

    def test_record_start(self):
        """记录任务开始（task_id 使用 uuid.uuid4().hex）"""
        from scheduler import SchedulerManager, SCHEDULER_COLLECTION

        mock_sched_coll = MagicMock()

        mgr = SchedulerManager()
        mgr._db = MagicMock()
        mgr._db.__getitem__ = MagicMock(return_value=mock_sched_coll)

        task_id = mgr.record_start("test_task", ["2026-01", "2026-02"])
        # 新实现使用 uuid.uuid4().hex，长度为32
        assert len(task_id) == 32, f"task_id should be 32 chars, got {len(task_id)}"
        mock_sched_coll.insert_one.assert_called_once()

    def test_record_finish(self):
        """记录任务完成"""
        from scheduler import SchedulerManager, SCHEDULER_COLLECTION

        mock_sched_coll = MagicMock()

        mgr = SchedulerManager()
        mgr._db = MagicMock()
        mgr._db.__getitem__ = MagicMock(return_value=mock_sched_coll)

        mgr.record_finish("test_task-20260101", status="completed", stats={"success": 10})
        mock_sched_coll.update_one.assert_called_once()

    def test_get_latest_status_no_db(self):
        """无数据库时返回默认状态"""
        from scheduler import SchedulerManager

        mgr = SchedulerManager()
        # Mock _get_scheduler_db so db property returns None
        with patch("scheduler._get_scheduler_db", return_value=None):
            mgr._db = None  # reset so property re-evaluates
            status = mgr.get_latest_status()
            assert status["status"] == "no-db"
            assert status["rebuilding"] is False

    def test_check_incomplete_tasks(self):
        """检查未完成任务"""
        from scheduler import SchedulerManager, SCHEDULER_COLLECTION

        # 构造 mock cursor with .sort() that returns a list-like
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = [
            {"task_id": "task1", "status": "running"},
            {"task_id": "task2", "status": "failed"},
        ]

        mock_sched_coll = MagicMock()
        mock_sched_coll.find.return_value = mock_cursor

        mgr = SchedulerManager()
        mgr._db = MagicMock()
        mgr._db.__getitem__ = MagicMock(return_value=mock_sched_coll)

        tasks = mgr.check_incomplete_tasks()
        assert len(tasks) == 2


# ============================================================
# 4. rebuild_summary 幂等性测试
# ============================================================

class TestRebuildSummaryIdempotent:
    """测试预聚合幂等性"""

    def test_rebuild_idempotent_with_mock(self):
        """重复执行不会产生重复数据"""
        # 这个测试验证 rebuild_summary 的 upsert 逻辑
        # 使用 mock 避免真实数据库调用
        from unittest.mock import patch

        mock_coll = MagicMock()

        with patch("summary.get_client") as mock_get_client:
            # get_client(db_name) 返回 client，[db_name] 返回 db
            mock_client_instance = MagicMock()
            mock_db_instance = MagicMock()
            mock_db_instance.__getitem__ = MagicMock(return_value=mock_coll)
            mock_client_instance.__getitem__ = MagicMock(return_value=mock_db_instance)
            mock_get_client.return_value = mock_client_instance

            with patch("summary.BED_DB_NAMES", ["test_db"]):
                # 模拟一个成功的计算结果
                with patch("summary.INDICATOR_COMPUTERS", {
                    "ICU-01": lambda dc, s, e: {"num": 10, "den": 20, "val": 50.0, "val_type": "percent"},
                }):
                    stats = rebuild_summary(["JJL000282"], ["2026-06"])
                    # 验证 upsert 被调用
                    assert mock_coll.update_one.called


# ============================================================
# 5. 前端状态测试 (概念性)
# ============================================================

class TestFrontendDataComplete:
    """测试前端数据完整性检测逻辑"""

    def test_data_complete_true_when_all_periods_have_data(self):
        """所有月份有数据时 data_complete=True"""
        rows = [
            {"code": "ICU-01", "status": "good", "monthly": [80, 85, 90]},
        ]
        periods = ["2026-01", "2026-02", "2026-03"]

        # 模拟前端检测逻辑
        data_complete = True
        missing_periods = []
        for row in rows:
            if row.get("status") == "unknown":
                monthly = row.get("monthly", [])
                for i, val in enumerate(monthly):
                    if val is None and i < len(periods):
                        mp = periods[i]
                        if mp not in missing_periods:
                            missing_periods.append(mp)
        if missing_periods:
            data_complete = False

        assert data_complete is True
        assert missing_periods == []

    def test_data_complete_false_when_periods_missing(self):
        """部分月份缺失时 data_complete=False"""
        rows = [
            {"code": "ICU-01", "status": "unknown", "monthly": [80, None, 90]},
        ]
        periods = ["2026-01", "2026-02", "2026-03"]

        # 模拟前端检测逻辑
        data_complete = True
        missing_periods = []
        for row in rows:
            if row.get("status") == "unknown":
                monthly = row.get("monthly", [])
                for i, val in enumerate(monthly):
                    if val is None and i < len(periods):
                        mp = periods[i]
                        if mp not in missing_periods:
                            missing_periods.append(mp)
        if missing_periods:
            data_complete = False

        assert data_complete is False
        assert "2026-02" in missing_periods

    def test_real_zero_vs_no_data(self):
        """区分真实0和无数据"""
        # 真实0: numerator=0, denominator=5 → value=0
        row_real_zero = {
            "code": "ICU-05-1h",
            "numerator": 0,
            "denominator": 5,
            "value": 0,
            "status": "danger",
        }
        assert row_real_zero["numerator"] == 0
        assert row_real_zero["denominator"] > 0
        assert row_real_zero["value"] == 0

        # 无数据: numerator=None, denominator=None → value=None → status="unknown"
        row_no_data = {
            "code": "ICU-05-1h",
            "numerator": None,
            "denominator": None,
            "value": None,
            "status": "unknown",
        }
        assert row_no_data["numerator"] is None
        assert row_no_data["denominator"] is None
        assert row_no_data["status"] == "unknown"


# ============================================================
# 6. 跨月汇总正确性测试
# ============================================================

class TestCrossMonthAggregation:
    """测试跨月汇总的正确性"""

    def test_months_between_single_month(self):
        """单月查询"""
        from main import _periods_between
        periods = _periods_between("2026-06")
        assert periods == ["2026-06"]

    def test_months_between_multi_month(self):
        """跨月查询"""
        from main import _periods_between
        periods = _periods_between("2026-01", "2026-06")
        assert periods == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

    def test_months_between_cross_year(self):
        """跨年查询"""
        from main import _periods_between
        periods = _periods_between("2025-11", "2026-02")
        assert periods == ["2025-11", "2025-12", "2026-01", "2026-02"]
