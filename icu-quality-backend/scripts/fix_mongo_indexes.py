"""
MongoDB 索引优化脚本。
修复 VI_ICU_EXAM 和 VI_ICU_EXAM_ITEM 的 MaxTimeMSExpired 问题。

使用方法：
    python scripts/fix_mongo_indexes.py

功能：
    1. 检查现有索引
    2. 创建缺失索引
    3. 验证索引使用
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timezone, timedelta
from db import get_client, BED_DB_NAMES


def get_dc_db():
    """获取 DataCenter 数据库连接"""
    for db_name in BED_DB_NAMES:
        try:
            client = get_client(db_name)
            db = client[db_name]
            # 测试连接
            db.command("ping")
            return db
        except Exception as e:
            continue
    return None


def check_existing_indexes(collection):
    """检查现有索引"""
    print(f"\n{'='*60}")
    print(f"检查集合: {collection.name}")
    print(f"{'='*60}")

    indexes = list(collection.list_indexes())
    if not indexes:
        print("  无索引")
        return []

    print(f"  索引数量: {len(indexes)}")
    for idx in indexes:
        key = idx.get("key", {})
        name = idx.get("name", "unknown")
        unique = idx.get("unique", False)
        print(f"  - {name}: {key}" + (" [UNIQUE]" if unique else ""))

    return indexes


def create_indexes(db):
    """创建缺失的索引"""
    print(f"\n{'='*60}")
    print("创建索引")
    print(f"{'='*60}")

    # VI_ICU_EXAM 索引
    exam_coll = db["VI_ICU_EXAM"]
    print("\n[VI_ICU_EXAM]")

    # 检查是否已存在 {pid: 1, collectTime: -1} 索引
    existing_indexes = list(exam_coll.list_indexes())
    has_pid_collect_index = False
    for idx in existing_indexes:
        key = idx.get("key", {})
        if key == {"pid": 1, "collectTime": -1}:
            has_pid_collect_index = True
            print("  [OK] 索引 {pid: 1, collectTime: -1} 已存在")
            break

    if not has_pid_collect_index:
        try:
            exam_coll.create_index(
                [("pid", 1), ("collectTime", -1)],
                background=True,
                name="pid_collectTime_idx"
            )
            print("  [OK] 创建索引 {pid: 1, collectTime: -1}")
        except Exception as e:
            print(f"  [FAIL] 创建索引失败: {e}")

    # VI_ICU_EXAM_ITEM 索引
    item_coll = db["VI_ICU_EXAM_ITEM"]
    print("\n[VI_ICU_EXAM_ITEM]")

    existing_indexes = list(item_coll.list_indexes())

    # 检查 examID + itemCode 索引
    has_exam_item_index = False
    for idx in existing_indexes:
        key = idx.get("key", {})
        if key == {"examID": 1, "itemCode": 1}:
            has_exam_item_index = True
            print("  [OK] 索引 {examID: 1, itemCode: 1} 已存在")
            break

    if not has_exam_item_index:
        try:
            item_coll.create_index(
                [("examID", 1), ("itemCode", 1)],
                background=True,
                name="examID_itemCode_idx"
            )
            print("  [OK] 创建索引 {examID: 1, itemCode: 1}")
        except Exception as e:
            print(f"  [FAIL] 创建索引失败: {e}")

    # 检查 reportID + itemCode 索引
    has_report_item_index = False
    for idx in existing_indexes:
        key = idx.get("key", {})
        if key == {"reportID": 1, "itemCode": 1}:
            has_report_item_index = True
            print("  [OK] 索引 {reportID: 1, itemCode: 1} 已存在")
            break

    if not has_report_item_index:
        try:
            item_coll.create_index(
                [("reportID", 1), ("itemCode", 1)],
                background=True,
                name="reportID_itemCode_idx"
            )
            print("  [OK] 创建索引 {reportID: 1, itemCode: 1}")
        except Exception as e:
            print(f"  [FAIL] 创建索引失败: {e}")


def verify_index_usage(db, his_pid="1752815"):
    """验证索引使用"""
    print(f"\n{'='*60}")
    print(f"验证索引使用 (患者: {his_pid})")
    print(f"{'='*60}")

    eval_time = datetime.now(timezone.utc)
    window_start = eval_time - timedelta(hours=24)

    # VI_ICU_EXAM explain
    print("\n[VI_ICU_EXAM] explain")
    try:
        plan = db.VI_ICU_EXAM.explain("executionStats").find({
            "pid": his_pid,
            "collectTime": {"$gte": window_start, "$lte": eval_time}
        })

        stats = plan.get("executionStats", {})
        stage = stats.get("executionStage", "unknown")
        total_docs = stats.get("totalDocsExamined", 0)
        total_keys = stats.get("totalKeysExamined", 0)
        n_returned = stats.get("nReturned", 0)
        exec_time = stats.get("executionTimeMillis", 0)

        print(f"  winningPlan: {stage}")
        print(f"  totalDocsExamined: {total_docs}")
        print(f"  totalKeysExamined: {total_keys}")
        print(f"  nReturned: {n_returned}")
        print(f"  executionTimeMillis: {exec_time}")

        if stage == "COLLSCAN":
            print("  [WARN] 警告: 仍在使用 COLLSCAN!")
        else:
            print("  [OK] 使用索引")
    except Exception as e:
        print(f"  [FAIL] explain 失败: {e}")

    # VI_ICU_EXAM_ITEM explain
    print("\n[VI_ICU_EXAM_ITEM] explain")
    try:
        # 先获取一个 examID
        exam_doc = db.VI_ICU_EXAM.find_one({
            "pid": his_pid,
            "collectTime": {"$gte": window_start, "$lte": eval_time}
        })

        if exam_doc:
            exam_id = exam_doc.get("examID")
            if exam_id:
                plan = db.VI_ICU_EXAM_ITEM.explain("executionStats").find({
                    "examID": exam_id,
                    "itemCode": {"$in": ["PLT", "TBIL", "CREA"]}
                })

                stats = plan.get("executionStats", {})
                stage = stats.get("executionStage", "unknown")
                total_docs = stats.get("totalDocsExamined", 0)
                total_keys = stats.get("totalKeysExamined", 0)
                n_returned = stats.get("nReturned", 0)
                exec_time = stats.get("executionTimeMillis", 0)

                print(f"  winningPlan: {stage}")
                print(f"  totalDocsExamined: {total_docs}")
                print(f"  totalKeysExamined: {total_keys}")
                print(f"  nReturned: {n_returned}")
                print(f"  executionTimeMillis: {exec_time}")

                if stage == "COLLSCAN":
                    print("  [WARN] 警告: 仍在使用 COLLSCAN!")
                else:
                    print("  [OK] 使用索引")
            else:
                print("  [WARN] 未找到 examID")
        else:
            print("  [WARN] 未找到检验记录")
    except Exception as e:
        print(f"  [FAIL] explain 失败: {e}")


def test_batch_query_performance(db):
    """测试批量查询性能"""
    print(f"\n{'='*60}")
    print("测试批量查询性能")
    print(f"{'='*60}")

    # 报错患者列表
    his_pids = ["1752815", "1686820", "1703360", "1686271", "1706236", "1706466"]

    eval_time = datetime.now(timezone.utc)
    window_start = eval_time - timedelta(hours=24)

    import time

    # 测试单患者查询（旧方式）
    print("\n[旧方式] 单患者查询")
    start_time = time.time()
    single_query_count = 0

    for pid in his_pids:
        try:
            exam_docs = list(db.VI_ICU_EXAM.find(
                {"pid": pid,
                 "collectTime": {"$gte": window_start, "$lte": eval_time}},
                {"examID": 1, "reportID": 1, "collectTime": 1}
            ).max_time_ms(10000).limit(200))
            single_query_count += 1

            if exam_docs:
                exam_ids = [e.get("examID") for e in exam_docs if e.get("examID")]
                if exam_ids:
                    items = list(db.VI_ICU_EXAM_ITEM.find(
                        {"examID": {"$in": exam_ids},
                         "itemCode": {"$in": ["PLT", "TBIL", "CREA"]}},
                        {"itemValue": 1, "result": 1, "unit": 1}
                    ).max_time_ms(10000).limit(100))
                    single_query_count += 1
        except Exception as e:
            print(f"  患者 {pid} 查询失败: {e}")

    single_time = time.time() - start_time
    print(f"  查询次数: {single_query_count}")
    print(f"  耗时: {single_time:.2f}秒")

    # 测试批量查询（新方式）
    print("\n[新方式] 批量查询")
    start_time = time.time()

    try:
        exam_docs = list(db.VI_ICU_EXAM.find(
            {"pid": {"$in": his_pids},
             "collectTime": {"$gte": window_start, "$lte": eval_time}},
            {"pid": 1, "examID": 1, "reportID": 1, "collectTime": 1}
        ).max_time_ms(15000).limit(5000))

        exam_ids = [e.get("examID") for e in exam_docs if e.get("examID")]

        if exam_ids:
            items = list(db.VI_ICU_EXAM_ITEM.find(
                {"examID": {"$in": exam_ids},
                 "itemCode": {"$in": ["PLT", "TBIL", "CREA"]}},
                {"examID": 1, "itemCode": 1, "itemValue": 1, "result": 1, "unit": 1}
            ).max_time_ms(15000).limit(10000))

        batch_time = time.time() - start_time
        print(f"  查询次数: 2")
        print(f"  耗时: {batch_time:.2f}秒")
        print(f"  性能提升: {single_time/batch_time:.1f}x")

    except Exception as e:
        print(f"  批量查询失败: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("MongoDB 索引优化脚本")
    print("=" * 60)

    # 获取数据库连接
    db = get_dc_db()
    if db is None:
        print("错误: 无法连接到 DataCenter 数据库")
        sys.exit(1)

    print(f"成功连接到数据库: {db.name}")

    # 1. 检查现有索引
    check_existing_indexes(db["VI_ICU_EXAM"])
    check_existing_indexes(db["VI_ICU_EXAM_ITEM"])

    # 2. 创建缺失索引
    create_indexes(db)

    # 3. 验证索引使用
    verify_index_usage(db)

    # 4. 测试批量查询性能
    test_batch_query_performance(db)

    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
