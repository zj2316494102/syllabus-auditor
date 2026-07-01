# syllabus_extractions 表设计说明（PostgreSQL）

本文档定义课程方案 PDF 抽取结果在 **PostgreSQL** 中的存储方案：将一份 PDF 按模版字段拆分为 `payload`（JSONB），并用 `meta`（JSONB）保留全文转化结果及无法归类的片段（**策略 B**）。

**字段键命名**：`payload` 业务字段采用**中文拼音首字母**缩写（如 `kcbh` = 课程编号），PDF 解析层负责「中文标签 → 字段键」映射；文档表格中均含 **释义** 列标注对应中文名。

---

## 一、PostgreSQL 环境

### 1.1 版本与扩展

| 项 | 要求 |
|----|------|
| PostgreSQL | **14+**（推荐 15/16；JSONB 与 GIN 索引成熟稳定） |
| 必需扩展 | 无（本表仅使用内置 `JSONB`） |
| 可选扩展 | `pgvector`（后续 RAG 审核检索 `reference_chunks` 时使用，与本表无强依赖） |

### 1.2 连接配置（`.env`）

```env
POSTGRES_ADDRESS=localhost:5432
POSTGRES_DB=syllabus_auditor
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
```

应用层通过 `psycopg`（v3）连接，`POSTGRES_ADDRESS` 支持 `host` 或 `host:port` 两种写法。

### 1.3 Schema 约定

| Schema | 用途 |
|--------|------|
| `public` | 默认业务表（本表、`courses` 等） |

本表位于 **`public.syllabus_extractions`**。

---

## 二、字段键命名约定

| 规则 | 说明 | 示例 |
|------|------|------|
| 拼音首字母 | 多字词取每字拼音首字母 | 课程编号 → `kcbh` |
| 冲突消歧 | 首字母相同时加长或改用全称音节 | 周学时 `zxs`，总学时 `zongxs` |
| 同义区分 | 不同章节出现相同中文名时拆分键名 | 基本信息考核 `jcxx.khfs`；考核章节 `khfsb` |
| 数组统一 | 表格各行统一用 `tm`（条目） | `jxnr.tm`、`jxap.tm`、`khfsb.tm` |
| 概述兜底 | 无法结构化时写入 `*gs` 字段 | 目标概述 `mbgs`、内容概述 `nrgs` |
| meta 技术字段 | 保留英文 snake_case | `full_text`、`raw_pages` |

---

## 三、设计策略（策略 B）

| 层级 | JSONB 路径 | 释义 | 用途 |
|------|------------|------|------|
| 结构化 | `payload` | 载荷 | 按 PDF 模版拆分的业务字段 |
| 章节兜底 | `payload.kcmb.mbgs` 等 | 各模块概述 | 该章节无法结构化时的概述 |
| 全文备份 | `meta.full_text` / `meta.raw_pages` | 全文 / 按页原文 | 整份 PDF 全量文本 |
| 未映射片段 | `meta.unmapped_segments` | 未映射片段 | 无法归入 payload 的游离文本 |

---

## 四、DDL：建表与索引

### 4.1 枚举：抽取状态

```sql
CREATE TYPE extraction_status AS ENUM ('success', 'partial', 'failed');
```

### 4.2 主表

```sql
CREATE TABLE IF NOT EXISTS public.syllabus_extractions (
    id                  BIGSERIAL PRIMARY KEY,
    course_code         TEXT        NOT NULL,
    source_path         TEXT        NOT NULL,
    payload             JSONB       NOT NULL DEFAULT '{}'::jsonb,
    meta                JSONB       NOT NULL DEFAULT '{}'::jsonb,
    extractor           TEXT,
    extraction_status   extraction_status,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT syllabus_extractions_payload_is_object
        CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT syllabus_extractions_meta_is_object
        CHECK (jsonb_typeof(meta) = 'object')
);

COMMENT ON TABLE public.syllabus_extractions IS
    '课程方案 PDF 抽取结果：payload 为结构化字段，meta 为全文与未映射片段';
COMMENT ON COLUMN public.syllabus_extractions.course_code IS '课程编号（kcbh），与 courses 表逻辑关联';
COMMENT ON COLUMN public.syllabus_extractions.payload IS '结构化 JSONB，字段键为拼音首字母，见第六节';
COMMENT ON COLUMN public.syllabus_extractions.meta IS 'PDF 全量转化与 unmapped_segments，见第七节';
```

