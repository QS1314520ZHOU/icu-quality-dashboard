#!/usr/bin/env python3
"""
ICU-05 历史数据重建脚本
========================
重建指定月份的ICU-05预聚合数据。

用法:
    python tools/rebuild_icu05.py --periods 2026-01 2026-02 ... 2026-09
    python tools/rebuild_icu05.py --start 2026-01 --end 2026-09
    python tools/rebuild_icu05.py --periods 2026-06 --dry-run

功能:
    - 清除指定月份的ICU-05旧预聚合数据
    - 重新计算该月份的分子/分母
    - 写回icu_dept_summary集合
    - 支持--dry-run模式(只计算不写入)
    - 输出详细的重建日志

依赖:
    - MongoDB连接(通过环境变量MONGO_URI或默认localhost:27017)
    - icu-quality-backend模块(PYTHONPATH)
"""
import sys
import os
import argparse
import logging
from datetime import datetime
from typing import Optional

# 添加backend路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'icu-quality-backend'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


def _periods_between(start_period: str, end_period: str) -> list:
    """生成月份列表"""
    sy, sm = start_period.split("-")
    ey, em = end_period.split("-")
    periods = []
    y, m = int(sy), int(sm)
    while (y < int(ey)) or (y == int(ey) and m <= int(em)):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return periods


