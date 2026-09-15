"""
调度状态管理模块。
提供运行锁、状态记录、失败重试功能。
使用 MongoDB 集合实现，支持多实例部署。

关键设计：
- 分布式锁使用 owner_token 防止误释放
- task_id 使用 uuid.uuid4().hex 保证全局唯一
- heartbeat_at 用于检测僵尸任务
- DuplicateKeyError 时返回 False（失败关闭）
"""
import logging
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("scheduler")

SCHEDULER_COLLECTION = "icu_scheduler_status"
LOCK_COLLECTION = "icu_scheduler_lock"

# 僵尸任务检测超时（秒）
ZOMBIE_TIMEOUT_SEC = 1800  # 30分钟无心跳视为僵尸


def _get_scheduler_db():
    """获取调度状态数据库连接。"""
    from db import get_client, BED_DB_NAMES
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            return db
        except Exception:
            continue
    return None


def ensure_scheduler_collections():
    """创建调度相关集合索引（幂等）。"""
    db = _get_scheduler_db()
    if db is None:
        return
    try:
        # 调度状态表索引
        db[SCHEDULER_COLLECTION].create_index(
            [("task_id", 1)],
            unique=True,
            background=True,
        )
        db[SCHEDULER_COLLECTION].create_index(
            [("task_name", 1), ("started_at", -1)],
            background=True,
        )
        db[SCHEDULER_COLLECTION].create_index(
            [("status", 1)],
            background=True,
        )
        # 运行锁索引
        db[LOCK_COLLECTION].create_index(
            [("task_name", 1)],
            unique=True,
            background=True,
        )
        logger.info("[scheduler] Collections and indexes ensured")
    except Exception as e:
        logger.error("[scheduler] Failed to ensure collections: %s", e)


