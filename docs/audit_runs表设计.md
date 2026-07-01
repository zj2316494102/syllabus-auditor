# 审核运行表设计说明（PostgreSQL）

本文档定义**批量审核运行**相关的 PostgreSQL 表结构：记录每次 `run-batch` 的任务信息、每门课总体结果、各维度明细及调试产物。

**设计目标**：

- 与 `courses`（课程库）、`syllabus_extractions`（PDF 抽取）配合使用
- **同时支持** `rule`（纯规则）、`direct_llm`（按维度直喂 LLM）、`rag_llm`（检索 + LLM）三种判定路径
- 同一批次可**混用**多种判定方式，由配置快照决定，表结构不因是否使用 RAG 而改变

---

## 一、表总览

| 表名 | 释义 | 粒度 |
|------|------|------|
| `reference_chunks` | 参考规则片段 | 一条规则/关键词切片 |
| `audit_runs` | 审核运行 | 一次 `run-batch` 任务 |
| `audit_results` | 审核结果（课程级） | 一次 run 中一门课 |
| `audit_findings` | 审核发现（维度级） | 一门课的一个审核维度 |
| `audit_artifacts` | 审核产物 | 可选调试信息（prompt、LLM 输出、检索记录等） |

### 1.1 关系示意

```text
courses ──────────────────┐
                          ├──► audit_results ──► audit_findings ──► audit_artifacts
syllabus_extractions ─────┘           ▲
                                      │
                                audit_runs
                                      │
                         config_snapshot（各维度判定模式）
                                      │
              reference_chunks ◄──────┘
                direct_llm：按 wd 全量读取
                rag_llm：检索 top_k
```

### 1.2 判定路径与落库

| 判定方式 | 代码键 `type` | 释义 | 主要写入 |
|----------|---------------|------|----------|
| 纯规则 | `rule` | 字段比对、算术校验等 | `audit_findings` + `artifact(field_diff)` |
| 直喂 LLM | `direct_llm` | 按维度组装 payload 字段 + 规则全文送 LLM | `findings` + `artifacts(input_context, rule_pack, prompt, llm_response)` |
| RAG + LLM | `rag_llm` | 从 `reference_chunks` 检索后送 LLM | `findings` + `artifacts(retrieval, prompt, llm_response)` |

**不用 RAG 时**：不出现 `retrieval` 类型 artifact；**用 RAG 时**：额外写入检索结果，**不改表结构**。

---

## 二、判定模式配置（config_snapshot）

写入 `audit_runs.config_snapshot`，记录本次运行可复现的配置。

### 2.1 顶层结构示例

```json
{
  "import_term": "2026-spring",
  "llm_default": "qwen_audit",
  "auditors": ["jcxx_yz", "mb_yq", "xs_pp", "sz_yr"],
  "audit_modes": {
    "jcxx_yz": { "type": "rule" },
    "mb_yq":   { "type": "direct_llm", "llm": "qwen_audit" },
    "xs_pp":   { "type": "rule" },
    "sz_yr":   { "type": "rag_llm", "llm": "qwen_audit", "retriever": "bm25", "top_k": 5 }
  },
  "project_yaml_hash": "abc123..."
}
```

### 2.2 audit_modes 各 type 字段

| 字段 | 释义 | 适用 type |
|------|------|-----------|
| `type` | 判定方式 | 必填：`rule` / `direct_llm` / `rag_llm` |
| `llm` | LLM 配置名 | `direct_llm`、`rag_llm` |
| `retriever` | 检索器名 | 仅 `rag_llm` |
| `top_k` | 检索条数 | 仅 `rag_llm` |
| `input_sections` | 从 payload 取的章节键 | 可选，如 `["kcmb","jxnr"]` |

---

## 三、reference_chunks（参考规则库）

细则 txt、关键词 xlsx 等导入后切片存储。**direct_llm 按维度全量读取；rag_llm 对同表做检索。**

### 3.1 DDL

```sql
CREATE TABLE IF NOT EXISTS public.reference_chunks (
    id          BIGSERIAL PRIMARY KEY,
    wd          TEXT,
    source      TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding   vector(1024),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.reference_chunks IS '审核参考规则片段；direct_llm 按 wd 全量读，rag_llm 检索';
COMMENT ON COLUMN public.reference_chunks.wd IS '关联审核维度码，可空表示通用规则';
COMMENT ON COLUMN public.reference_chunks.embedding IS '可选；仅 rag_llm 需要，需 pgvector 扩展';

CREATE INDEX IF NOT EXISTS idx_reference_chunks_wd ON public.reference_chunks (wd);
CREATE INDEX IF NOT EXISTS idx_reference_chunks_source ON public.reference_chunks (source);
-- rag_llm 启用时再建：
-- CREATE INDEX idx_reference_chunks_embedding ON reference_chunks USING hnsw (embedding vector_cosine_ops);
```

