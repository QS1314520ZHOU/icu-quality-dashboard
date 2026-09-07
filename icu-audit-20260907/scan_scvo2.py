#!/usr/bin/env python3
"""
ScvO2 数据扫描脚本
检查中心静脉血氧饱和度数据
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

def scan_scvo2_keywords():
    """扫描ScvO2相关关键词"""
    print("=" * 60)
    print("ScvO2 关键词扫描")
    print("=" * 60)

    # ScvO2相关关键词
    scvo2_keywords = [
        "ScvO2", "ScvO₂", "ScVO2", "central venous oxygen saturation",
        "中心静脉血氧饱和度", "中央静脉血氧饱和度",
        "SO2", "sO2", "SvO2", "静脉血氧饱和度"
    ]

    # 排除关键词（非目标）
    exclude_keywords = [
        "SaO2", "SpO2", "FiO2", "动脉血氧饱和度", "脉搏血氧饱和度",
        "吸入氧浓度", "PaO2"
    ]

    print("\n候选关键词:")
    for kw in scvo2_keywords:
        print(f"  - {kw}")

    print("\n排除关键词:")
    for kw in exclude_keywords:
        print(f"  - {kw}")

    return scvo2_keywords, exclude_keywords

def scan_bedside_for_scvo2():
    """扫描bedside集合中的ScvO2数据"""
    print("\n" + "=" * 60)
    print("bedside 集合 ScvO2 扫描")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 候选code值
        candidate_codes = [
            "param_ScvO2", "param_ScVO2", "param_Scvo2",
            "param_SvO2", "param_SvO2", "param_SO2",
            "param_central_venous_oxygen_saturation",
            "param_中心静脉血氧饱和度"
        ]

        # 查找最近30天的数据
        thirty_days_ago = datetime.now() - timedelta(days=30)

        print("\n1. bedside code 值扫描:")
        for code in candidate_codes:
            count = db.bedside.count_documents({
                "code": code,
                "time": {"$gte": thirty_days_ago}
            })
            if count > 0:
                print(f"  ✓ {code}: {count} 条记录")

                # 获取样本
                sample = db.bedside.find_one({
                    "code": code,
                    "time": {"$gte": thirty_days_ago}
                })
                if sample:
                    print(f"    样本字段: {list(sample.keys())}")
                    if "strVal" in sample:
                        print(f"    strVal: {sample['strVal']}")
                    if "fVal" in sample:
                        print(f"    fVal: {sample['fVal']}")
                    if "valid" in sample:
                        print(f"    valid: {sample['valid']}")
            else:
                print(f"  ✗ {code}: 无记录")

        # 模糊搜索
        print("\n2. 模糊搜索 ScvO2/SvO2/SO2:")
        pipeline = [
            {"$match": {
                "time": {"$gte": thirty_days_ago},
                "code": {"$regex": "ScvO2|SvO2|SO2|scvo2|so2", "$options": "i"}
            }},
            {"$group": {"_id": "$code", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]

        results = list(db.bedside.aggregate(pipeline))
        if results:
            print(f"  找到 {len(results)} 种code:")
            for r in results:
                print(f"    {r['_id']}: {r['count']} 条")
        else:
            print("  未找到匹配记录")

        return len(results)

    except Exception as e:
        print(f"扫描失败: {e}")
        return 0

def scan_exam_for_scvo2():
    """扫描检验集合中的ScvO2数据"""
    print("\n" + "=" * 60)
    print("检验集合 ScvO2 扫描")
    print("=" * 60)

    try:
        # 扫描DataCenter的VI_ICU_EXAM和VI_ICU_EXAM_ITEM
        client = get_client("DataCenter")
        db = client["DataCenter"]

        # 候选检验项目名称
        exam_keywords = [
            "ScvO2", "ScvO₂", "ScVO2", "SvO2", "SO2",
            "中心静脉血氧饱和度", "中央静脉血氧饱和度",
            "静脉血氧饱和度"
        ]

        thirty_days_ago = datetime.now() - timedelta(days=30)

        print("\n1. VI_ICU_EXAM 扫描:")
        for keyword in exam_keywords:
            count = db.VI_ICU_EXAM.count_documents({
                "$or": [
                    {"examName": {"$regex": keyword, "$options": "i"}},
                    {"itemName": {"$regex": keyword, "$options": "i"}}
                ],
                "reportTime": {"$gte": thirty_days_ago}
            })
            if count > 0:
                print(f"  ✓ {keyword}: {count} 条记录")

        print("\n2. VI_ICU_EXAM_ITEM 扫描:")
        for keyword in exam_keywords:
            count = db.VI_ICU_EXAM_ITEM.count_documents({
                "$or": [
                    {"itemName": {"$regex": keyword, "$options": "i"}},
                    {"result": {"$regex": keyword, "$options": "i"}}
                ],
                "reportTime": {"$gte": thirty_days_ago}
            })
            if count > 0:
                print(f"  ✓ {keyword}: {count} 条记录")

        return 0

    except Exception as e:
        print(f"扫描失败: {e}")
        return 0

def scan_bga_for_scvo2():
    """扫描血气分析中的ScvO2数据"""
    print("\n" + "=" * 60)
    print("血气分析 ScvO2 扫描")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 扫描bGATemp和bGATemp1
        for coll_name in ["bGATemp", "bGATemp1"]:
            print(f"\n1. {coll_name} 扫描:")

            # 查找最近30天的数据
            thirty_days_ago = datetime.now() - timedelta(days=30)

            # 扫描bedsides中的code
            pipeline = [
                {"$match": {"eventExe.startTime": {"$gte": thirty_days_ago}}},
                {"$unwind": "$bedsides"},
                {"$match": {
                    "bedsides.code": {"$regex": "ScvO2|SvO2|SO2|scvo2|so2", "$options": "i"}
                }},
                {"$group": {"_id": "$bedsides.code", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]

            results = list(db[coll_name].aggregate(pipeline))
            if results:
                print(f"  找到 {len(results)} 种code:")
                for r in results:
                    print(f"    {r['_id']}: {r['count']} 条")
            else:
                print("  未找到匹配记录")

        return 0

    except Exception as e:
        print(f"扫描失败: {e}")
        return 0

def main():
    """主函数"""
    print("ScvO2 数据扫描")
    print("扫描时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()

    # 扫描关键词
    scvo2_keywords, exclude_keywords = scan_scvo2_keywords()

    # 扫描bedside
    bedside_count = scan_bedside_for_scvo2()

    # 扫描检验
    exam_count = scan_exam_for_scvo2()

    # 扫描血气
    bga_count = scan_bga_for_scvo2()

    # 总结
    print("\n" + "=" * 60)
    print("扫描总结")
    print("=" * 60)
    print(f"bedside 匹配: {bedside_count} 种code")
    print(f"检验匹配: {exam_count}")
    print(f"血气匹配: {bga_count}")

if __name__ == "__main__":
    main()