### 4.3 索引

```sql
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_course_code
    ON public.syllabus_extractions (course_code);

CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_course_created
    ON public.syllabus_extractions (course_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_payload_gin
    ON public.syllabus_extractions USING GIN (payload jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_meta_gin
    ON public.syllabus_extractions USING GIN (meta jsonb_path_ops);

-- 表达式索引：中文课程名、开课院系
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_cn_name
    ON public.syllabus_extractions ((payload #>> '{jcxx,zwkcmc}'));

CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_department
    ON public.syllabus_extractions ((payload #>> '{jcxx,kkyx}'));

CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_status
    ON public.syllabus_extractions (extraction_status)
    WHERE extraction_status IS NOT NULL;
```

### 4.4 updated_at 自动更新

```sql
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_syllabus_extractions_updated_at
    BEFORE UPDATE ON public.syllabus_extractions
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();
```

> PostgreSQL 14 使用 `EXECUTE PROCEDURE`；15+ 推荐 `EXECUTE FUNCTION`。

---

## 五、关系型列说明

| 列名 | PostgreSQL 类型 | 约束 | 释义 | 说明 |
|------|-----------------|------|------|------|
| `id` | `BIGSERIAL` | `PRIMARY KEY` | 主键 | 自增 ID |
| `course_code` | `TEXT` | `NOT NULL` | 课程编号 | 与 `courses` 逻辑关联；与 `payload.jcxx.kcbh` 一致 |
| `source_path` | `TEXT` | `NOT NULL` | 源文件路径 | 原始 PDF 路径 |
| `payload` | `JSONB` | `NOT NULL` | 结构化载荷 | 见第六节 |
| `meta` | `JSONB` | `NOT NULL` | 元数据 | 见第七节 |
| `extractor` | `TEXT` | 可空 | 抽取器 | 如 `pdfplumber:0.11.0` |
| `extraction_status` | `extraction_status` | 可空 | 抽取状态 | `success` / `partial` / `failed` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | 创建时间 | 入库时间 |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | 更新时间 | 触发器维护 |

**一行对应**：一门课的一份 PDF 抽取结果。重复导入建议**插入新行**保留历史；业务层按 `(course_code, created_at DESC)` 取最新。

---

## 六、payload 结构（JSONB）

`payload` 为 JSONB 对象。访问方式：`payload -> 'jcxx' ->> 'kcbh'` 或 `payload #>> '{jcxx,kcbh}'`。

> **注意**：`jcxx.khfs` 为基本信息表中的短考核形式（如「课堂闭卷」）；`khfsb` 为「（八）考核方式」章节表格，二者不可混用。

### 6.1 顶层键

| 字段键 | 释义 | JSON 类型 | PostgreSQL 访问示例 |
|--------|------|-----------|---------------------|
| `jcxx` | 基础信息（含主讲教师） | object | `payload -> 'jcxx'` |
| `kczwjj` | 课程中文简介 | string | `payload ->> 'kczwjj'` |
| `kcywjj` | 课程英文简介 | string | `payload ->> 'kcywjj'` |
| `ybzsyq` | 预备知识要求 | string | `payload ->> 'ybzsyq'` |
| `jcjydcl` | 教材及阅读材料 | string | `payload ->> 'jcjydcl'` |
| `kcmb` | 课程目标 | object | `payload -> 'kcmb'` |
| `jxnr` | 教学内容 | object | `payload -> 'jxnr'` |
| `jxap` | 教学安排 | object | `payload -> 'jxap'` |
| `kcyq` | 课程要求 | string | `payload ->> 'kcyq'` |
| `khfsb` | 考核方式（章节表格） | object | `payload -> 'khfsb'` |

---

### 6.2 基础信息 `payload.jcxx`

