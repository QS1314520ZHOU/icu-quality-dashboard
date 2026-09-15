# Data Complete 修复总结

## 修复概述
本次修复完成了 ICU-05 SOFA 评分数据完整性的完整链路传递，确保查询失败（timeout/query_error）与临床数据缺失（no_data）被正确区分，并通过所有层传递到最终汇总。

## 修改的文件

### 1. `scoring/lab_batch.py`
**核心变更**：
- `batch_fetch_lab_observations()` 返回格式从 `{pid: [observations]}` 改为 `{pid: {"observations": [...], "status": str, "error": str|None, "data_complete": bool}}`
- 添加 `seen` 参数支持跨批次去重
- 添加 limit 截断检测（5000/10000）
- `_process_exam_items()` 更新为支持新格式和外部 seen 集合
- `batch_fetch_lab_observations_with_status()` 同步更新

**状态值**：
- `"success"`: 查询成功
- `"no_data"`: 无检验数据（临床正常）
- `"timeout"`: MaxTimeMSExpired 超时
- `"query_error"`: 其他查询错误

### 2. `scoring/data_adapter.py`
**核心变更**：
- `_fetch_lab_observations()` 返回 `data_complete` 字段
- `fetch_patient_obs_meds()` 支持 `batch_lab_cache` 参数
- `fetch_meta` 包含 `lab_status`, `lab_error`, `lab_data_complete`, `lab_source`
- `data_complete` 计算逻辑：基于 lab_status 和 flags

### 3. `scoring/sofa_bridge.py`
**核心变更**：
- `compute_sofa_scores()` 支持 `batch_lab_cache` 参数
- 返回值包含 `data_complete` 字段
- 从 `fetch_patient_obs_meds()` 透传 `data_complete`

### 4. `db.py`
**核心变更**：
- `get_bundle_data_v2()` 添加阶段 4：批量预加载检验数据
- 创建 `global_seen` 集合用于跨批次去重
- `judge_bundle_v3_for_patient()` 支持 `batch_lab_cache` 参数
- 传递 `batch_lab_cache` 到 `compute_sofa_scores()`

### 5. `summary.py`
**核心变更**：
- `_compute_icu05()` 添加数据完整性检查
- 跟踪 `failed_pids`, `failed_sources`, `timeout_count`, `query_error_count`, `truncated_count`
- 返回值包含完整的数据完整性字段

## 数据完整性链路

```
data_adapter.fetch_patient_obs_meds()
    ↓ data_complete
sofa_bridge.compute_sofa_scores()
    ↓ data_complete
db.judge_bundle_v3_for_patient()
    ↓ v3["sofa"]["data_complete"]
summary._compute_icu05()
    ↓ 最终 data_complete, failed_pids, failed_sources, ...
```

## 返回值格式

### batch_fetch_lab_observations()
```python
{
    "his_pid": {
        "observations": [...],
        "status": "success"|"no_data"|"timeout"|"query_error",
        "error": str|None,
        "data_complete": bool
    }
}
```

### summary._compute_icu05()
```python
{
    # ... 原有字段 ...
    "data_complete": bool,
    "failed_pids": [...],
    "failed_sources": [...],
    "timeout_count": int,
    "query_error_count": int,
    "truncated_count": int,
}
```

## 测试验证
- 所有现有测试通过
- 语法检查通过
- 导入测试通过
- 函数签名正确

## 关键特性
1. **区分查询失败与临床缺失**：timeout/query_error vs no_data
2. **跨批次去重**：通过 seen 集合避免重复处理
3. **limit 截断检测**：检测 5000/10000 limit 触发
4. **完整链路传递**：从数据适配器到最终汇总
5. **向后兼容**：batch_lab_cache 为可选参数