> **注意**：`embedding` 可空。未安装 pgvector 或未生成向量时，仍可用 `direct_llm` + 按 `wd` 读 `content`。

### 3.2 列说明

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `id` | 主键 | BIGSERIAL | |
| `wd` | 关联维度码 | TEXT | 如 `mb_yq`；NULL = 通用 |
| `source` | 来源 | TEXT | 文件名或路径 |
| `content` | 规则正文 | TEXT | |
| `metadata` | 元数据 | JSONB | 行号、sheet 名等 |
| `embedding` | 向量 | vector(1024) | **可选**，rag 用 |
| `created_at` | 创建时间 | TIMESTAMPTZ | |

---

## 四、audit_runs（审核运行主表）

一次 `python -m syllabus_auditor.cli run-batch` 对应一行。

### 4.1 DDL

```sql
CREATE TYPE audit_run_status AS ENUM (
    'created', 'running', 'completed', 'failed', 'cancelled'
);

CREATE TABLE IF NOT EXISTS public.audit_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_name        TEXT NOT NULL,
    import_term     TEXT,
    auditors        JSONB NOT NULL DEFAULT '[]'::jsonb,
    config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          audit_run_status NOT NULL DEFAULT 'created',
    course_total    INTEGER NOT NULL DEFAULT 0,
    course_done     INTEGER NOT NULL DEFAULT 0,
    summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.audit_runs IS '批量审核运行主表，一次 run-batch 一行';
COMMENT ON COLUMN public.audit_runs.config_snapshot IS '含 audit_modes、LLM、检索器等可复现配置';
COMMENT ON COLUMN public.audit_runs.summary IS '运行级汇总：pass_count、fail_count 等';

CREATE INDEX IF NOT EXISTS idx_audit_runs_status ON public.audit_runs (status);
CREATE INDEX IF NOT EXISTS idx_audit_runs_import_term ON public.audit_runs (import_term);
CREATE INDEX IF NOT EXISTS idx_audit_runs_started_at ON public.audit_runs (started_at DESC);
```

### 4.2 列说明

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `id` | 运行 ID | BIGSERIAL | CLI 输出 `run_id` |
| `run_name` | 运行名称 | TEXT | 如 `2026-spring_batch_20260623` |
| `import_term` | 导入学期 | TEXT | 对应 `courses.import_term` |
| `auditors` | 启用维度列表 | JSONB | 如 `["jcxx_yz","mb_yq"]` |
| `config_snapshot` | 配置快照 | JSONB | 含 `audit_modes`，见第二节 |
| `status` | 运行状态 | audit_run_status | |
| `course_total` | 计划审核门数 | INTEGER | |
| `course_done` | 已完成门数 | INTEGER | |
| `summary` | 运行汇总 | JSONB | 见 4.3 |
| `error_message` | 错误信息 | TEXT | 整批失败时 |
| `started_at` | 开始时间 | TIMESTAMPTZ | |
| `completed_at` | 结束时间 | TIMESTAMPTZ | |
| `created_at` | 创建时间 | TIMESTAMPTZ | |
| `updated_at` | 更新时间 | TIMESTAMPTZ | |

### 4.3 summary 示例

```json
{
  "pass_count": 120,
  "fail_count": 15,
  "partial_count": 8,
  "manual_review_count": 3,
  "skipped_count": 2,
  "error_count": 1
}
```

---

## 五、audit_results（课程级结果）

一次 run 中，一门课一行。`(run_id, kcbh)` 唯一。

### 5.1 DDL