含课程基本信息表全部字段及**主讲教师**四项，不再单独设顶层对象。

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `kcbh` | 课程编号 | string | |
| `kkyx` | 开课（院）系 | string | |
| `zwkcmc` | 中文课程名称 | string | |
| `ywkcmc` | 英文课程名称 | string | |
| `skyy` | 授课语言 | string | |
| `sfyxwxyxk` | 是否允许外学院选课 | string | |
| `khfs` | 考核方式 | string | 基本信息表中的短文本，非 `khfsb` |
| `kcxz` | 课程性质 | string | |
| `kclb` | 课程类别 | string | |
| `zxs` | 周学时 | string | 与 `zongxs`（总学时）区分 |
| `skzs` | 上课周数 | string | |
| `zongxs` | 总学时 | string | 审核：周学时 × 上课周数 |
| `jxxs` | 教学学时 | string | |
| `syxs` | 实验学时 | string | |
| `sjxs` | 实践学时 | string | |
| `qtxs` | 其他学时 | string | |
| `zxxs` | 自学学时 | string | |
| `kcxf` | 课程学分 | string | |
| `rkjsxm` | 任课教师姓名 | string | 主讲教师 |
| `jsgh` | 教师工号 | string | 主讲教师 |
| `email` | 邮箱 | string | 主讲教师 |
| `lxdh` | 联系电话 | string | 主讲教师 |

---

### 6.3 课程目标 `payload.kcmb`

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `szmb` | 思政目标 | string | |
| `nlmb` | 能力目标 | string | |
| `zsmb` | 知识目标 | string | |
| `mbgs` | 目标概述 | string | 无法拆三类时写入；正常为 `""` |

---

### 6.4 教学内容 `payload.jxnr`

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `tm` | 条目 | array | 无法表格化时为 `[]` |
| `zongxs` | 总学时 | string | 表底课时总计 |
| `nrgs` | 内容概述 | string | 无法表格化时写入；正常为 `""` |

**`tm[]` 元素**：

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `xh` | 序号 | string | 行序号，非周次 |
| `zt` | 主题 | string | |
| `zsd` | 知识点 | string | 多条可用 `\n` 连接 |
| `xs` | 学时 | string | |

---

### 6.5 教学安排 `payload.jxap`

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `tm` | 条目 | array | 无法表格化时为 `[]` |
| `apgs` | 安排概述 | string | 无法表格化时写入；正常为 `""` |

**`tm[]` 元素**：

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `zs` | 周数 | string | 连续周，如 `"1"`、`"3-4"` |
| `sknr` | 授课内容 | string | |
| `skfs` | 授课方式 | string | |
| `szyqjxx` | 思政元素的融入和预期教学成效 | string | |

---

### 6.6 课程要求 `payload.kcyq`

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| （顶层键 `kcyq`） | 课程要求 | string | 章节全文 |

---

### 6.7 考核方式 `payload.khfsb`

按**考试形式**分行，使用 `tm` 数组 + `ksxs` 字段，避免中文动态键。

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `tm` | 条目 | array | 无法表格化时为 `[]` |
| `khgs` | 考核概述 | string | 无法表格化时写入；正常为 `""` |

**`tm[]` 元素**：

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `ksxs` | 考试形式 | string | 如「期末考试」「课堂展示」 |
| `kcnr` | 考察内容 | string | |
| `kcfs` | 考察方式 | string | |
| `zb` | 占比 | string | 如 `"40%"` |

---

### 6.8 payload 完整示例

```json
{
  "jcxx": {
    "kcbh": "0202J92002",
    "kkyx": "财税学院",
    "zwkcmc": "财税量化分析",
    "ywkcmc": "Quantitative Analysis in Fiscal and Taxation",
    "skyy": "中文",
    "sfyxwxyxk": "否",
    "khfs": "课堂闭卷",
    "kcxz": "专业必修课",
    "kclb": "学术学位硕士",
    "zxs": "3",
    "skzs": "19",
    "zongxs": "57",
    "jxxs": "57",
    "syxs": "0",
    "sjxs": "0",
    "qtxs": "0",
    "zxxs": "0",
    "kcxf": "3",
    "rkjsxm": "张三",
    "jsgh": "20051052",
    "email": "zhangsan@swufe.edu.cn",
    "lxdh": "028-87092000"
  },
  "kczwjj": "……",
  "kcywjj": "……",
  "ybzsyq": "……",
  "jcjydcl": "……",
  "kcmb": {
    "szmb": "……",
    "nlmb": "……",
    "zsmb": "……",
    "mbgs": ""
  },
  "jxnr": {
    "tm": [
      {
        "xh": "1",
        "zt": "导论、基础计量模型",
        "zsd": "一元、多元线性回归\nStata应用简介（一）",
        "xs": "6"
      }
    ],
    "zongxs": "57",
    "nrgs": ""
  },
  "jxap": {
    "tm": [
      {
        "zs": "1",
        "sknr": "导论，线性回归",
        "skfs": "课堂讲授讨论",
        "szyqjxx": "……"
      }
    ],
    "apgs": ""
  },
  "kcyq": "1. ……\n2. ……",
  "khfsb": {
    "tm": [
      {
        "ksxs": "期末考试",
        "kcnr": "课程教学内容",
        "kcfs": "课程论文",
        "zb": "40%"
      },
      {
        "ksxs": "课堂展示",
        "kcnr": "课程教学内容",
        "kcfs": "课题小组展示论文解读",
        "zb": "40%"
      },
      {
        "ksxs": "平时成绩",
        "kcnr": "课堂课后综合表现",
        "kcfs": "课堂参与、课后作业等",
        "zb": "20%"
      }
    ],
    "khgs": ""
  }
}
```