class SchedulerManager:
    """调度状态管理器。"""

    def __init__(self):
        self._db = None
        self._owner_token = uuid.uuid4().hex  # 本实例唯一标识

    @property
    def db(self):
        if self._db is None:
            self._db = _get_scheduler_db()
        return self._db

    @property
    def owner_token(self):
        return self._owner_token

    def acquire_lock(self, task_name: str, timeout_sec: int = 3600) -> bool:
        """
        获取运行锁（防止多实例重复执行）。

        使用 MongoDB update_one + upsert 原子操作实现分布式锁。
        超时时间默认1小时，防止死锁。

        Returns:
            True: 成功获取锁
            False: 锁已被占用或获取失败（失败关闭）
        """
        if self.db is None:
            logger.warning("[scheduler] No DB available, cannot acquire lock")
            return False  # 失败关闭：无DB时不允许执行

        try:
            now = datetime.utcnow()
            result = self.db[LOCK_COLLECTION].update_one(
                {
                    "task_name": task_name,
                    "$or": [
                        {"locked_at": {"$lt": now - timedelta(seconds=timeout_sec)}},
                        {"locked_at": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "task_name": task_name,
                        "locked_at": now,
                        "heartbeat_at": now,
                        "owner_token": self._owner_token,
                    }
                },
                upsert=True,
            )
            if result.upserted_id or result.modified_count > 0:
                logger.info("[scheduler] Lock acquired for %s (owner=%s)", task_name, self._owner_token[:8])
                return True
            else:
                logger.info("[scheduler] Lock already held for %s", task_name)
                return False
        except Exception as e:
            # DuplicateKeyError 或其他数据库异常都返回 False
            logger.error("[scheduler] Failed to acquire lock: %s", e)
            return False  # 失败关闭

    def release_lock(self, task_name: str):
        """
        释放运行锁。只有锁的持有者（匹配 owner_token）才能释放。
        """
        if self.db is None:
            return
        try:
            result = self.db[LOCK_COLLECTION].delete_one({
                "task_name": task_name,
                "owner_token": self._owner_token,
            })
            if result.deleted_count > 0:
                logger.info("[scheduler] Lock released for %s", task_name)
            else:
                logger.warning("[scheduler] Lock not owned by this instance, skip release for %s", task_name)
        except Exception as e:
            logger.error("[scheduler] Failed to release lock: %s", e)

    def renew_lock(self, task_name: str) -> bool:
        """
        续期锁（更新 heartbeat_at）。只有锁的持有者才能续期。
        """
        if self.db is None:
            return False
        try:
            now = datetime.utcnow()
            result = self.db[LOCK_COLLECTION].update_one(
                {
                    "task_name": task_name,
                    "owner_token": self._owner_token,
                },
                {"$set": {"heartbeat_at": now}},
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error("[scheduler] Failed to renew lock: %s", e)
            return False

    def record_start(self, task_name: str, periods: list, indicators: list = None,
                     extra_info: dict = None) -> str:
        """
        记录任务开始。task_id 使用 uuid.uuid4().hex 保证全局唯一。

        Returns:
            task_id: 任务ID
        """
        if self.db is None:
            return "no-db"

        task_id = uuid.uuid4().hex
        now = datetime.utcnow()
        doc = {
            "task_id": task_id,
            "task_name": task_name,
            "status": "running",
            "started_at": now,
            "heartbeat_at": now,
            "finished_at": None,
            "periods": periods,
            "indicators": indicators or [],
            "error": None,
            "stats": None,
            "owner_token": self._owner_token,
        }
        if extra_info:
            doc.update(extra_info)

        try:
            self.db[SCHEDULER_COLLECTION].insert_one(doc)
            logger.info("[scheduler] Task started: %s (periods=%d)", task_id, len(periods))
        except Exception as e:
            logger.error("[scheduler] Failed to record start: %s", e)

        return task_id

    def update_heartbeat(self, task_id: str):
        """更新任务心跳。"""
        if self.db is None:
            return
        try:
            self.db[SCHEDULER_COLLECTION].update_one(
                {"task_id": task_id},
                {"$set": {"heartbeat_at": datetime.utcnow()}},
            )
        except Exception as e:
            logger.error("[scheduler] Failed to update heartbeat: %s", e)

    def record_finish(self, task_id: str, status: str = "completed",
                      error: str = None, stats: dict = None):
        """记录任务完成。"""
        if self.db is None:
            return

        update = {
            "$set": {
                "status": status,
                "finished_at": datetime.utcnow(),
                "heartbeat_at": datetime.utcnow(),
            }
        }
        if error:
            update["$set"]["error"] = error[:1000]
        if stats:
            update["$set"]["stats"] = stats

        try:
            self.db[SCHEDULER_COLLECTION].update_one(
                {"task_id": task_id},
                update,
            )
            logger.info("[scheduler] Task finished: %s (status=%s)", task_id, status)
        except Exception as e:
            logger.error("[scheduler] Failed to record finish: %s", e)

    def mark_zombie_tasks(self, timeout_sec: int = ZOMBIE_TIMEOUT_SEC) -> int:
        """
        检测并标记僵尸任务。
        状态为 running 且 heartbeat_at 超过 timeout_sec 的任务标记为 interrupted。

        Returns:
            被标记的任务数量
        """
        if self.db is None:
            return 0

        cutoff = datetime.utcnow() - timedelta(seconds=timeout_sec)
        try:
            result = self.db[SCHEDULER_COLLECTION].update_many(
                {
                    "status": "running",
                    "heartbeat_at": {"$lt": cutoff},
                },
                {
                    "$set": {
                        "status": "interrupted",
                        "finished_at": datetime.utcnow(),
                        "error": "Zombie task detected: no heartbeat for {} seconds".format(timeout_sec),
                    }
                },
            )
            count = result.modified_count
            if count > 0:
                logger.warning("[scheduler] Marked %d zombie tasks as interrupted", count)
            return count
        except Exception as e:
            logger.error("[scheduler] Failed to mark zombie tasks: %s", e)
            return 0

    def check_incomplete_tasks(self, max_age_hours: int = 24) -> list:
        """
        检查未完成/失败的任务。

        Returns:
            未完成任务列表
        """
        if self.db is None:
            return []

        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        try:
            tasks = list(self.db[SCHEDULER_COLLECTION].find(
                {
                    "status": {"$in": ["running", "failed", "interrupted"]},
                    "started_at": {"$gte": cutoff},
                },
                {"_id": 0},
            ).sort("started_at", -1))
            return tasks
        except Exception as e:
            logger.error("[scheduler] Failed to check incomplete tasks: %s", e)
            return []

    def get_latest_status(self) -> dict:
        """获取最新的调度状态。"""
        if self.db is None:
            return {"status": "no-db", "rebuilding": False}

        try:
            # 先标记僵尸任务
            self.mark_zombie_tasks()

            latest = self.db[SCHEDULER_COLLECTION].find_one(
                {"_id": {"$ne": None}},
                {"_id": 0},
                sort=[("started_at", -1)],
            )
            if not latest:
                return {"status": "never_run", "rebuilding": False}

            return {
                "task_id": latest.get("task_id"),
                "status": latest.get("status"),
                "started_at": latest.get("started_at", "").isoformat() if latest.get("started_at") else None,
                "finished_at": latest.get("finished_at", "").isoformat() if latest.get("finished_at") else None,
                "heartbeat_at": latest.get("heartbeat_at", "").isoformat() if latest.get("heartbeat_at") else None,
                "periods": latest.get("periods", []),
                "error": latest.get("error"),
                "rebuilding": latest.get("status") == "running",
            }
        except Exception as e:
            logger.error("[scheduler] Failed to get status: %s", e)
            return {"status": "error", "rebuilding": False}

    def get_last_success_at(self) -> Optional[str]:
        """获取最后一次成功完成的时间。"""
        if self.db is None:
            return None

        try:
            doc = self.db[SCHEDULER_COLLECTION].find_one(
                {"status": "completed"},
                {"finished_at": 1, "_id": 0},
                sort=[("finished_at", -1)],
            )
            if doc and doc.get("finished_at"):
                return doc["finished_at"].isoformat()
        except Exception:
            pass
        return None


# 全局实例
scheduler = SchedulerManager()