```sql
CREATE TYPE audit_overall_status AS ENUM (
    'pass', 'fail', 'partial', 'manual_review', 'skipped', 'error'
);

CREATE TABLE IF NOT EXISTS public.audit_results (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES public.audit_runs (id) ON DELETE CASCADE,
    kcbh            TEXT NOT NULL,
    extraction_id   BIGINT REFERENCES public.syllabus_extractions (id),
    overall_status  audit_overall_status NOT NULL,
    overall_score   NUMERIC(5, 2),
    finding_count   INTEGER NOT NULL DEFAULT 0,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audit_results_run_kcbh_unique UNIQUE (run_id, kcbh)
);

COMMENT ON TABLE public.audit_results IS '单次运行中每门课的总体审核结论';
COMMENT ON COLUMN public.audit_results.extraction_id IS '本次比对使用的 PDF 抽取记录';

CREATE INDEX IF NOT EXISTS idx_audit_results_run_id ON public.audit_results (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_results_kcbh ON public.audit_results (kcbh);
CREATE INDEX IF NOT EXISTS idx_audit_results_overall_status ON public.audit_results (overall_status);
CREATE INDEX IF NOT EXISTS idx_audit_results_extraction_id ON public.audit_results (extraction_id);
```

### 5.2 列说明

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `id` | 主键 | BIGSERIAL | |
| `run_id` | 所属运行 | BIGINT FK | |
| `kcbh` | 课程编号 | TEXT | 关联 `courses.kcbh` |
| `extraction_id` | 抽取记录 ID | BIGINT FK | 关联 `syllabus_extractions.id` |
| `overall_status` | 总体状态 | audit_overall_status | |
| `overall_score` | 综合分 | NUMERIC(5,2) | 可选 |
| `finding_count` | 维度条数 | INTEGER | |
| `fail_count` | 不通过维度数 | INTEGER | |
| `summary` | 课程级摘要 | JSONB | 一句话结论、需人工项等 |
| `error_message` | 单课错误 | TEXT | 该课处理失败时 |
| `created_at` | 创建时间 | TIMESTAMPTZ | |

### 5.3 数据关联

| 数据源 | 关联方式 |
|--------|----------|
| 课程库基准 | `courses.kcbh` + `audit_runs.import_term` |
| PDF 抽取 | `syllabus_extractions.id`（通常取该课最新抽取） |

**不在此表复制** `payload` / `jcxx`，仅保存结论与指针。

---

## 六、audit_findings（维度级明细）

一门课每个审核维度一行（或一个 auditor 一行）。

### 6.1 DDL

```sql
CREATE TYPE audit_finding_status AS ENUM (
    'pass', 'fail', 'warning', 'manual_review', 'error', 'skipped'
);

CREATE TYPE audit_judge_type AS ENUM (
    'rule', 'direct_llm', 'rag_llm'
);

CREATE TABLE IF NOT EXISTS public.audit_findings (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES public.audit_runs (id) ON DELETE CASCADE,
    result_id   BIGINT NOT NULL REFERENCES public.audit_results (id) ON DELETE CASCADE,
    kcbh        TEXT NOT NULL,
    wd          TEXT NOT NULL,
    pdfs        audit_judge_type NOT NULL,
    status      audit_finding_status NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    evidence    JSONB NOT NULL DEFAULT '{}'::jsonb,
    rule_ref    JSONB NOT NULL DEFAULT '{}'::jsonb,
    suggestion  TEXT NOT NULL DEFAULT '',
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audit_findings_result_wd_unique UNIQUE (result_id, wd)
);

COMMENT ON TABLE public.audit_findings IS '单门课单维度的审核结论';
COMMENT ON COLUMN public.audit_findings.wd IS '审核维度码';
COMMENT ON COLUMN public.audit_findings.pdfs IS '判定方式：rule / direct_llm / rag_llm';
COMMENT ON COLUMN public.audit_findings.evidence IS '证据 JSON，结构随 pdfs 变化';

CREATE INDEX IF NOT EXISTS idx_audit_findings_run_id ON public.audit_findings (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_result_id ON public.audit_findings (result_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_kcbh ON public.audit_findings (kcbh);
CREATE INDEX IF NOT EXISTS idx_audit_findings_wd ON public.audit_findings (wd);
CREATE INDEX IF NOT EXISTS idx_audit_findings_status ON public.audit_findings (status);
CREATE INDEX IF NOT EXISTS idx_audit_findings_pdfs ON public.audit_findings (pdfs);
```

### 6.2 列说明

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `id` | 主键 | BIGSERIAL | |
| `run_id` | 所属运行 | BIGINT FK | 冗余，便于按 run 查 |
| `result_id` | 所属课程结果 | BIGINT FK | |
| `kcbh` | 课程编号 | TEXT | 冗余 |
| `wd` | 维度码 | TEXT | 见 6.4 |
| `pdfs` | 判定方式 | audit_judge_type | rule / direct_llm / rag_llm |
| `status` | 维度状态 | audit_finding_status | |
| `message` | 简短结论 | TEXT | |
| `evidence` | 证据 | JSONB | 见 6.3 |
| `rule_ref` | 规则引用 | JSONB | 细则文件、chunk_id 列表等 |
| `suggestion` | 修改建议 | TEXT | |
| `details` | 结构化明细 | JSONB | 字段 diff、子项得分等 |
| `created_at` | 创建时间 | TIMESTAMPTZ | |

