# 课程方案审核系统

本项目用于批量导入课程方案 PDF 和课程库 Excel，将 PDF 抽取结果结构化入库，并按审核维度生成每轮审核结果、字段级不通过原因、LLM 调用记录和运行指标。

项目根目录为 `dev1`，主要代码位于 `src/syllabus_auditor`，数据库使用 PostgreSQL。

## 整体流程

1. 初始化数据库表结构。
2. 导入课程库 Excel 到 `courses` 表。
3. 批量读取课程方案 PDF，生成结构化 payload 和 meta，写入 `syllabus_extractions` 表。
4. 执行一轮审核，生成新的 `run_id`。
5. 每套课程在本轮生成一条 `audit_results` 总结果。
6. 每个审核维度写入 `audit_findings`。
7. 每个字段或子项的不通过原因写入 `audit_field_findings`。
8. LLM 审核维度保存完整 prompt、模型原始回答、解析结果到 `llm_trace`。
9. 本轮结束后计算审核指标，写入 `audit_run_metrics`。

## 常用命令

在项目根目录执行：

```cmd
cd /d C:\Users\Administrator\Desktop\课程方案\dev1
```

初始化或更新数据库：

```cmd
set PYTHONPATH=src
conda run -n course python -m syllabus_auditor.cli init-db
```

导入课程库 Excel：

```cmd
conda run -n course python -m syllabus_auditor.cli prepare-course-library --data-dir data
```

预览将要导入的 PDF：

```cmd
conda run -n course python -m syllabus_auditor.cli prepare-courses --input data --list-only
```

导入课程方案 PDF：

```cmd
conda run -n course python -m syllabus_auditor.cli prepare-courses --input data
```

执行一轮审核：

```cmd
conda run -n course python -m syllabus_auditor.cli run-batch
```

指定审核轮次名称：

```cmd
conda run -n course python -m syllabus_auditor.cli run-batch --run-name audit_2026_spring
```

## 数据表说明

核心表如下：

- `courses`：课程库 Excel 导入结果。
- `syllabus_extractions`：PDF 抽取结果，包含 `payload`、`meta`、`extraction_status`。
- `audit_runs`：每一轮审核记录，每次运行生成新的 `run_id`。
- `audit_results`：一套课程在一轮审核中的总结果。
- `audit_findings`：维度级审核结论，每个维度一行。
- `audit_field_findings`：字段级或子项级审核明细，保存不通过原因。
- `audit_run_metrics`：每轮审核的汇总指标。
- `audit_artifacts`：预留调试证据或大块材料。

维度结论统一存储在 `audit_findings`，不要给 `audit_results` 为每个维度新增独立字段。

## PDF 抽取结果

PDF 导入后写入 `syllabus_extractions`。

主要字段：

- `course_code`：技术关联用课程编号，缺失时可用文件名兜底定位课程库。
- `source_path`：PDF 原始路径。
- `payload`：结构化课程方案内容。
- `meta`：抽取过程信息、warning、未映射片段、原文片段等。
- `extraction_status`：`success`、`partial`、`failed`。

处理原则：

- 字段抽不到时保留空值，不因业务字段为空导致 PDF 导入失败。
- 字符串入库前会清理 `\x00` 等非法控制字符。
- 不标准模板中的额外列优先进入对应条目的 `kzzd`。
- 跨页续表、表头变体、额外列、低置信度片段都会通过 `meta.extraction_warnings` 或 `meta.unmapped_segments` 记录。

## 六个审核维度

### 1. 课程基本信息是否与课程库一致

- 编码：`kcjbxxsfykckyz`
- 方式：规则审核
- 判断 PDF 基础信息是否能唯一定位课程库记录，并与课程库字段精准一致。
- 不处理 `syxs`、`sjxs`、`qtxs`、`zxxs` 四个字段。

### 2. 教学内容是否与学时匹配

- 编码：`jxnrsfyxspp`
- 方式：规则审核
- 比较 `payload.jcxx.zongxs` 与 `payload.jxnr.zongxs`。
- 字段缺失时可从 meta 的对应语义区域兜底，但不能使用孤立、无法归属的“总学时”。

### 3. 教学安排是否与周次匹配

- 编码：`jxapsfyzcpp`
- 方式：规则审核
- 检查 `payload.jxap.tm[].zs` 是否从第 1 周连续覆盖。
- 支持 `1`、`第1周`、`5-9`、`5~9`、`1、2`、`1-3,5-6` 等周次写法。
- 最大周次必须等于 `payload.jcxx.skzs`。

### 4. 教学目标、内容、方式是否符合要求

