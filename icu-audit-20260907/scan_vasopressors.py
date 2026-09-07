#!/usr/bin/env python3
"""
血管活性药物数据扫描脚本
检查药物字典、给药途径、状态、时间等
只读扫描，不修改任何数据
"""

import os
import sys
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def get_client(db_name):
    """获取MongoDB连接"""
    host = os.getenv("SMARTCARE_DB_HOST", "127.0.0.1")
    port = int(os.getenv("SMARTCARE_DB_PORT", "27017"))
    user = os.getenv("SMARTCARE_DB_USER")
    password = os.getenv("SMARTCARE_DB_PASSWORD")
    auth_db = os.getenv("SMARTCARE_DB_AUTH", "SmartCare")

    if user:
        try:
            client = MongoClient(
                host=host,
                port=port,
                username=user,
                password=password,
                authSource=auth_db,
                serverSelectionTimeoutMS=3000,
            )
            client[db_name].command("ping")
            return client
        except Exception:
            pass

    # 无认证回退
    return MongoClient(
        host=host,
        port=port,
        serverSelectionTimeoutMS=5000,
    )

def scan_vasopressor_drugs():
    """扫描血管活性药物"""
    print("=" * 60)
    print("血管活性药物扫描")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 候选血管活性药物关键词
        vasopressor_keywords = [
            "去甲肾上腺素", "肾上腺素", "多巴胺", "多巴酚丁胺",
            "血管加压素", "苯肾上腺素", "去氧肾上腺素", "米力农",
            "异丙肾上腺素", "特利加压素", "血管紧张素",
            "norepinephrine", "epinephrine", "dopamine", "dobutamine",
            "vasopressin", "phenylephrine", "milrinone", "isoproterenol",
            "terlipressin", "angiotensin"
        ]

        # 扫描drugExe集合
        print("\n1. drugExe 集合中的血管活性药物:")
        drug_exe_count = 0
        vasopressor_count = 0

        # 查找最近30天的数据
        thirty_days_ago = datetime.now() - timedelta(days=30)

        pipeline = [
            {"$match": {"startTime": {"$gte": thirty_days_ago}}},
            {"$unwind": "$drugList"},
            {"$match": {"drugList.name": {"$regex": "|".join(vasopressor_keywords), "$options": "i"}}},
            {"$group": {"_id": "$drugList.name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20}
        ]

        results = list(db.drugExe.aggregate(pipeline))
        if results:
            print(f"  找到 {len(results)} 种血管活性药物:")
            for r in results:
                print(f"    {r['_id']}: {r['count']} 次")
                vasopressor_count += r['count']
        else:
            print("  未找到血管活性药物记录")

        # 扫描configDrug集合
        print("\n2. configDrug 集合中的血管活性药物分类:")
        pipeline = [
            {"$match": {"name": {"$regex": "|".join(vasopressor_keywords), "$options": "i"}}},
            {"$group": {"_id": "$name", "classification": {"$first": "$classification"}}},
            {"$limit": 20}
        ]

        results = list(db.configDrug.aggregate(pipeline))
        if results:
            print(f"  找到 {len(results)} 种分类:")
            for r in results:
                print(f"    {r['_id']}: {r.get('classification', '未分类')}")
        else:
            print("  未找到分类信息")

        return vasopressor_count

    except Exception as e:
        print(f"扫描失败: {e}")
        return 0

def scan_administration_times():
    """扫描给药时间数据"""
    print("\n" + "=" * 60)
    print("给药时间数据扫描")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 查找最近30天的数据
        thirty_days_ago = datetime.now() - timedelta(days=30)

        # 扫描drugExe的时间字段
        print("\n1. drugExe 时间字段:")
        sample = db.drugExe.find_one({"startTime": {"$gte": thirty_days_ago}})
        if sample:
            print(f"  startTime: {type(sample.get('startTime')).__name__}")
            if "drugActionList" in sample and sample["drugActionList"]:
                action = sample["drugActionList"][0]
                print(f"  drugActionList[0]: {list(action.keys())}")
                if "startTime" in action:
                    print(f"    startTime: {type(action['startTime']).__name__}")
                if "endTime" in action:
                    print(f"    endTime: {type(action['endTime']).__name__}")
        else:
            print("  无近期数据")

        # 统计时间字段缺失情况
        print("\n2. 时间字段缺失统计:")
        total = db.drugExe.count_documents({"startTime": {"$gte": thirty_days_ago}})
        missing_start = db.drugExe.count_documents({
            "startTime": {"$gte": thirty_days_ago},
            "$or": [
                {"startTime": None},
                {"startTime": {"$exists": False}}
            ]
        })
        print(f"  总记录: {total}")
        print(f"  startTime缺失: {missing_start}")

        return total

    except Exception as e:
        print(f"扫描失败: {e}")
        return 0

def scan_administration_status():
    """扫描给药状态数据"""
    print("\n" + "=" * 60)
    print("给药状态数据扫描")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 查找最近30天的数据
        thirty_days_ago = datetime.now() - timedelta(days=30)

        # 扫描状态字段
        print("\n1. drugExe 状态字段:")
        pipeline = [
            {"$match": {"startTime": {"$gte": thirty_days_ago}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]

        results = list(db.drugExe.aggregate(pipeline))
        if results:
            print(f"  状态分布:")
            for r in results:
                print(f"    {r['_id']}: {r['count']} 次")
        else:
            print("  无状态数据")

        return len(results)

    except Exception as e:
        print(f"扫描失败: {e}")
        return 0

def main():
    """主函数"""
    print("血管活性药物数据扫描")
    print("扫描时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()

    # 扫描血管活性药物
    vasopressor_count = scan_vasopressor_drugs()

    # 扫描给药时间
    time_count = scan_administration_times()

    # 扫描给药状态
    status_count = scan_administration_status()

    # 总结
    print("\n" + "=" * 60)
    print("扫描总结")
    print("=" * 60)
    print(f"血管活性药物记录: {vasopressor_count} 次")
    print(f"给药时间记录: {time_count} 次")
    print(f"状态类型: {status_count} 种")

if __name__ == "__main__":
    main()