### 6.3 evidence 结构（按 pdfs 区分）

**rule**

```json
{
  "diffs": [
    { "field": "zongxs", "释义": "总学时", "lib": "57", "pdf": "56" }
  ]
}
```

**direct_llm**

```json
{
  "input_sections": ["kcmb", "jxnr", "jxap"],
  "rule_source": "file:教学目标细则.txt",
  "chunk_ids": [12, 13, 14],
  "llm_summary": "教学目标基本符合要求，但能力目标描述不够具体"
}
```

**rag_llm**

```json
{
  "retrieved_chunk_ids": [101, 102, 105],
  "retriever": "bm25",
  "top_k": 5,
  "llm_summary": "思政元素融入不充分"
}
```

### 6.4 维度码 wd（规划占位）

| wd | 释义 | 建议默认 type |
|----|------|---------------|
| `jcxx_yz` | 基础信息与课程库一致 | `rule` |
| `mb_yq` | 教学目标/内容/方式符合要求 | `direct_llm` 或 `rag_llm` |
| `ys_wz` | 信息要素完整 | `rule` |
| `xs_pp` | 学时/周次匹配 | `rule` |
| `sz_yr` | 思政元素融入 | `direct_llm` 或 `rag_llm` |

业务明确后在 `auditors/registry.py` 注册，wd 与代码保持一致。

---

## 七、audit_artifacts（审核产物）

体积较大或调试用的内容，与 findings 分离。**RAG 特有数据仅作为一类 artifact 存在。**

### 7.1 DDL

```sql
CREATE TABLE IF NOT EXISTS public.audit_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES public.audit_runs (id) ON DELETE CASCADE,
    result_id       BIGINT REFERENCES public.audit_results (id) ON DELETE CASCADE,
    finding_id      BIGINT REFERENCES public.audit_findings (id) ON DELETE CASCADE,
    kcbh            TEXT,
    artifact_type   TEXT NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.audit_artifacts IS '审核调试产物：prompt、LLM 输出、检索记录等';

CREATE INDEX IF NOT EXISTS idx_audit_artifacts_run_id ON public.audit_artifacts (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_artifacts_finding_id ON public.audit_artifacts (finding_id);
CREATE INDEX IF NOT EXISTS idx_audit_artifacts_type ON public.audit_artifacts (artifact_type);
```

### 7.2 artifact_type 说明

| artifact_type | 释义 | 何时写入 |
|---------------|------|----------|
| `input_context` | 送入 LLM 的维度上下文 | **direct_llm** |
| `rule_pack` | 本维度使用的规则全文或引用 | **direct_llm** |
| `prompt` | 完整 system + user prompt | direct_llm / rag_llm |
| `llm_response` | LLM 原始输出 | direct_llm / rag_llm |
| `retrieval` | 检索结果（chunk、分数） | **仅 rag_llm** |
| `field_diff` | 规则比对明细 | **rule** |

### 7.3 同一 finding 的多条 artifact 示例

**direct_llm（mb_yq 维度）**

```text
finding_id = 1002
  ├─ input_context   payload: { "kcmb": "...", "sections": [...] }
  ├─ rule_pack       payload: { "source": "教学目标细则.txt", "content": "..." }
  ├─ prompt          payload: { "system": "...", "user": "..." }
  └─ llm_response    payload: { "raw": "...", "parsed": { ... } }
```

**rag_llm（sz_yr 维度）**

```text
finding_id = 1005
  ├─ retrieval       payload: { "chunks": [{ "id": 101, "score": 0.92, "content": "..." }] }
  ├─ prompt          payload: { ... }
  └─ llm_response    payload: { ... }
```

**rule（jcxx_yz 维度）**

```text
finding_id = 1001
  └─ field_diff      payload: { "diffs": [ ... ] }
```

---

## 八、运行生命周期

