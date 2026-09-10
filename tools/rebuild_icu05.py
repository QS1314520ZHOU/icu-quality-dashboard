#!/usr/bin/env python3
"""
ICU-05 历史数据重建脚本 (简化版)
==================================
使用 get_bundle_data_v2 重建指定月份的ICU-05预聚合数据。

用法:
    python tools/rebuild_icu05.py --start 2026-01 --end 2026-09
    python tools/rebuild_icu05.py --start 2026-06 --end 2026-06 --dry-run

输出:
    - 逐月漏斗统计
    - 写入 icu_dept_summary 集合
"""
import sys
import os
import argparse
import logging
from datetime import datetime

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


def get_dept_codes():
    """获取所有科室代码"""
    from db import get_client, BED_DB_NAMES
    codes = []
    for db_name in BED_DB_NAMES:
        try:
            db = get_client(db_name)[db_name]
            docs = list(db.department.find({}, {"code": 1, "_id": 0}))
            if docs:
                codes = [d["code"] for d in docs]
                break
        except Exception:
            continue
    return codes if codes else ["JJL000282", "JJL000283", "0801"]


def inject_vaso_labels():
    """注入升压药白名单"""
    from scoring.bundle_engine import set_vaso_wide_labels
    from db import get_client

    try:
        sc = get_client("SmartCare")["SmartCare"]
        vaso_drugs = list(sc.configDrug.find(
            {"classification": {"$regex": "血管活性", "$options": "i"}},
            {"name": 1, "_id": 0}
        ))
        labels = {d["name"].strip() for d in vaso_drugs if d.get("name")}
        if labels:
            set_vaso_wide_labels(labels)
            logger.info("升压药白名单注入: %d 条", len(labels))
            return True
        else:
            logger.warning("升压药白名单为空")
            return False
    except Exception as e:
        logger.error("升压药白名单注入失败: %s", e)
        return False


def rebuild_month(dept_codes: list, period: str, dry_run: bool = False) -> dict:
    """重建单个月份的ICU-05预聚合数据"""
    import calendar
    from db import get_bundle_data_v2
    from config.candidate_rules import CANDIDATE_RULE_VERSION, CANDIDATE_ENGINE_MODE

    year, month = map(int, period.split("-"))
    start_date = f"{year}-{month:02d}-01"
    end_day = calendar.monthrange(year, month)[1]
    end_date = f"{year}-{month:02d}-{end_day:02d}"

    result = {
        "period": period,
        "dry_run": dry_run,
        "started_at": datetime.now().isoformat(),
    }

    # 获取bundle数据
    bundle_data = get_bundle_data_v2(dept_codes, start_date, end_date)
    den_patients = bundle_data.get("den_patients", [])
    h1_patients = bundle_data.get("h1_patients", [])
    h3_patients = bundle_data.get("h3_patients", [])
    h6_patients = bundle_data.get("h6_patients", [])

    # 统计
    official_den = len(den_patients)
    num_1h = len(h1_patients)
    num_3h = len(h3_patients)
    num_6h = len(h6_patients)

    # 候选引擎统计
    # active 模式: candidate_shadow 未设置，需从 den_patients 统计
    candidate_shadow = bundle_data.get("candidate_shadow")
    if candidate_shadow is None:
        # 从 den_patients 手动统计
        candidate_count = sum(1 for p in den_patients
                              if p.get("candidate_status", "not_candidate") != "not_candidate")
        high_prob = sum(1 for p in den_patients if p.get("candidate_status") == "high_probability")
        probable = sum(1 for p in den_patients if p.get("candidate_status") == "probable")
        pending = sum(1 for p in den_patients if p.get("candidate_status") == "pending_review")
        candidate_shadow = {
            "raw_candidate_count": candidate_count,
            "high_probability_count": high_prob,
            "probable_count": probable,
            "pending_review_count": pending,
            "not_candidate_count": len(den_patients) - candidate_count,
        }
    candidate_den = candidate_shadow.get("raw_candidate_count", 0)

    result.update({
        "official_den": official_den,
        "num_1h": num_1h,
        "num_3h": num_3h,
        "num_6h": num_6h,
        "candidate_den": candidate_den,
        "candidate_shadow": candidate_shadow,
    })

    logger.info("[%s] 旧口径分母=%d, 分子(1h/3h/6h)=%d/%d/%d",
                period, official_den, num_1h, num_3h, num_6h)
    logger.info("[%s] 候选分母=%d (high=%d, probable=%d, pending=%d)",
                period, candidate_den,
                candidate_shadow.get("high_probability_count", 0),
                candidate_shadow.get("probable_count", 0),
                candidate_shadow.get("pending_review_count", 0))

    # 写入预聚合
    if not dry_run and official_den > 0:
        try:
            from db import get_datacenter_db
            db = get_datacenter_db()
            summary_doc = {
                "indicator_id": "ICU-05",
                "period": period,
                "dept_codes": dept_codes,
                "denominator": official_den,
                "numerator": num_1h,
                "num_3h": num_3h,
                "num_6h": num_6h,
                "official_den": official_den,
                "candidate_den": candidate_den,
                "candidate_shadow": candidate_shadow,
                "candidate_engine_mode": CANDIDATE_ENGINE_MODE,
                "candidate_rule_version": CANDIDATE_RULE_VERSION,
                "rebuilt_at": datetime.now().isoformat(),
                "rebuilt_by": "rebuild_icu05.py",
            }
            db.icu_dept_summary.update_one(
                {"indicator_id": "ICU-05", "period": period},
                {"$set": summary_doc},
                upsert=True,
            )
            logger.info("[%s] 预聚合数据已写入", period)
            result["written"] = True
        except Exception as e:
            logger.error("[%s] 写入失败: %s", period, e)
            result["errors"] = [str(e)]
            result["written"] = False
    else:
        if dry_run:
            logger.info("[%s] dry-run模式, 不写入", period)
        result["written"] = False

    result["completed_at"] = datetime.now().isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(description="ICU-05 历史数据重建脚本")
    parser.add_argument("--start", required=True, help="起始月份 (YYYY-MM)")
    parser.add_argument("--end", required=True, help="结束月份 (YYYY-MM)")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写入")
    args = parser.parse_args()

    periods = _periods_between(args.start, args.end)
    dept_codes = get_dept_codes()

    # 注入升压药白名单
    if not inject_vaso_labels():
        logger.error("无法注入升压药白名单，中止")
        return

    logger.info("=" * 60)
    logger.info("ICU-05 历史数据重建")
    logger.info("=" * 60)
    logger.info("月份: %s", periods)
    logger.info("科室: %s (%d个)", dept_codes[:3], len(dept_codes))
    logger.info("模式: %s", "dry-run" if args.dry_run else "实际写入")
    logger.info("=" * 60)

    all_results = []
    for period in periods:
        logger.info("-" * 40)
        logger.info("处理: %s", period)
        result = rebuild_month(dept_codes, period, args.dry_run)
        all_results.append(result)

    # 汇总
    logger.info("=" * 60)
    logger.info("重建完成汇总")
    logger.info("=" * 60)
    total_den = 0
    total_num = 0
    for r in all_results:
        den = r.get("official_den", 0)
        num = r.get("num_1h", 0)
        total_den += den
        total_num += num
        status = "✓" if r.get("written") else ("-" if r.get("dry_run") else "✗")
        logger.info("  %s %s: 分母=%d, 分子=%d", status, r["period"], den, num)
    logger.info("-" * 40)
    logger.info("  合计: 分母=%d, 分子=%d", total_den, total_num)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
