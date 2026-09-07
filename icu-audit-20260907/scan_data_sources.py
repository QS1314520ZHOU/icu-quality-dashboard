#!/usr/bin/env python3
"""
数据源扫描脚本 — 检查SmartCare和DataCenter中的候选数据源
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

def scan_smartcare_collections():
    """扫描SmartCare数据库中的集合"""
    print("=" * 60)
    print("SmartCare 数据库集合扫描")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 获取所有集合
        collections = db.list_collection_names()
        print(f"找到 {len(collections)} 个集合")

        # 候选集合列表
        candidate_collections = [
            "patient", "configDrug", "drugExe", "configParam", "bedside",
            "bGATemp", "bGATemp1", "drugList", "drugActionList",
            "diseaseDiagnosis", "infectionShockV2", "bedRecord", "configBed",
            "account", "score", "temperatureData", "tubeExe", "criticalValue",
            "department"
        ]

        found_collections = []
        missing_collections = []

        for coll_name in candidate_collections:
            if coll_name in collections:
                count = db[coll_name].count_documents({}, limit=1)
                found_collections.append((coll_name, count > 0))
                status = "✓ 存在" if count > 0 else "✓ 存在 (空)"
                print(f"  {status}: {coll_name}")
            else:
                missing_collections.append(coll_name)
                print(f"  ✗ 不存在: {coll_name}")

        return found_collections, missing_collections

    except Exception as e:
        print(f"连接失败: {e}")
        return [], []

def scan_datacenter_collections():
    """扫描DataCenter数据库中的集合"""
    print("\n" + "=" * 60)
    print("DataCenter 数据库集合扫描")
    print("=" * 60)

    try:
        client = get_client("DataCenter")
        db = client["DataCenter"]

        # 获取所有集合
        collections = db.list_collection_names()
        print(f"找到 {len(collections)} 个集合")

        # 候选集合列表
        candidate_collections = [
            "VI_ICU_ZYBR", "VI_ICU_ZYYZ", "VI_ICU_EXAM", "VI_ICU_EXAM_ITEM"
        ]

        found_collections = []
        missing_collections = []

        for coll_name in candidate_collections:
            if coll_name in collections:
                count = db[coll_name].count_documents({}, limit=1)
                found_collections.append((coll_name, count > 0))
                status = "✓ 存在" if count > 0 else "✓ 存在 (空)"
                print(f"  {status}: {coll_name}")
            else:
                missing_collections.append(coll_name)
                print(f"  ✗ 不存在: {coll_name}")

        return found_collections, missing_collections

    except Exception as e:
        print(f"连接失败: {e}")
        return [], []

def scan_patient_fields():
    """扫描patient集合的字段结构"""
    print("\n" + "=" * 60)
    print("patient 集合字段结构")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 获取一条样本
        sample = db.patient.find_one()
        if not sample:
            print("  无数据")
            return

        print("字段列表:")
        for key in sample.keys():
            if key == "_id":
                print(f"  {key}: ObjectId")
            else:
                value_type = type(sample[key]).__name__
                print(f"  {key}: {value_type}")

        # 检查关键字段
        key_fields = ["mrn", "hisPid", "patientId", "name", "deptCode", "status",
                      "icuAdmissionTime", "icuDischargeTime"]
        print("\n关键字段检查:")
        for field in key_fields:
            if field in sample:
                print(f"  ✓ {field} 存在")
            else:
                print(f"  ✗ {field} 不存在")

    except Exception as e:
        print(f"扫描失败: {e}")

def scan_drugexe_fields():
    """扫描drugExe集合的字段结构"""
    print("\n" + "=" * 60)
    print("drugExe 集合字段结构")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 获取一条样本
        sample = db.drugExe.find_one()
        if not sample:
            print("  无数据")
            return

        print("字段列表:")
        for key in sample.keys():
            if key == "_id":
                print(f"  {key}: ObjectId")
            else:
                value_type = type(sample[key]).__name__
                print(f"  {key}: {value_type}")

        # 检查关键字段
        key_fields = ["pid", "startTime", "drugList", "drugActionList"]
        print("\n关键字段检查:")
        for field in key_fields:
            if field in sample:
                print(f"  ✓ {field} 存在")
            else:
                print(f"  ✗ {field} 不存在")

        # 检查drugList结构
        if "drugList" in sample and sample["drugList"]:
            print("\ndrugList 结构示例:")
            drug_item = sample["drugList"][0]
            for key in drug_item.keys():
                value_type = type(drug_item[key]).__name__
                print(f"  {key}: {value_type}")

    except Exception as e:
        print(f"扫描失败: {e}")

def scan_bedsides_fields():
    """扫描bedside集合的字段结构"""
    print("\n" + "=" * 60)
    print("bedside 集合字段结构")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 获取一条样本
        sample = db.bedside.find_one()
        if not sample:
            print("  无数据")
            return

        print("字段列表:")
        for key in sample.keys():
            if key == "_id":
                print(f"  {key}: ObjectId")
            else:
                value_type = type(sample[key]).__name__
                print(f"  {key}: {value_type}")

        # 检查关键字段
        key_fields = ["pid", "code", "valid", "time", "strVal", "fVal"]
        print("\n关键字段检查:")
        for field in key_fields:
            if field in sample:
                print(f"  ✓ {field} 存在")
            else:
                print(f"  ✗ {field} 不存在")

    except Exception as e:
        print(f"扫描失败: {e}")

def scan_bgatemp_fields():
    """扫描bGATemp集合的字段结构"""
    print("\n" + "=" * 60)
    print("bGATemp 集合字段结构")
    print("=" * 60)

    try:
        client = get_client("SmartCare")
        db = client["SmartCare"]

        # 获取一条样本
        sample = db.bGATemp.find_one()
        if not sample:
            print("  无数据")
            return

        print("字段列表:")
        for key in sample.keys():
            if key == "_id":
                print(f"  {key}: ObjectId")
            else:
                value_type = type(sample[key]).__name__
                print(f"  {key}: {value_type}")

        # 检查关键字段
        key_fields = ["pid", "mrn", "deptCode", "eventExe", "bedsides"]
        print("\n关键字段检查:")
        for field in key_fields:
            if field in sample:
                print(f"  ✓ {field} 存在")
            else:
                print(f"  ✗ {field} 不存在")

        # 检查eventExe结构
        if "eventExe" in sample:
            print("\neventExe 结构示例:")
            event_exe = sample["eventExe"]
            for key in event_exe.keys():
                value_type = type(event_exe[key]).__name__
                print(f"  {key}: {value_type}")

        # 检查bedsides结构
        if "bedsides" in sample and sample["bedsides"]:
            print("\nbedsides 结构示例:")
            bedside_item = sample["bedsides"][0]
            for key in bedside_item.keys():
                value_type = type(bedside_item[key]).__name__
                print(f"  {key}: {value_type}")

    except Exception as e:
        print(f"扫描失败: {e}")

def scan_vi_zyyz_fields():
    """扫描VI_ICU_ZYYZ集合的字段结构"""
    print("\n" + "=" * 60)
    print("VI_ICU_ZYYZ 集合字段结构")
    print("=" * 60)

    try:
        client = get_client("DataCenter")
        db = client["DataCenter"]

        # 获取一条样本
        sample = db.VI_ICU_ZYYZ.find_one()
        if not sample:
            print("  无数据")
            return

        print("字段列表:")
        for key in sample.keys():
            if key == "_id":
                print(f"  {key}: ObjectId")
            else:
                value_type = type(sample[key]).__name__
                print(f"  {key}: {value_type}")

        # 检查关键字段
        key_fields = ["pid", "mrn", "orderName", "orderTime", "status"]
        print("\n关键字段检查:")
        for field in key_fields:
            if field in sample:
                print(f"  ✓ {field} 存在")
            else:
                print(f"  ✗ {field} 不存在")

    except Exception as e:
        print(f"扫描失败: {e}")

def main():
    """主函数"""
    print("ICU 质控仪表板数据源扫描")
    print("扫描时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()

    # 扫描SmartCare
    sc_found, sc_missing = scan_smartcare_collections()

    # 扫描DataCenter
    dc_found, dc_missing = scan_datacenter_collections()

    # 扫描字段结构
    scan_patient_fields()
    scan_drugexe_fields()
    scan_bedsides_fields()
    scan_bgatemp_fields()
    scan_vi_zyyz_fields()

    # 总结
    print("\n" + "=" * 60)
    print("扫描总结")
    print("=" * 60)
    print(f"SmartCare: 找到 {len(sc_found)} 个候选集合, 缺少 {len(sc_missing)} 个")
    print(f"DataCenter: 找到 {len(dc_found)} 个候选集合, 缺少 {len(dc_missing)} 个")

    if sc_missing:
        print(f"\nSmartCare 缺少的集合: {', '.join(sc_missing)}")
    if dc_missing:
        print(f"\nDataCenter 缺少的集合: {', '.join(dc_missing)}")

if __name__ == "__main__":
    main()