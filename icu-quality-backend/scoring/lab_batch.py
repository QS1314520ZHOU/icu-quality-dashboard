"""
MongoDB 检验数据批量查询模块。
消除 N+1 查询，支持按患者批次查询 VI_ICU_EXAM 和 VI_ICU_EXAM_ITEM。

核心设计：
1. 一次传入一批 his_pid
2. 批量查询 VI_ICU_EXAM
3. 建立 his_pid → examID/reportID 映射
4. examID/reportID 分批查询 VI_ICU_EXAM_ITEM
5. 在 Python 内按患者和时间窗分配
6. $in 列表按合理大小分块（200-500）
7. 禁止对每个患者重复扫描大表
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 医院时区: 默认 Asia/Shanghai
_HOSPITAL_TZ = ZoneInfo("Asia/Shanghai")

# $in 列表分块大小
CHUNK_SIZE = 200

# itemCode → 标准码映射 (多编码兼容)
LAB_MAP = {
    "PLT": "PLT",
    "platelet": "PLT",
    "TBIL": "TBIL",
    "sCr": "CREA",
    "Cr": "CREA",
    "CREA": "CREA",
}


def _aware(dt: datetime) -> datetime:
    """
    确保时区感知。
    数据库 naive 时间视为 Asia/Shanghai，显式本地化后转 UTC。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_HOSPITAL_TZ).astimezone(timezone.utc)
    return dt