```text
1. INSERT audit_runs (status=running, config_snapshot=…)
2. FOR each kcbh in batch:
     a. 读取 courses + syllabus_extractions（最新或指定 extraction_id）
     b. INSERT audit_results
     c. FOR each wd in auditors:
          - 按 config_snapshot.audit_modes[wd].type 选择路径
          - rule        → findings + artifact(field_diff)
          - direct_llm  → findings + artifacts(input_context, rule_pack, prompt, llm_response)
          - rag_llm     → findings + artifacts(retrieval, prompt, llm_response)
     d. UPDATE audit_results（overall_status, summary, counts）
3. UPDATE audit_runs（status=completed, summary=聚合统计）
```

单课失败：`audit_results.overall_status = error`，其余课程继续；整批失败：`audit_runs.status = failed`。

---

## 九、常用 SQL 示例

### 9.1 创建一次运行

```sql
INSERT INTO public.audit_runs (
    run_name, import_term, auditors, config_snapshot, status, course_total
) VALUES (
    '2026-spring_batch_20260623',
    '2026-spring',
    '["jcxx_yz", "mb_yq", "xs_pp"]'::jsonb,
    '{"audit_modes": {"jcxx_yz": {"type": "rule"}, "mb_yq": {"type": "direct_llm", "llm": "qwen_audit"}}}'::jsonb,
    'running',
    150
)
RETURNING id;
```

### 9.2 查询某次 run 不通过课程

```sql
SELECT r.kcbh, c.zwkcmc, r.overall_status, r.summary
FROM public.audit_results r
JOIN public.courses c ON c.kcbh = r.kcbh
WHERE r.run_id = 42
  AND r.overall_status IN ('fail', 'partial')
ORDER BY r.kcbh;
```

### 9.3 查询某课某维度结论与判定方式

```sql
SELECT wd, pdfs, status, message, evidence, suggestion
FROM public.audit_findings
WHERE run_id = 42 AND kcbh = '0202J92002';
```

### 9.4 查询 rag_llm 维度的检索 artifact

```sql
SELECT a.payload
FROM public.audit_artifacts a
JOIN public.audit_findings f ON f.id = a.finding_id
WHERE f.run_id = 42
  AND f.pdfs = 'rag_llm'
  AND a.artifact_type = 'retrieval';
```

### 9.5 按院系统计通过率

```sql
SELECT
    c.kkyx,
    COUNT(*) FILTER (WHERE r.overall_status = 'pass') AS pass_n,
    COUNT(*) AS total_n
FROM public.audit_results r
JOIN public.courses c ON c.kcbh = r.kcbh
WHERE r.run_id = 42
GROUP BY c.kkyx
ORDER BY pass_n DESC;
```

### 9.6 与 PDF 抽取、课程库 JOIN 复核

```sql
SELECT
    r.kcbh,
    r.overall_status,
    c.zongxs AS lib_zongxs,
    e.payload #>> '{jcxx,zongxs}' AS pdf_zongxs,
    f.wd,
    f.status AS wd_status,
    f.message
FROM public.audit_results r
JOIN public.courses c ON c.kcbh = r.kcbh
LEFT JOIN public.syllabus_extractions e ON e.id = r.extraction_id
LEFT JOIN public.audit_findings f ON f.result_id = r.id
WHERE r.run_id = 42 AND r.kcbh = '0202J92002';
```

---

## 十、与 git_rag/test 的对应

| git_rag/test | syllabus-auditor |
|--------------|------------------|
| `rag_runs` | `audit_runs` |
| `rag_run_queries` | `audit_results` |
| query metrics | `audit_findings` |
| `rag_run_retrievals` | `audit_artifacts`（type=`retrieval`，仅 rag_llm） |
| `rag_run_artifacts` | `audit_artifacts`（其他 type） |
| attack config in run | `config_snapshot.audit_modes` |

---

## 十一、全库表关系总览

| 表 | 角色 |
|----|------|
| `courses` | 课程库基准 |
| `syllabus_extractions` | PDF 抽取结果 |
| `reference_chunks` | 规则库（direct 全量 / rag 检索） |
| `audit_runs` | 审核批次 |
| `audit_results` | 每课总结果 |
| `audit_findings` | 每维度结论 |
| `audit_artifacts` | 可选调试产物 |

---

## 十二、实施建议

1. **第一期**：`audit_runs` + `audit_results` + `audit_findings` + `rule` / `direct_llm` 路径
2. **第二期**：`audit_artifacts` 完整写入；`reference_chunks` 导入细则
3. **第三期**：启用 `rag_llm`，加 `embedding` 索引与 `retrieval` artifact

---

*文档版本：audit_runs v1.0 · PostgreSQL · 支持 rule / direct_llm / rag_llm*