---

### 6.9 字段键速查表（payload 全量）

| 字段键 | 释义 | 路径 |
|--------|------|------|
| `jcxx` | 基础信息 | 顶层 |
| `kcbh` | 课程编号 | `jcxx` |
| `kkyx` | 开课（院）系 | `jcxx` |
| `zwkcmc` | 中文课程名称 | `jcxx` |
| `ywkcmc` | 英文课程名称 | `jcxx` |
| `skyy` | 授课语言 | `jcxx` |
| `sfyxwxyxk` | 是否允许外学院选课 | `jcxx` |
| `khfs` | 考核方式（基本信息） | `jcxx` |
| `kcxz` | 课程性质 | `jcxx` |
| `kclb` | 课程类别 | `jcxx` |
| `zxs` | 周学时 | `jcxx` |
| `skzs` | 上课周数 | `jcxx` |
| `zongxs` | 总学时 | `jcxx` / `jxnr` |
| `jxxs` | 教学学时 | `jcxx` |
| `syxs` | 实验学时 | `jcxx` |
| `sjxs` | 实践学时 | `jcxx` |
| `qtxs` | 其他学时 | `jcxx` |
| `zxxs` | 自学学时 | `jcxx` |
| `kcxf` | 课程学分 | `jcxx` |
| `rkjsxm` | 任课教师姓名 | `jcxx` |
| `jsgh` | 教师工号 | `jcxx` |
| `email` | 邮箱 | `jcxx` |
| `lxdh` | 联系电话 | `jcxx` |
| `kczwjj` | 课程中文简介 | 顶层 |
| `kcywjj` | 课程英文简介 | 顶层 |
| `ybzsyq` | 预备知识要求 | 顶层 |
| `jcjydcl` | 教材及阅读材料 | 顶层 |
| `kcmb` | 课程目标 | 顶层 |
| `szmb` | 思政目标 | `kcmb` |
| `nlmb` | 能力目标 | `kcmb` |
| `zsmb` | 知识目标 | `kcmb` |
| `mbgs` | 目标概述 | `kcmb` |
| `jxnr` | 教学内容 | 顶层 |
| `tm` | 条目 | `jxnr` / `jxap` / `khfsb` |
| `xh` | 序号 | `jxnr.tm[]` |
| `zt` | 主题 | `jxnr.tm[]` |
| `zsd` | 知识点 | `jxnr.tm[]` |
| `xs` | 学时 | `jxnr.tm[]` |
| `nrgs` | 内容概述 | `jxnr` |
| `jxap` | 教学安排 | 顶层 |
| `zs` | 周数 | `jxap.tm[]` |
| `sknr` | 授课内容 | `jxap.tm[]` |
| `skfs` | 授课方式 | `jxap.tm[]` |
| `szyqjxx` | 思政元素的融入和预期教学成效 | `jxap.tm[]` |
| `apgs` | 安排概述 | `jxap` |
| `kcyq` | 课程要求 | 顶层 |
| `khfsb` | 考核方式（章节） | 顶层 |
| `ksxs` | 考试形式 | `khfsb.tm[]` |
| `kcnr` | 考察内容 | `khfsb.tm[]` |
| `kcfs` | 考察方式 | `khfsb.tm[]` |
| `zb` | 占比 | `khfsb.tm[]` |
| `khgs` | 考核概述 | `khfsb` |

---

## 七、meta 结构（JSONB · 策略 B）