def _safe_float(val) -> Optional[float]:
    """安全转 float，失败返回 None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def batch_fetch_lab_observations(
    dc,
    his_pids: List[str],
    eval_time: datetime,
    lookback_hours: int = 24,
) -> Dict[str, List[dict]]:
    """
    批量查询检验数据，替代逐患者 N+1 查询。

    Args:
        dc: DataCenter 数据库连接
        his_pids: 批量患者 ID 列表
        eval_time: 评估时间
        lookback_hours: 回溯窗口（小时）

    Returns:
        {his_pid: [observations]}
        每个 observation 格式:
        {
            "code": str,           # 标准码 (PLT/TBIL/CREA)
            "value_number": float, # 检验值
            "unit": str,           # 单位
            "observed_at": datetime, # 采样时间
            "item_name": str,      # 原始项目名
            "source": str,         # "VI_ICU_EXAM_ITEM"
        }
    """
    window_start = eval_time - timedelta(hours=lookback_hours)
    result = {pid: [] for pid in his_pids}

    if not his_pids or dc is None:
        return result

    logger.info("batch_fetch_lab: %d patients, window=%s to %s",
                len(his_pids), window_start, eval_time)

    # Step 1: 分块查询 VI_ICU_EXAM
    exam_by_pid = {}  # his_pid → [{examID, reportID, collectTime}]

    for i in range(0, len(his_pids), CHUNK_SIZE):
        chunk = his_pids[i:i + CHUNK_SIZE]

        try:
            exam_docs = list(dc.VI_ICU_EXAM.find(
                {
                    "pid": {"$in": chunk},
                    "collectTime": {"$gte": window_start, "$lte": eval_time}
                },
                {"pid": 1, "examID": 1, "reportID": 1, "collectTime": 1}
            ).max_time_ms(15000).limit(5000))

            for doc in exam_docs:
                pid = doc.get("pid")
                if pid not in exam_by_pid:
                    exam_by_pid[pid] = []
                exam_by_pid[pid].append({
                    "examID": doc.get("examID"),
                    "reportID": doc.get("reportID"),
                    "collectTime": doc.get("collectTime")
                })

            logger.debug("VI_ICU_EXAM chunk %d-%d: %d docs", i, i + CHUNK_SIZE, len(exam_docs))

        except Exception as e:
            logger.warning("VI_ICU_EXAM batch query failed for chunk %d-%d: %s",
                         i, i + CHUNK_SIZE, e)
            continue  # 继续处理下一块

    if not exam_by_pid:
        logger.info("batch_fetch_lab: no exam docs found")
        return result

    # Step 2: 收集所有 examID 和 reportID
    all_exam_ids = []
    all_report_ids = []
    exam_time_map = {}  # str(id) → collectTime
    exam_pid_map = {}   # str(id) → his_pid

    for pid, exams in exam_by_pid.items():
        for exam in exams:
            eid = exam.get("examID")
            rid = exam.get("reportID")
            ct = exam.get("collectTime")

            if eid:
                eid_str = str(eid)
                all_exam_ids.append(eid)
                exam_time_map[eid_str] = ct
                exam_pid_map[eid_str] = pid

            if rid:
                rid_str = str(rid)
                all_report_ids.append(rid)
                exam_time_map[rid_str] = ct
                exam_pid_map[rid_str] = pid

    if not all_exam_ids and not all_report_ids:
        logger.info("batch_fetch_lab: no exam/report IDs found")
        return result

    logger.info("batch_fetch_lab: %d exam IDs, %d report IDs",
                len(all_exam_ids), len(all_report_ids))

    # Step 3: 批量查询 VI_ICU_EXAM_ITEM
    target_item_codes = list(LAB_MAP.keys())

    # 分块查询 examID
    for i in range(0, len(all_exam_ids), CHUNK_SIZE):
        chunk = all_exam_ids[i:i + CHUNK_SIZE]

        try:
            items = list(dc.VI_ICU_EXAM_ITEM.find(
                {
                    "examID": {"$in": chunk},
                    "itemCode": {"$in": target_item_codes}
                },
                {"examID": 1, "itemCode": 1, "itemValue": 1, "result": 1,
                 "unit": 1, "itemName": 1}
            ).max_time_ms(15000).limit(10000))

            # 处理查询结果
            _process_exam_items(items, exam_time_map, exam_pid_map,
                              LAB_MAP, result, window_start, eval_time)

            logger.debug("VI_ICU_EXAM_ITEM exam chunk %d-%d: %d items",
                        i, i + CHUNK_SIZE, len(items))

        except Exception as e:
            logger.warning("VI_ICU_EXAM_ITEM batch query failed for exam chunk %d-%d: %s",
                         i, i + CHUNK_SIZE, e)
            continue

    # 分块查询 reportID（如果存在）
    for i in range(0, len(all_report_ids), CHUNK_SIZE):
        chunk = all_report_ids[i:i + CHUNK_SIZE]

        try:
            items = list(dc.VI_ICU_EXAM_ITEM.find(
                {
                    "reportID": {"$in": chunk},
                    "itemCode": {"$in": target_item_codes}
                },
                {"reportID": 1, "itemCode": 1, "itemValue": 1, "result": 1,
                 "unit": 1, "itemName": 1}
            ).max_time_ms(15000).limit(10000))

            _process_exam_items(items, exam_time_map, exam_pid_map,
                              LAB_MAP, result, window_start, eval_time)

            logger.debug("VI_ICU_EXAM_ITEM report chunk %d-%d: %d items",
                        i, i + CHUNK_SIZE, len(items))

        except Exception as e:
            logger.warning("VI_ICU_EXAM_ITEM batch query failed for report chunk %d-%d: %s",
                         i, i + CHUNK_SIZE, e)
            continue

    # 统计结果
    total_obs = sum(len(obs) for obs in result.values())
    patients_with_data = sum(1 for obs in result.values() if obs)
    logger.info("batch_fetch_lab complete: %d patients with data, %d total observations",
                patients_with_data, total_obs)

    return result


def _process_exam_items(
    items: List[dict],
    exam_time_map: Dict[str, datetime],
    exam_pid_map: Dict[str, str],
    lab_map: Dict[str, str],
    result: Dict[str, List[dict]],
    window_start: datetime,
    eval_time: datetime,
) -> None:
    """
    处理检验项目结果，去重并分配给患者。

    Args:
        items: VI_ICU_EXAM_ITEM 查询结果
        exam_time_map: exam_id_str → collectTime
        exam_pid_map: exam_id_str → his_pid
        lab_map: itemCode → std_code 映射
        result: 输出结果字典 {his_pid: [observations]}
        window_start: 时间窗口开始
        eval_time: 评估时间
    """
    seen = {}  # (pid, exam_id, item_code) → True

    for doc in items:
        # 提取检验值
        raw_val = _safe_float(doc.get("itemValue"))
        if raw_val is None:
            raw_val = _safe_float(doc.get("result"))
        if raw_val is None:
            continue

        # 获取关联 ID
        exam_id = doc.get("examID") or doc.get("reportID")
        if not exam_id:
            continue

        exam_id_str = str(exam_id)

        # 获取患者 PID
        pid = exam_pid_map.get(exam_id_str)
        if not pid or pid not in result:
            continue

        # 获取检验时间
        collect_time = exam_time_map.get(exam_id_str)
        if not collect_time or not isinstance(collect_time, datetime):
            continue

        # 时间窗口校验
        collect_time_aware = _aware(collect_time)
        if collect_time_aware < window_start or collect_time_aware > eval_time:
            continue

        # 去重
        item_code = doc.get("itemCode")
        dedup_key = (pid, exam_id_str, item_code)
        if dedup_key in seen:
            continue
        seen[dedup_key] = True

        # 标准化代码
        std_code = lab_map.get(item_code)
        if not std_code:
            continue

        # 添加观测
        result[pid].append({
            "code": std_code,
            "value_number": raw_val,
            "unit": (doc.get("unit") or "").strip(),
            "observed_at": collect_time_aware,
            "item_name": doc.get("itemName", ""),
            "source": "VI_ICU_EXAM_ITEM",
        })


def batch_fetch_lab_observations_with_status(
    dc,
    his_pids: List[str],
    eval_time: datetime,
    lookback_hours: int = 24,
) -> Tuple[Dict[str, List[dict]], Dict[str, str], List[str]]:
    """
    带状态返回的批量查询版本。

    Returns:
        (observations_by_pid, status_by_pid, failed_pids)
        - observations_by_pid: {his_pid: [observations]}
        - status_by_pid: {his_pid: status}
          status 取值: "success" | "no_data" | "timeout" | "query_error"
        - failed_pids: 查询失败的患者列表
    """
    window_start = eval_time - timedelta(hours=lookback_hours)
    result = {pid: [] for pid in his_pids}
    status = {pid: "success" for pid in his_pids}
    failed_pids = []

    if not his_pids or dc is None:
        if dc is None:
            status = {pid: "query_error" for pid in his_pids}
            failed_pids = list(his_pids)
        return result, status, failed_pids

    logger.info("batch_fetch_lab_with_status: %d patients", len(his_pids))

    # Step 1: 分块查询 VI_ICU_EXAM
    exam_by_pid = {}  # his_pid → [{examID, reportID, collectTime}]

    for i in range(0, len(his_pids), CHUNK_SIZE):
        chunk = his_pids[i:i + CHUNK_SIZE]

        try:
            exam_docs = list(dc.VI_ICU_EXAM.find(
                {
                    "pid": {"$in": chunk},
                    "collectTime": {"$gte": window_start, "$lte": eval_time}
                },
                {"pid": 1, "examID": 1, "reportID": 1, "collectTime": 1}
            ).max_time_ms(15000).limit(5000))

            for doc in exam_docs:
                pid = doc.get("pid")
                if pid not in exam_by_pid:
                    exam_by_pid[pid] = []
                exam_by_pid[pid].append({
                    "examID": doc.get("examID"),
                    "reportID": doc.get("reportID"),
                    "collectTime": doc.get("collectTime")
                })

        except Exception as e:
            error_msg = str(e)
            if "MaxTimeMSExpired" in error_msg:
                chunk_status = "timeout"
            else:
                chunk_status = "query_error"

            for pid in chunk:
                status[pid] = chunk_status
                failed_pids.append(pid)

            logger.warning("VI_ICU_EXAM batch query failed for chunk %d-%d: %s",
                         i, i + CHUNK_SIZE, e)
            continue

    # 标记无检验数据的患者
    for pid in his_pids:
        if pid not in exam_by_pid and status[pid] == "success":
            status[pid] = "no_data"

    if not exam_by_pid:
        return result, status, failed_pids

    # Step 2: 收集所有 examID 和 reportID
    all_exam_ids = []
    all_report_ids = []
    exam_time_map = {}  # str(id) → collectTime
    exam_pid_map = {}   # str(id) → his_pid

    for pid, exams in exam_by_pid.items():
        for exam in exams:
            eid = exam.get("examID")
            rid = exam.get("reportID")
            ct = exam.get("collectTime")

            if eid:
                eid_str = str(eid)
                all_exam_ids.append(eid)
                exam_time_map[eid_str] = ct
                exam_pid_map[eid_str] = pid

            if rid:
                rid_str = str(rid)
                all_report_ids.append(rid)
                exam_time_map[rid_str] = ct
                exam_pid_map[rid_str] = pid

    if not all_exam_ids and not all_report_ids:
        return result, status, failed_pids

    # Step 3: 批量查询 VI_ICU_EXAM_ITEM
    target_item_codes = list(LAB_MAP.keys())

    # 分块查询 examID
    for i in range(0, len(all_exam_ids), CHUNK_SIZE):
        chunk = all_exam_ids[i:i + CHUNK_SIZE]

        try:
            items = list(dc.VI_ICU_EXAM_ITEM.find(
                {
                    "examID": {"$in": chunk},
                    "itemCode": {"$in": target_item_codes}
                },
                {"examID": 1, "itemCode": 1, "itemValue": 1, "result": 1,
                 "unit": 1, "itemName": 1}
            ).max_time_ms(15000).limit(10000))

            _process_exam_items(items, exam_time_map, exam_pid_map,
                              LAB_MAP, result, window_start, eval_time)

        except Exception as e:
            error_msg = str(e)
            # 找出受影响的患者
            affected_pids = set()
            for eid in chunk:
                pid = exam_pid_map.get(str(eid))
                if pid:
                    affected_pids.add(pid)

            if "MaxTimeMSExpired" in error_msg:
                chunk_status = "timeout"
            else:
                chunk_status = "query_error"

            for pid in affected_pids:
                if status[pid] == "success":  # 只覆盖成功状态
                    status[pid] = chunk_status
                    failed_pids.append(pid)

            logger.warning("VI_ICU_EXAM_ITEM batch query failed for exam chunk %d-%d: %s",
                         i, i + CHUNK_SIZE, e)
            continue

    # 分块查询 reportID
    for i in range(0, len(all_report_ids), CHUNK_SIZE):
        chunk = all_report_ids[i:i + CHUNK_SIZE]

        try:
            items = list(dc.VI_ICU_EXAM_ITEM.find(
                {
                    "reportID": {"$in": chunk},
                    "itemCode": {"$in": target_item_codes}
                },
                {"reportID": 1, "itemCode": 1, "itemValue": 1, "result": 1,
                 "unit": 1, "itemName": 1}
            ).max_time_ms(15000).limit(10000))

            _process_exam_items(items, exam_time_map, exam_pid_map,
                              LAB_MAP, result, window_start, eval_time)

        except Exception as e:
            error_msg = str(e)
            affected_pids = set()
            for rid in chunk:
                pid = exam_pid_map.get(str(rid))
                if pid:
                    affected_pids.add(pid)

            if "MaxTimeMSExpired" in error_msg:
                chunk_status = "timeout"
            else:
                chunk_status = "query_error"

            for pid in affected_pids:
                if status[pid] == "success":
                    status[pid] = chunk_status
                    failed_pids.append(pid)

            logger.warning("VI_ICU_EXAM_ITEM batch query failed for report chunk %d-%d: %s",
                         i, i + CHUNK_SIZE, e)
            continue

    # 统计
    total_obs = sum(len(obs) for obs in result.values())
    patients_with_data = sum(1 for obs in result.values() if obs)
    logger.info("batch_fetch_lab_with_status complete: %d/%d patients with data, %d observations",
                patients_with_data, len(his_pids), total_obs)

    return result, status, failed_pids
