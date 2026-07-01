# 课程基本信息审核规则

本文档描述审核维度 `kcjbxxsfykckyz` 的字段处理规则。

`kcjbxxsfykckyz` 表示“课程基本信息是否与课程库一致”。每次执行审核时，每套 PDF 都会生成该维度结果：

- 通过：`audit_findings.message = "是"`
- 不通过：`audit_findings.message = "否"`
- 不通过原因：写入 `audit_findings.details.reasons[]`，并在 `audit_field_findings.reason/message` 中保存字段级中文原因。

## 课程库定位

基础信息审核必须先定位课程库记录。定位结果会写入 `audit_results.summary.course_match`，后续其他审核维度也复用同一条课程库记录。

定位优先级如下：

1. 使用 PDF 抽取结果中的 `payload.jcxx.kcbh` 精确匹配 `courses.kcbh`。
2. 如果课程编号为空或未匹配成功，使用 `payload.jcxx.zwkcmc` 精确匹配 `courses.zwkcmc`。
3. 如果 PDF 内课程名称也为空，则从 `syllabus_extractions.source_path` 的文件名提取课程名称，再精确匹配 `courses.zwkcmc`。

文件名提取会去除目录、`.pdf` 扩展名、常见模板词、括号编号、空白字符等。例如：

```text
data_pdf/【经济】课程方案完整版/实验经济学计量方法.pdf
```

会提取为：

```text
实验经济学计量方法
```

只有唯一命中课程库记录时才使用该记录。无命中或多命中时，`kcjbxxsfykckyz` 判定为“否”，原因写中文，例如：

- 无法定位课程库记录
- 文件路径或课程名称匹配到多条课程库记录，需人工复核

## 精准比对规则

基础信息字段采用精准匹配，不做模糊判断。

比对时只清理首尾空白和非法控制字符，不删除内部空格，不忽略大小写，不统一数字格式，不做包含匹配。

判定规则：

- PDF 值与课程库值完全一致：通过。
- PDF 为空、课程库有值：不通过，原因写“XX为空”。
- PDF 有值、课程库为空：不通过，原因写“课程库中XX为空”。
- PDF 和课程库都为空：不通过，原因写“PDF 和课程库中的XX都为空”。
- PDF 和课程库都有值但不一致：不通过，原因写“XX与课程库不一致：课程库为 A，PDF 为 B”。

## 与课程库比对的字段

以下字段进入 `kcjbxxsfykckyz` 维度，并与课程库字段一一对应精准比对。

| PDF 字段路径 | PDF 字段含义 | 课程库字段 | 处理规则 |
| --- | --- | --- | --- |
| `payload.jcxx.kcbh` | 课程编号 | `courses.kcbh` | 精准一致，不能为空 |
| `payload.jcxx.kkyx` | 开课（院）系 | `courses.kkyx` | 精准一致，不能为空 |
| `payload.jcxx.zwkcmc` | 中文课程名称 | `courses.zwkcmc` | 精准一致，不能为空 |
| `payload.jcxx.ywkcmc` | 英文课程名称 | `courses.ywkcmc` | 精准一致，不能为空 |
| `payload.jcxx.skyy` | 授课语言 | `courses.skyy` | 精准一致，不能为空 |
| `payload.jcxx.sfyxwxyxk` | 是否允许外学院选课 | `courses.yxwxyxk` | 精准一致，不能为空 |
| `payload.jcxx.khfs` | 考核方式 | `courses.khfs` | 精准一致，不能为空 |
| `payload.jcxx.kcxz` | 课程性质 | `courses.kcxz` | 精准一致，不能为空 |
| `payload.jcxx.kclb` | 课程类别 | `courses.kclb` | 精准一致，不能为空 |
| `payload.jcxx.zxs` | 周学时 | `courses.zxs` | 精准一致，不能为空 |
| `payload.jcxx.skzs` | 上课周数 | `courses.skzs` | 精准一致，不能为空 |
| `payload.jcxx.zongxs` | 总学时 | `courses.zongxs` | 精准一致，不能为空 |
| `payload.jcxx.jxxs` | 教学学时 | `courses.jxxs` | 精准一致，不能为空 |
| `payload.jcxx.kcxf` | 课程学分 | `courses.kcxf` | 精准一致，不能为空 |
| `payload.jcxx.rkjsxm` | 任课教师姓名 | `courses.zjjsxm` | 精准一致，不能为空 |

## PDF 内部必填字段

以下字段只检查 PDF 中是否填写，不与课程库比对。

| PDF 字段路径 | 字段含义 | 处理规则 |
| --- | --- | --- |
| `payload.jcxx.jsgh` | 教师工号 | 必填，为空则不通过 |
| `payload.jcxx.email` | E-mail | 必填，为空则不通过 |
| `payload.jcxx.lxdh` | 联系电话 | 必填，为空则不通过 |

为空时原因写中文，例如：

- 教师工号为空
- E-mail为空
- 联系电话为空

## PDF 内部公式校验

基础信息还会检查 PDF 内部的学时公式：

```text
总学时 = 周学时 × 上课周数
```

对应字段：

- `payload.jcxx.zongxs`
- `payload.jcxx.zxs`
- `payload.jcxx.skzs`

如果三个字段都可转换为数字，则执行公式校验。

示例不通过原因：

```text
总学时不等于周学时乘以上课周数：总学时为 38，周学时 3 × 上课周数 7 = 21
```

如果任一字段为空，则该字段已经由精准比对规则产生“不通过”原因，公式校验不重复输出。

## 不进入基础信息审核的字段

以下四个字段不再与课程库比对，也不进入 `kcjbxxsfykckyz` 审核：

- `payload.jcxx.syxs`：实验学时
- `payload.jcxx.sjxs`：实践学时
- `payload.jcxx.qtxs`：其他学时
- `payload.jcxx.zxxs`：自学学时

这些字段可以继续保留在 PDF 抽取 payload 中，但基础信息审核不会为它们生成 `audit_field_findings` 记录。

## 入库位置

维度级结果写入 `audit_findings`：

- `wd = "kcjbxxsfykckyz"`
- `message = "是"` 或 `"否"`
- `details.label = "课程基本信息是否与课程库一致"`
- `details.result = "是"` 或 `"否"`
- `details.reasons[]` 保存中文不通过原因
- `details.course_match` 保存课程库定位结果

字段级结果写入 `audit_field_findings`：

- `section = "jcxx"`
- `field` 保存字段 key，例如 `kcbh`、`zwkcmc`、`zongxs`
- `path` 保存 JSON 路径，例如 `payload.jcxx.kcbh`
- `status` 保存 `pass` 或 `fail`
- `reason` 保存中文原因
- `message` 保存中文完整说明
- `expected` 保存课程库值或公式期望值
- `actual` 保存 PDF 实际值

## 常用查询

查询某轮基础信息维度不通过的课程：

```sql
SELECT r.subject_key, r.kcbh, r.source_path, f.message, f.details
FROM audit_results r
JOIN audit_findings f ON f.result_id = r.id
WHERE r.run_id = :run_id
  AND f.wd = 'kcjbxxsfykckyz'
  AND f.message = '否';
```

查询某轮基础信息字段级不通过原因：

```sql
SELECT subject_key, field, path, reason, expected, actual
FROM audit_field_findings
WHERE run_id = :run_id
  AND section = 'jcxx'
  AND status <> 'pass'
ORDER BY subject_key, field;
```