- 编码：`jxmbnrfsfhyq`
- 方式：LLM 审核
- 拆成三个子项 prompt：
  - `jxmb`：教学目标是否符合要求。
  - `jxnr`：教学内容是否符合要求。
  - `jxfs`：教学方式是否符合要求。
- 三项全部为“是”时，总维度才为“是”。
- 完整 prompt、模型原始回答和解析结果保存到 `llm_trace.calls[]`。

### 5. 是否将思政元素有效融入各环节

- 编码：`szysfyxrghj`
- 方式：LLM 审核
- 一次 prompt 综合判断：
  - 课程目标中的思政目标。
  - 教学安排中的思政元素融入。
- 不审核预期教学成效。
- 判断是否有明确思政目标、教学安排是否有具体融入、两者是否形成呼应。

### 6. 信息要素完整、符合模板、是否有中英文简介

- 编码：`xxyzwzfhmb`
- 方式：规则审核
- “信息要素完整”和“符合模板”合并为 `mbxxyzwz`。
- “是否有中英文简介”单独形成 `zywjj`。
- `syxs`、`sjxs`、`qtxs`、`zxxs` 只在本维度检查 key 是否存在，允许值为空。
- 不判断内容质量，只判断字段、章节、表格列是否存在且非空。

## LLM 审核

当前 LLM 维度：

- `jxmbnrfsfhyq`
- `szysfyxrghj`

LLM 配置读取 `.env`：

```env
LLM_MODEL_NAME=模型名
LLM_API_KEY=密钥
LLM_BASE_URL=兼容 OpenAI 的接口地址
```

如果未配置 LLM：

- LLM 维度不会中断整轮审核。
- 对应维度会写入不通过或需人工复核原因。
- `llm_trace.calls[].status` 写为 `no_llm`。

如果模型返回非 JSON：

- 对应维度或子项判为不通过。
- 原始回答和解析异常写入 `llm_trace.calls[]`。

## 审核结果查询

查询某轮所有课程总结果：

```sql
SELECT *
FROM audit_results
WHERE run_id = 1
ORDER BY id;
```

查询某轮不通过或需关注课程：

```sql
SELECT *
FROM audit_results
WHERE run_id = 1
  AND overall_status IN ('fail', 'partial', 'error');
```

查询某轮某个维度结果：

```sql
SELECT ar.subject_key, ar.kcbh, ar.source_path,
       af.wd, af.status, af.message, af.details
FROM audit_results ar
JOIN audit_findings af ON af.result_id = ar.id
WHERE ar.run_id = 1
  AND af.wd = '信息要素完整、符合模板、是否有中英文简介';
```

查询某套课程字段级不通过原因：

```sql
SELECT section, field, path, status, reason, message, evidence
FROM audit_field_findings
WHERE run_id = 1
  AND subject_key = 'extraction:123'
  AND status <> 'pass'
ORDER BY section, field;
```

查询 LLM 原始回答：

```sql
SELECT wd, llm_trace
FROM audit_findings
WHERE run_id = 1
  AND wd IN ('教学目标、内容、方式是否符合要求', '是否将思政元素有效融入各环节');
```

## 审核指标

每轮审核完成后，系统会计算并写入 `audit_run_metrics`。

当前指标：

- `overall_pass_rate`：六个核心维度全部通过的课程占比。
- `dimension_pass_rates`：各维度通过率。
- `reason_top10`：字段级不通过原因 Top 10。
- `missing_field_top10`：字段缺失或为空 Top 10。
- `manual_review_course_count`：需人工复核课程数。
- `llm_exception_count`：LLM 异常次数。
- `llm_status_counts`：LLM 异常状态分布。

查询某轮全部指标：

```sql
SELECT metric_key, metric_value
FROM audit_run_metrics
WHERE run_id = 1
ORDER BY metric_key;
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

## 文档索引

详细设计文档位于 `docs`：

- `项目结构说明.md`
- `courses表设计.md`
- `syllabus_extractions表设计.md`
- `audit_runs表设计.md`
- `audit_run_metrics表设计.md`
- `课程基本信息是否与课程库一致.md`
- `教学内容是否与学时匹配.md`
- `教学安排是否与周次匹配.md`
- `教学目标内容方式是否符合要求.md`
- `是否将思政元素有效融入各环节.md`
- `信息要素完整符合模板是否有中英文简介.md`

## 开发验证

运行核心测试：

```cmd
conda run -n course python -m unittest tests.test_audit tests.test_xxyzwzfhmb tests.test_szysfyxrghj tests.test_jxmbnrfsfhyq
```

编译检查：

```cmd
conda run -n course python -m compileall src tests
```

数据库结构更新：

```cmd
set PYTHONPATH=src
conda run -n course python -m syllabus_auditor.cli init-db
```
