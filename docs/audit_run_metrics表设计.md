# audit_run_metrics 表设计

## 用途

`audit_run_metrics` 保存每一轮审核 `run_id` 的轻量汇总指标。

这些指标在 `run-batch` 完成时由系统自动计算并入库，用于快速查看本轮审核效果，不需要人工标注，也不需要重新扫描 PDF。

## 表结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGSERIAL` | 主键 |
| `run_id` | `BIGINT` | 审核轮次 ID，关联 `audit_runs.id` |
| `metric_key` | `TEXT` | 指标编码 |
| `metric_value` | `JSONB` | 指标内容 |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | 更新时间 |

唯一约束：

```sql
UNIQUE (run_id, metric_key)
```

同一轮同一指标只保留一条，重复计算时更新 `metric_value`。

## 当前指标

### `overall_pass_rate`

本轮整体通过率。

“整体通过”指六个核心维度全部通过：

- `kcjbxxsfykckyz`
- `jxnrsfyxspp`
- `jxapsfyzcpp`
- `jxmbnrfsfhyq`
- `szysfyxrghj`
- `xxyzwzfhmb`

示例：

```json
{
  "total": 631,
  "pass_count": 520,
  "fail_count": 111,
  "pass_rate": 0.8241,
  "dimension_count": 6,
  "dimensions": ["kcjbxxsfykckyz", "jxnrsfyxspp"]
}
```

### `dimension_pass_rates`

六个维度分别的通过率。

示例：

```json
{
  "kcjbxxsfykckyz": {
    "total": 631,
    "pass_count": 580,
    "fail_count": 51,
    "pass_rate": 0.9192
  }
}
```

### `reason_top10`

字段级不通过原因 Top 10。

来源：`audit_field_findings.reason`。

示例：

```json
[
  {"reason": "课程英文简介为空", "count": 22},
  {"reason": "教学安排周次不连续，缺少第 4 周", "count": 18}
]
```

### `missing_field_top10`

字段缺失/为空类原因 Top 10。

来源：`audit_field_findings.reason` 中包含：

- `为空`
- `字段缺失`
- `缺失`

示例：

```json
[
  {
    "section": "payload",
    "field": "kcywjj",
    "path": "payload.kcywjj",
    "reason": "课程英文简介为空",
    "count": 22
  }
]
```

### `manual_review_course_count`

本轮需要人工复核的课程数量。

统计规则：

- 字段原因或说明包含 `需人工复核`
- 或包含 `无法定位课程库记录`

按 `result_id` 去重统计。

### `llm_exception_count`

LLM 调用异常次数。

统计 `audit_findings.llm_trace.calls[].status` 为：

- `parse_error`
- `no_llm`

### `llm_status_counts`

LLM 异常状态分布。

示例：

```json
{
  "parse_error": 2,
  "no_llm": 1262
}
```

## 查询示例

查询某轮全部指标：

```sql
SELECT metric_key, metric_value
FROM audit_run_metrics
WHERE run_id = 1
ORDER BY metric_key;
```

查询某轮各维度通过率：

```sql
SELECT metric_value
FROM audit_run_metrics
WHERE run_id = 1
  AND metric_key = 'dimension_pass_rates';
```

查询最近一轮整体通过率：

```sql
SELECT m.metric_value
FROM audit_run_metrics m
JOIN audit_runs r ON r.id = m.run_id
WHERE m.metric_key = 'overall_pass_rate'
ORDER BY r.started_at DESC
LIMIT 1;
```

## 与 audit_runs.summary 的关系

`complete_run` 会同时把完整指标快照写入：

- `audit_run_metrics`
- `audit_runs.summary.metrics`

规范查询建议使用 `audit_run_metrics`，`audit_runs.summary.metrics` 仅作为运行总览快照。