meta 以英文 snake_case 为主，便于与通用工具链接。

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `source_path` | 源文件路径 | string | 与表列 `source_path` 一致 |
| `extracted_at` | 抽取时间 | string | ISO 8601 |
| `extractor` | 抽取器 | string | 如 `pdfplumber:0.11.0` |
| `page_count` | 页数 | number | PDF 总页数 |
| `full_text` | 全文 | string | 拼接全文 |
| `raw_pages` | 按页原文 | array | `string[]` |
| `unmapped_segments` | 未映射片段 | array | 见下表 |

**`unmapped_segments[]` 元素**：

| 字段键 | 释义 | JSON 类型 | 说明 |
|--------|------|-----------|------|
| `segment_id` | 片段 ID | string | 如 `seg_001` |
| `text` | 片段原文 | string | |
| `page` | 页码 | number | 从 1 起 |
| `reason` | 未映射原因 | string | `unknown_section` / `parse_failed` / `overflow` |
| `context` | 上下文摘要 | string | 可选，便于人工定位 |

```json
{
  "source_path": "data_pdf/财税量化分析.pdf",
  "extracted_at": "2026-06-23T12:00:00+08:00",
  "extractor": "pdfplumber:0.11.0",
  "page_count": 5,
  "full_text": "（一）课程基本信息\n……",
  "raw_pages": ["第1页……", "第2页……"],
  "unmapped_segments": [
    {
      "segment_id": "seg_001",
      "text": "附：2024年修订说明……",
      "page": 5,
      "reason": "unknown_section",
      "context": "文档末尾，无对应模版字段"
    }
  ]
}
```

---

## 八、常用 SQL 示例

### 8.1 插入

```sql
INSERT INTO public.syllabus_extractions (
    course_code, source_path, payload, meta, extractor, extraction_status
) VALUES (
    '0202J92002',
    'data_pdf/财税量化分析.pdf',
    '{"jcxx": {"kcbh": "0202J92002", "zwkcmc": "财税量化分析"}}'::jsonb,
    '{"full_text": "……", "raw_pages": [], "unmapped_segments": []}'::jsonb,
    'pdfplumber:0.11.0',
    'partial'
);
```

### 8.2 按课程编号取最新一条

```sql
SELECT id, course_code, payload, meta, extraction_status, created_at
FROM public.syllabus_extractions
WHERE course_code = '0202J92002'
ORDER BY created_at DESC
LIMIT 1;
```

### 8.3 读取 payload 字段

```sql
SELECT
    course_code,
    payload #>> '{jcxx,zwkcmc}'              AS cn_name,
    payload #>> '{jcxx,zongxs}'              AS total_hours,
    payload #>> '{jcxx,rkjsxm}'              AS instructor,
    payload -> 'kcmb' ->> 'szmb'             AS ideological_goal,
    payload -> 'jxnr' ->> 'zongxs'           AS content_total_hours,
    jsonb_array_length(payload -> 'jxnr' -> 'tm') AS content_row_count
FROM public.syllabus_extractions
WHERE course_code = '0202J92002';
```

### 8.4 筛选需人工复核的记录

```sql
-- 存在未映射片段
SELECT id, course_code, extraction_status
FROM public.syllabus_extractions
WHERE jsonb_array_length(COALESCE(meta -> 'unmapped_segments', '[]'::jsonb)) > 0;

-- 使用了概述兜底
SELECT id, course_code
FROM public.syllabus_extractions
WHERE (payload -> 'kcmb' ->> 'mbgs') <> ''
   OR (payload -> 'jxnr' ->> 'nrgs') <> ''
   OR (payload -> 'jxap' ->> 'apgs') <> ''
   OR (payload -> 'khfsb' ->> 'khgs') <> '';

-- 抽取失败队列
SELECT id, course_code, source_path, created_at
FROM public.syllabus_extractions
WHERE extraction_status = 'failed';
```

### 8.5 全文检索（可选）

```sql
SELECT course_code, payload #>> '{jcxx,zwkcmc}' AS cn_name
FROM public.syllabus_extractions
WHERE meta ->> 'full_text' ILIKE '%双重差分%';
```

---

## 九、写入优先级（策略 B）

```text
PDF 全文
  ├─1─► meta.full_text / meta.raw_pages
  ├─2─► payload 各结构化字段（拼音键）
  ├─3─► payload.*.*gs 概述字段（章节无法结构化时）
  └─4─► meta.unmapped_segments（仍无法归类）
```