def rebuild_month(dept_codes: list, period: str, dry_run: bool = False) -> dict:
    """
    重建单个月份的ICU-05预聚合数据。

    Args:
        dept_codes: 科室代码列表
        period: 月份(period), 如 "2026-06"
        dry_run: 是否只计算不写入

    Returns:
        重建结果字典
    """
    from db import (
        get_mongo_db, get_icu_events_by_period,
        get_bundle_data_v2, get_sofa2_for_event, get_candidate_layer_data_for_event,
        get_classic_sofa_for_event, get_drug_dict_classifications,
    )
    from scoring.candidate_engine import extract_candidate, compute_candidate_statistics
    from scoring.bundle_engine import set_vaso_wide_labels
    from config.candidate_rules import CANDIDATE_RULE_VERSION, CANDIDATE_ENGINE_MODE
    from config.indicator_windows import SHOCK_RULE

    db = get_mongo_db()
    result = {
        "period": period,
        "dept_codes": dept_codes,
        "dry_run": dry_run,
        "started_at": datetime.now().isoformat(),
        "events_processed": 0,
        "patients_den": 0,
        "patients_num": 0,
        "candidate_stats": {},
        "errors": [],
    }

    # Step 1: 注入升压药白名单
    try:
        classifications = get_drug_dict_classifications()
        vaso_wide_labels = classifications.get("血管活性", set())
        if vaso_wide_labels:
            set_vaso_wide_labels(vaso_wide_labels)
            logger.info("升压药白名单注入: %d 条", len(vaso_wide_labels))
        else:
            logger.warning("升压药白名单为空, ICU-05分母可能恒为0")
    except Exception as e:
        logger.error("升压药白名单注入失败: %s", e)
        result["errors"].append(f"vaso_wide_injection_failed: {e}")
        return result

    # Step 2: 获取ICU事件
    events = get_icu_events_by_period(dept_codes, period)
    logger.info("[%s] 获取ICU事件: %d 条", period, len(events))
    result["events_processed"] = len(events)

    if not events:
        logger.warning("[%s] 无ICU事件, 跳过", period)
        result["completed_at"] = datetime.now().isoformat()
        return result

    # Step 3: 逐事件计算
    all_den_candidates = []
    all_num_candidates = []
    candidate_list = []

    for event in events:
        event_id = event.get("_id")
        pid = event.get("pid")
        mrn = event.get("mrn")
        admission_id = event.get("admission_id")

        try:
            # 获取bundle数据
            bundle_data = get_bundle_data_v2(event_id, period)
            if not bundle_data:
                continue

            # 获取候选引擎数据
            candidate_data = get_candidate_layer_data_for_event(event_id, pid, mrn)

            # K1/K2判断
            k1 = bundle_data.get("k1")
            k2 = bundle_data.get("k2")

            # 候选引擎提取
            sofa2_result = None
            if candidate_data and candidate_data.get("has_sofa2"):
                sofa2_result = get_sofa2_for_event(event_id)

            classic_sofa_result = None
            if candidate_data and candidate_data.get("has_classic_sofa"):
                classic_sofa_result = get_classic_sofa_for_event(event_id)

            candidate = extract_candidate(
                diagnosis_text=bundle_data.get("diagnosis_text"),
                infection_evidence=bundle_data.get("infection_evidence"),
                has_vasopressor_wide=bundle_data.get("has_vasopressor", False),
                has_vasopressor_strict=bundle_data.get("has_vasopressor_strict", False),
                vasopressor_status=bundle_data.get("vasopressor_status"),
                lactate_value=bundle_data.get("lactate_value"),
                map_value=bundle_data.get("map_value"),
                sofa2_result=sofa2_result,
                classic_sofa_result=classic_sofa_result,
                has_fluid_resuscitation=bundle_data.get("has_fluid"),
                s1_s4_signals=bundle_data.get("s1_s4_signals"),
                has_advanced_support=bundle_data.get("has_advanced_support", False),
                source=bundle_data.get("source", "unknown"),
            )

            candidate_status = candidate.get("candidate_status", "not_candidate")

            # 构造患者记录
            exclusion_key = f"{pid}|{admission_id}" if admission_id else pid
            patient_record = {
                "_id": event_id,
                "pid": pid,
                "mrn": mrn,
                "exclusion_key": exclusion_key,
                "v3": {"k1": k1, "k2": k2},
                "candidate_status": candidate_status,
                "candidate_pathways": candidate.get("candidate_pathways", []),
                "clinical_confirmation_status": candidate.get("clinical_confirmation_status", "insufficient"),
                "bundle_1h": bundle_data.get("bundle_1h"),
                "bundle_3h": bundle_data.get("bundle_3h"),
                "bundle_6h": bundle_data.get("bundle_6h"),
            }

            # 分母判定(旧口径: K1 AND K2)
            if k1 is True and k2 is True:
                all_den_candidates.append(patient_record)

            # 候选引擎分母
            if candidate_status != "not_candidate":
                candidate_list.append(patient_record)

            # 分子判定
            bundle_key = f"bundle_1h"  # 默认1h
            bundle = bundle_data.get(bundle_key) or {}
            if bundle.get("finish") is True:
                all_num_candidates.append(patient_record)

        except Exception as e:
            logger.error("[%s] 事件 %s 处理失败: %s", period, event_id, e)
            result["errors"].append(f"event_{event_id}: {e}")

    # Step 4: 去重
    seen_den = set()
    unique_den = []
    for p in all_den_candidates:
        key = p.get("exclusion_key")
        if key and key not in seen_den:
            seen_den.add(key)
            unique_den.append(p)

    seen_num = set()
    unique_num = []
    for p in all_num_candidates:
        key = p.get("exclusion_key")
        if key and key in seen_den and key not in seen_num:
            seen_num.add(key)
            unique_num.append(p)

    # Step 5: 候选统计
    candidate_stats = compute_candidate_statistics(candidate_list)

    result["patients_den"] = len(unique_den)
    result["patients_num"] = len(unique_num)
    result["candidate_stats"] = candidate_stats
    result["official_den"] = len(unique_den)
    result["candidate_den"] = len(candidate_list)

    logger.info("[%s] 结果: 旧口径分母=%d, 候选分母=%d, 分子=%d",
                period, len(unique_den), len(candidate_list), len(unique_num))
    logger.info("[%s] 候选统计: %s", period, candidate_stats)

    # Step 6: 写入预聚合
    if not dry_run:
        try:
            summary_doc = {
                "indicator_id": "ICU-05",
                "period": period,
                "dept_codes": dept_codes,
                "denominator": len(unique_den),
                "numerator": len(unique_num),
                "official_den": len(unique_den),
                "candidate_den": len(candidate_list),
                "candidate_stats": candidate_stats,
                "candidate_engine_mode": CANDIDATE_ENGINE_MODE,
                "candidate_rule_version": CANDIDATE_RULE_VERSION,
                "rebuilt_at": datetime.now().isoformat(),
                "rebuilt_by": "rebuild_icu05.py",
            }
            db.icu_dept_summary.update_one(
                {"indicator_id": "ICU-05", "period": period, "dept_codes": dept_codes},
                {"$set": summary_doc},
                upsert=True,
            )
            logger.info("[%s] 预聚合数据已写入", period)
            result["written"] = True
        except Exception as e:
            logger.error("[%s] 写入失败: %s", period, e)
            result["errors"].append(f"write_failed: {e}")
            result["written"] = False
    else:
        logger.info("[%s] dry-run模式, 不写入", period)
        result["written"] = False

    result["completed_at"] = datetime.now().isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(
        description="ICU-05 历史数据重建脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/rebuild_icu05.py --periods 2026-01 2026-02 2026-03
  python tools/rebuild_icu05.py --start 2026-01 --end 2026-09
  python tools/rebuild_icu05.py --periods 2026-06 --dry-run
        """,
    )
    parser.add_argument("--periods", nargs="+", help="指定月份列表, 如 2026-01 2026-02")
    parser.add_argument("--start", help="起始月份(与--end配合使用)")
    parser.add_argument("--end", help="结束月份(与--start配合使用)")
    parser.add_argument("--dept-codes", nargs="+", default=["ICU"],
                        help="科室代码列表, 默认: ICU")
    parser.add_argument("--dry-run", action="store_true",
                        help="只计算不写入")

    args = parser.parse_args()

    # 确定月份列表
    if args.periods:
        periods = args.periods
    elif args.start and args.end:
        periods = _periods_between(args.start, args.end)
    else:
        parser.error("请指定 --periods 或 --start/--end")
        return

    logger.info("=" * 60)
    logger.info("ICU-05 历史数据重建")
    logger.info("=" * 60)
    logger.info("月份: %s", periods)
    logger.info("科室: %s", args.dept_codes)
    logger.info("模式: %s", "dry-run" if args.dry_run else "实际写入")
    logger.info("=" * 60)

    all_results = []
    for period in periods:
        logger.info("-" * 40)
        logger.info("开始处理: %s", period)
        logger.info("-" * 40)
        result = rebuild_month(args.dept_codes, period, args.dry_run)
        all_results.append(result)

    # 汇总
    logger.info("=" * 60)
    logger.info("重建完成汇总")
    logger.info("=" * 60)
    for r in all_results:
        status = "✓" if not r.get("errors") else "✗"
        logger.info("  %s %s: 分母=%s, 分子=%s, 候选分母=%s",
                    status, r["period"],
                    r.get("patients_den", "?"),
                    r.get("patients_num", "?"),
                    r.get("candidate_den", "?"))
        if r.get("errors"):
            for err in r["errors"]:
                logger.error("    错误: %s", err)

    logger.info("=" * 60)
    if args.dry_run:
        logger.info("注意: dry-run模式, 数据未写入数据库")
    logger.info("完成时间: %s", datetime.now().isoformat())


if __name__ == "__main__":
    main()
