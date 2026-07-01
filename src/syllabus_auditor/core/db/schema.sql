-- syllabus-auditor 初始化 DDL
-- 数据库：course（PostgreSQL）

BEGIN;

-- 1. 公共函数：updated_at 自动更新
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. 枚举类型
DO $$ BEGIN
    CREATE TYPE extraction_status AS ENUM ('success', 'partial', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_run_status AS ENUM ('created', 'running', 'completed', 'failed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_overall_status AS ENUM ('pass', 'fail', 'partial', 'manual_review', 'skipped', 'error');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_finding_status AS ENUM ('pass', 'fail', 'warning', 'manual_review', 'error', 'skipped');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_judge_type AS ENUM ('rule', 'direct_llm', 'rag_llm');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 3. courses 课程库
CREATE TABLE IF NOT EXISTS public.courses (
    id              BIGSERIAL PRIMARY KEY,
    kcbh            TEXT NOT NULL,
    kkyx            TEXT,
    zwkcmc          TEXT,
    ywkcmc          TEXT,
    skyy            TEXT,
    yxwxyxk         TEXT,
    khfs            TEXT,
    kcxz            TEXT,
    kclb            TEXT,
    zxs             TEXT,
    skzs            TEXT,
    zongxs          TEXT,
    jxxs            TEXT,
    syxs            TEXT,
    sjxs            TEXT,
    qtxs            TEXT,
    zxxs            TEXT,
    kcxf            TEXT,
    zjjsxm          TEXT,
    qtkc            TEXT,
    sfsx            TEXT,
    shzt            TEXT,
    import_term     TEXT,
    source_file     TEXT,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT courses_kcbh_unique UNIQUE (kcbh)
);

CREATE INDEX IF NOT EXISTS idx_courses_kkyx ON public.courses (kkyx);
CREATE INDEX IF NOT EXISTS idx_courses_zwkcmc ON public.courses (zwkcmc);
CREATE INDEX IF NOT EXISTS idx_courses_shzt ON public.courses (shzt);
CREATE INDEX IF NOT EXISTS idx_courses_import_term ON public.courses (import_term);

DROP TRIGGER IF EXISTS trg_courses_updated_at ON public.courses;
CREATE TRIGGER trg_courses_updated_at
    BEFORE UPDATE ON public.courses
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 4. syllabus_extractions PDF 抽取
CREATE TABLE IF NOT EXISTS public.syllabus_extractions (
    id                  BIGSERIAL PRIMARY KEY,
    course_code         TEXT NOT NULL,
    source_path         TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,
    extractor           TEXT,
    extraction_status   extraction_status,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT syllabus_extractions_payload_is_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT syllabus_extractions_meta_is_object CHECK (jsonb_typeof(meta) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_course_code ON public.syllabus_extractions (course_code);
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_course_created ON public.syllabus_extractions (course_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_payload_gin ON public.syllabus_extractions USING GIN (payload jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_meta_gin ON public.syllabus_extractions USING GIN (meta jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_cn_name ON public.syllabus_extractions ((payload #>> '{jcxx,zwkcmc}'));
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_department ON public.syllabus_extractions ((payload #>> '{jcxx,kkyx}'));
CREATE INDEX IF NOT EXISTS idx_syllabus_extractions_status ON public.syllabus_extractions (extraction_status) WHERE extraction_status IS NOT NULL;

DROP TRIGGER IF EXISTS trg_syllabus_extractions_updated_at ON public.syllabus_extractions;
CREATE TRIGGER trg_syllabus_extractions_updated_at
    BEFORE UPDATE ON public.syllabus_extractions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 5. reference_chunks 规则库（暂无 embedding，后续 RAG 再加）
CREATE TABLE IF NOT EXISTS public.reference_chunks (
    id          BIGSERIAL PRIMARY KEY,
    wd          TEXT,
    source      TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reference_chunks_wd ON public.reference_chunks (wd);
CREATE INDEX IF NOT EXISTS idx_reference_chunks_source ON public.reference_chunks (source);

-- 6. audit_runs
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

CREATE INDEX IF NOT EXISTS idx_audit_runs_status ON public.audit_runs (status);
CREATE INDEX IF NOT EXISTS idx_audit_runs_import_term ON public.audit_runs (import_term);
CREATE INDEX IF NOT EXISTS idx_audit_runs_started_at ON public.audit_runs (started_at DESC);

DROP TRIGGER IF EXISTS trg_audit_runs_updated_at ON public.audit_runs;
CREATE TRIGGER trg_audit_runs_updated_at
    BEFORE UPDATE ON public.audit_runs
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 7. audit_results
CREATE TABLE IF NOT EXISTS public.audit_results (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES public.audit_runs (id) ON DELETE CASCADE,
    subject_key     TEXT NOT NULL DEFAULT '',
    kcbh            TEXT NOT NULL,
    extraction_id   BIGINT REFERENCES public.syllabus_extractions (id),
    source_path     TEXT NOT NULL DEFAULT '',
    overall_status  audit_overall_status NOT NULL,
    overall_score   NUMERIC(5, 2),
    finding_count   INTEGER NOT NULL DEFAULT 0,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    warning_count   INTEGER NOT NULL DEFAULT 0,
    summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.audit_results ADD COLUMN IF NOT EXISTS subject_key TEXT NOT NULL DEFAULT '';
ALTER TABLE public.audit_results ADD COLUMN IF NOT EXISTS source_path TEXT NOT NULL DEFAULT '';
ALTER TABLE public.audit_results ADD COLUMN IF NOT EXISTS warning_count INTEGER NOT NULL DEFAULT 0;
DROP INDEX IF EXISTS public.idx_audit_results_jxnrsfyxspp;
ALTER TABLE public.audit_results DROP COLUMN IF EXISTS jxnrsfyxspp;
UPDATE public.audit_results
SET subject_key = CASE
    WHEN extraction_id IS NOT NULL THEN 'extraction:' || extraction_id::text
    WHEN COALESCE(source_path, '') <> '' THEN 'source:' || md5(source_path)
    ELSE 'audit_result:' || id::text
END
WHERE COALESCE(subject_key, '') = '';
ALTER TABLE public.audit_results DROP CONSTRAINT IF EXISTS audit_results_run_kcbh_unique;
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'audit_results_run_subject_key_unique'
          AND conrelid = 'public.audit_results'::regclass
    ) THEN
        ALTER TABLE public.audit_results
            ADD CONSTRAINT audit_results_run_subject_key_unique UNIQUE (run_id, subject_key);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_audit_results_run_id ON public.audit_results (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_results_subject_key ON public.audit_results (subject_key);
CREATE INDEX IF NOT EXISTS idx_audit_results_kcbh ON public.audit_results (kcbh);
CREATE INDEX IF NOT EXISTS idx_audit_results_overall_status ON public.audit_results (overall_status);
CREATE INDEX IF NOT EXISTS idx_audit_results_extraction_id ON public.audit_results (extraction_id);

-- 8. audit_findings
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
    llm_trace   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT audit_findings_result_wd_unique UNIQUE (result_id, wd)
);

ALTER TABLE public.audit_findings ADD COLUMN IF NOT EXISTS llm_trace JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_audit_findings_run_id ON public.audit_findings (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_result_id ON public.audit_findings (result_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_kcbh ON public.audit_findings (kcbh);
CREATE INDEX IF NOT EXISTS idx_audit_findings_wd ON public.audit_findings (wd);
CREATE INDEX IF NOT EXISTS idx_audit_findings_status ON public.audit_findings (status);
CREATE INDEX IF NOT EXISTS idx_audit_findings_pdfs ON public.audit_findings (pdfs);
CREATE INDEX IF NOT EXISTS idx_audit_findings_run_wd ON public.audit_findings (run_id, wd);
CREATE INDEX IF NOT EXISTS idx_audit_findings_run_wd_status ON public.audit_findings (run_id, wd, status);

-- 9. audit_field_findings
CREATE TABLE IF NOT EXISTS public.audit_field_findings (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES public.audit_runs (id) ON DELETE CASCADE,
    result_id   BIGINT NOT NULL REFERENCES public.audit_results (id) ON DELETE CASCADE,
    kcbh        TEXT NOT NULL DEFAULT '',
    subject_key TEXT NOT NULL DEFAULT '',
    section     TEXT NOT NULL,
    field       TEXT NOT NULL,
    path        TEXT NOT NULL,
    status      audit_finding_status NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',
    expected    JSONB NOT NULL DEFAULT '{}'::jsonb,
    actual      JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence    JSONB NOT NULL DEFAULT '{}'::jsonb,
    suggestion  TEXT NOT NULL DEFAULT '',
    llm_trace   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.audit_field_findings ADD COLUMN IF NOT EXISTS llm_trace JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_audit_field_findings_run_id ON public.audit_field_findings (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_field_findings_result_id ON public.audit_field_findings (result_id);
CREATE INDEX IF NOT EXISTS idx_audit_field_findings_kcbh ON public.audit_field_findings (kcbh);
CREATE INDEX IF NOT EXISTS idx_audit_field_findings_subject_key ON public.audit_field_findings (subject_key);
CREATE INDEX IF NOT EXISTS idx_audit_field_findings_section_field ON public.audit_field_findings (section, field);
CREATE INDEX IF NOT EXISTS idx_audit_field_findings_status ON public.audit_field_findings (status);
CREATE INDEX IF NOT EXISTS idx_audit_field_findings_reason ON public.audit_field_findings (reason);

-- 10. audit_artifacts
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

CREATE INDEX IF NOT EXISTS idx_audit_artifacts_run_id ON public.audit_artifacts (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_artifacts_finding_id ON public.audit_artifacts (finding_id);
CREATE INDEX IF NOT EXISTS idx_audit_artifacts_type ON public.audit_artifacts (artifact_type);

-- 11. audit_run_metrics
CREATE TABLE IF NOT EXISTS public.audit_run_metrics (
    id                   BIGSERIAL PRIMARY KEY,
    run_id               BIGINT NOT NULL REFERENCES public.audit_runs (id) ON DELETE CASCADE,
    metric_key           TEXT NOT NULL,
    metric_value         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT audit_run_metrics_run_key_unique UNIQUE (run_id, metric_key)
);

CREATE INDEX IF NOT EXISTS idx_audit_run_metrics_run_id ON public.audit_run_metrics (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_run_metrics_key ON public.audit_run_metrics (metric_key);

COMMIT;
