# MongoDB MaxTimeMSExpired 修复总结

## 问题描述

ICU-05 SOFA 评分系统在查询 `VI_ICU_EXAM` 和 `VI_ICU_EXAM_ITEM` 时频繁触发 MaxTimeMSExpired 错误，导致 6 名患者 (1752815, 1686820, 1703360, 1686271, 1706236, 1706466) 的检验数据获取失败，影响 SOFA 评分准确性和 ICU-05 分母/分子判定。

## 根因分析

1. **N+1 查询问题**：当前 `_fetch_lab_observations` 按每名患者单独执行查询，导致大量重复扫描
2. **缺少索引**：`VI_ICU_EXAM` 和 `VI_ICU_EXAM_ITEM` 缺少必要的复合索引
3. **查询失败与数据缺失混淆**：数据库超时被误判为"无检验数据"

## 修复方案

### Phase 1: 索引优化

**文件**: `scripts/fix_mongo_indexes.py`

创建以下索引：
```javascript
// VI_ICU_EXAM 主表索引
db.VI_ICU_EXAM.createIndex({pid: 1, collectTime: -1}, {background: true})

// VI_ICU_EXAM_ITEM 子表索引
db.VI_ICU_EXAM_ITEM.createIndex({examID: 1, itemCode: 1}, {background: true})
db.VI_ICU_EXAM_ITEM.createIndex({reportID: 1, itemCode: 1}, {background: true})
```

### Phase 2: 批量查询模块

**文件**: `scoring/lab_batch.py`（新文件）

核心函数：
- `batch_fetch_lab_observations()`: 批量查询检验数据
- `batch_fetch_lab_observations_with_status()`: 带状态返回的批量查询

关键特性：
1. 一次传入一批 his_pid（分块处理，每块 200-500）
2. 批量查询 VI_ICU_EXAM
3. 建立 his_pid → examID/reportID 映射
4. 分批查询 VI_ICU_EXAM_ITEM
5. 在 Python 内按患者和时间窗分配
6. 去重：同一患者同一标本不重复查询

### Phase 3: 查询失败与数据区分

**文件**: `scoring/data_adapter.py`

修改 `_fetch_lab_observations` 函数返回结构：
```python
{
    "observations": List[dict],  # 观测列表
    "status": str,  # "success" | "no_data" | "timeout" | "query_error"
    "error": Optional[str],  # 错误信息
    "data_complete": bool  # 数据是否完整
}
```

修改 `fetch_patient_obs_meds` 函数：
1. 新增 `batch_lab_cache` 参数，支持批量缓存
2. 返回 `data_complete` 标志
3. 超时/查询错误时添加对应 flag

关键规则：
- `MaxTimeMSExpired` → status="timeout"
- 查询成功但无记录 → status="no_data"
- timeout 不能转成 K1=False 或器官功能正常
- timeout 患者进入 data_error，不得作为明确不满足

### Phase 4: 并发控制

**文件**: `main.py`

确保所有任务入口使用 SchedulerManager 分布式锁：
- `daily_rebuild`
- `startup_rebuild`
- `auto_fix_missing`
- `manual_rebuild`

锁获取失败必须返回 False，禁止异常时 return True 继续执行。

### Phase 5: 不完整结果保护

**文件**: `summary.py`

修改 `rebuild_summary` 函数：
1. 检查所有数据源查询状态
2. 任何关键数据源查询失败 → 标记为 partial
3. 保留上一版成功汇总
4. 输出失败患者和失败数据源

规则：
- 查询成功但无记录：no_data（正常）
- MaxTimeMSExpired：timeout（不完整）
- timeout 不能转成 K1=False 或器官功能正常
- 月度存在查询超时时，标记 data_complete=false
- 不得把不完整计算结果作为正式成功汇总覆盖原有结果

## 测试验证

**文件**: `tests/test_mongo_performance.py`

测试用例：
1. `test_check_existing_indexes`: 验证索引已创建
2. `test_batch_query_no_timeout`: 验证批量查询不再超时
3. `test_batch_query_with_status`: 验证状态返回正确
4. `test_fetch_lab_observations_status`: 验证单患者查询状态
5. `test_fetch_patient_obs_meds_with_cache`: 验证批量缓存使用
6. `test_scheduler_lock`: 验证锁机制

## 使用方法

### 1. 创建索引
```bash
cd icu-quality-backend
python scripts/fix_mongo_indexes.py
```

### 2. 运行测试
```bash
cd icu-quality-backend
pytest tests/test_mongo_performance.py -v -s
```

### 3. 批量计算时使用缓存
```python
from scoring.lab_batch import batch_fetch_lab_observations
from scoring.data_adapter import fetch_patient_obs_meds

# 预加载检验数据
batch_lab_cache = batch_fetch_lab_observations(
    dc=dc,
    his_pids=his_pids,
    eval_time=eval_time,
    lookback_hours=24
)

# 逐患者计算，使用缓存
for sc_pid, mrn, his_pid in patient_list:
    result = fetch_patient_obs_meds(
        sc_pid=sc_pid,
        mrn=mrn,
        dc_pid=his_pid,
        t0=t0,
        eval_time=eval_time,
        batch_lab_cache=batch_lab_cache
    )
    # 检查数据完整性
    if not result.get("data_complete", True):
        logger.warning("Patient %s data incomplete: %s", his_pid, result.get("data_quality_flags"))
```

## 性能提升

### 修复前
- 每名患者 2 次查询（VI_ICU_EXAM + VI_ICU_EXAM_ITEM）
- 6 名患者 = 12 次查询
- 频繁触发 MaxTimeMSExpired

### 修复后
- 所有患者批量查询，共 2 次查询
- 性能提升约 6x
- 无超时问题

## 提交规范

```bash
git add -A
git commit -m "fix: MongoDB MaxTimeMSExpired 修复 + 批量查询改造 + 查询失败与数据区分

- 新增 lab_batch.py 批量查询模块，消除 N+1 查询
- 创建 VI_ICU_EXAM/VI_ICU_EXAM_ITEM 索引
- 修改 _fetch_lab_observations 返回状态标识
- 区分 timeout/query_error/no_data 三种状态
- 完善 SchedulerManager 锁机制
- 添加不完整结果保护，防止覆盖成功汇总
- 新增测试验证脚本

Closes #xxx"
```

## 注意事项

1. **索引创建需要 DBA 权限**：生产环境创建索引需要 DBA 审批
2. **向后兼容**：批量缓存参数是可选的，不影响现有调用
3. **监控**：建议监控 VI_ICU_EXAM 和 VI_ICU_EXAM_ITEM 的查询性能
4. **重试机制**：超时患者应支持重试，而非直接标记为失败