| 场景 | 写入位置 |
|------|----------|
| 课程目标正常拆分 | `kcmb.szmb` / `nlmb` / `zsmb` |
| 课程目标无法拆分 | `kcmb.mbgs` 有值，三类为 `""` |
| 不属于任何章节 | `meta.unmapped_segments` |
| 表格部分行失败 | 成功行 → `tm[]`；失败片段 → `unmapped_segments` |

---

## 十、extraction_status

| 值 | 释义 | 含义 |
|----|------|------|
| `success` | 成功 | 结构化完整，无 `unmapped_segments`，无概述兜底 |
| `partial` | 部分成功 | 有缺失、`unmapped_segments` 或概述兜底 |
| `failed` | 失败 | 抽取失败，`payload` 可能为 `{}` |

---

## 十一、与 courses 表的关系

| 表 | 说明 |
|----|------|
| `courses` | 课程库基准（Excel 导入） |
| `syllabus_extractions` | PDF 抽取结果，通过 `course_code` 与 `jcxx.kcbh` 逻辑关联 |

审核对比：`courses.*` ↔ `syllabus_extractions.payload.jcxx.*`

---

## 十二、概述字段汇总

| 字段键 | 释义 | JSONB 路径 |
|--------|------|------------|
| `mbgs` | 目标概述 | `payload -> 'kcmb' -> 'mbgs'` |
| `nrgs` | 内容概述 | `payload -> 'jxnr' -> 'nrgs'` |
| `apgs` | 安排概述 | `payload -> 'jxap' -> 'apgs'` |
| `khgs` | 考核概述 | `payload -> 'khfsb' -> 'khgs'` |

---

## 十三、非标准表格字段

PDF 解析层允许课程目标、教学内容、教学安排、课程要求、考核方式等章节出现非标准列，但写入 `payload` 时字段键仍必须使用拼音/ASCII，不允许把中文表头作为 JSON key。

| 字段键 | 释义 | JSONB 路径 | 说明 |
|--------|------|------------|------|
| `zy` | 作业 | `payload -> 'jxap' -> 'tm' -> n -> 'zy'` | 教学安排中出现 `作业`、`作业/测验`、`学习任务` 等列时写入 |
| `kzzd` | 扩展字段 | 各章节对象或 `tm[]` 条目内 | 用于保留非标准列 |
| `bt` | 原表头 | `kzzd[] -> 'bt'` | 存中文原表头值，不作为 key |
| `nr` | 内容 | `kzzd[] -> 'nr'` | 存该扩展列内容 |
| `kcyqb` | 课程要求表 | `payload -> 'kcyqb'` | 结构化课程要求；兼容保留顶层 `kcyq` 字符串 |
| `yqgs` | 要求概述 | `payload -> 'kcyqb' -> 'yqgs'` | 课程要求无法表格化时写入 |

示例：

```json
{
  "jxap": {
    "tm": [
      {
        "zs": "1",
        "sknr": "UNIT 1 ...",
        "skfs": "讲授",
        "zy": "微信群",
        "szyqjxx": "根据《高等学校课程思政建设指导纲要》...",
        "kzzd": [
          { "bt": "备注", "nr": "课前阅读" }
        ]
      }
    ],
    "apgs": ""
  }
}
```

`apgs`、`nrgs`、`mbgs`、`khgs`、`yqgs` 只表示整章无法结构化时的概述兜底；某一行多出的列应写入该行的 `kzzd`，不写入 `*gs`。

---

## 十四、Python 写入参考（psycopg3）

```python
import json
from psycopg import connect

payload = {
    "jcxx": {"kcbh": "0202J92002", "zwkcmc": "财税量化分析"},
    "kcmb": {"szmb": "", "nlmb": "", "zsmb": "", "mbgs": ""},
}
meta = {"full_text": "……", "raw_pages": [], "unmapped_segments": []}

with connect("postgresql://user:pass@localhost:5432/syllabus_auditor") as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO syllabus_extractions
                (course_code, source_path, payload, meta, extractor, extraction_status)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                "0202J92002",
                "data_pdf/财税量化分析.pdf",
                json.dumps(payload, ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
                "pdfplumber:0.11.0",
                "partial",
            ),
        )
    conn.commit()
```

PDF 解析层维护「PDF 中文标签 → 字段键」映射（如 `课程编号` → `kcbh`），写入 DB 前统一转换为拼音键。

---

*文档版本：syllabus_extractions v1.2 · PostgreSQL · 策略 B · 拼音首字母字段键*
