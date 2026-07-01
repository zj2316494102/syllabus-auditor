# courses 课程库表设计说明（PostgreSQL）

本文档定义**课程库**基准数据表 `courses`：数据来源于 Excel（如「2026年春季 课程方案审核情况汇总表」），作为 PDF 抽取结果的对照基准，供审核模块比对使用。

**字段命名**：列名采用**中文拼音首字母**缩写（与 `syllabus_extractions.payload.jcxx` 对齐处使用相同键名）；表格均含 **释义** 列。

---

## 一、表概述

| 项 | 说明 |
|----|------|
| 表名 | `public.courses` |
| 数据来源 | Excel 课程库导入 |
| 粒度 | 一行 = 一门课在当前批次/学期下的基准记录 |
| 主键 | `id`（自增）；业务唯一键 `kcbh`（课程编号） |
| 存储形态 | **关系型列**（非 JSONB），便于筛选、JOIN、与 PDF 字段逐项比对 |

---

## 二、字段键命名约定

与 `syllabus_extractions` 文档保持一致：

| 规则 | 示例 |
|------|------|
| 拼音首字母 | 课程编号 → `kcbh` |
| 冲突消歧 | 周学时 `zxs`，总学时 `zongxs` |
| 保留原文 | 学时、学分等以 `TEXT` 存储，保留 Excel 原文，数值校验在应用层 |

---

## 三、DDL：建表与索引

```sql
CREATE TABLE IF NOT EXISTS public.courses (
    id          BIGSERIAL PRIMARY KEY,

    -- 业务字段（课程库 Excel 列）
    kcbh        TEXT NOT NULL,
    kkyx        TEXT,
    zwkcmc      TEXT,
    ywkcmc      TEXT,
    skyy        TEXT,
    yxwxyxk     TEXT,
    khfs        TEXT,
    kcxz        TEXT,
    kclb        TEXT,
    zxs         TEXT,
    skzs        TEXT,
    zongxs      TEXT,
    jxxs        TEXT,
    syxs        TEXT,
    sjxs        TEXT,
    qtxs        TEXT,
    zxxs        TEXT,
    kcxf        TEXT,
    zjjsxm      TEXT,
    qtkc        TEXT,
    sfsx        TEXT,
    shzt        TEXT,

    -- 导入元数据
    import_term     TEXT,
    source_file     TEXT,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT courses_kcbh_unique UNIQUE (kcbh)
);

COMMENT ON TABLE public.courses IS '课程库基准数据，来源于 Excel 导入';
COMMENT ON COLUMN public.courses.kcbh IS '课程编号';
COMMENT ON COLUMN public.courses.import_term IS '导入学期标识，如 2026-spring';
COMMENT ON COLUMN public.courses.source_file IS '来源 Excel 文件名或路径';

CREATE INDEX IF NOT EXISTS idx_courses_kkyx ON public.courses (kkyx);
CREATE INDEX IF NOT EXISTS idx_courses_zwkcmc ON public.courses (zwkcmc);
CREATE INDEX IF NOT EXISTS idx_courses_shzt ON public.courses (shzt);
CREATE INDEX IF NOT EXISTS idx_courses_import_term ON public.courses (import_term);
```

### updated_at 触发器

与 `syllabus_extractions` 共用 `public.set_updated_at()` 函数（若尚未创建请先执行该函数 DDL）。

```sql
CREATE TRIGGER trg_courses_updated_at
    BEFORE UPDATE ON public.courses
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();
```

---

## 四、业务字段说明

### 4.1 基本信息与学时

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `kcbh` | 课程编号 | `TEXT NOT NULL` | 业务唯一键；关联 `syllabus_extractions.course_code` |
| `kkyx` | 开课（院）系 | `TEXT` | |
| `zwkcmc` | 中文课程名称 | `TEXT` | |
| `ywkcmc` | 英文课程名称 | `TEXT` | |
| `skyy` | 上课语言 | `TEXT` | PDF 侧同义字段为「授课语言」，比对时键名同为 `skyy` |
| `yxwxyxk` | 允许学院外选课 | `TEXT` | 如「是」「否」；PDF 侧字段名为「是否允许外学院选课」，键名 `sfyxwxyxk`，比对需归一化 |
| `khfs` | 考核方式 | `TEXT` | 课程库短文本；非 PDF `khfsb` 考核章节表 |
| `kcxz` | 课程性质 | `TEXT` | |
| `kclb` | 课程类别 | `TEXT` | |
| `zxs` | 周学时 | `TEXT` | |
| `skzs` | 上课周数 | `TEXT` | |
| `zongxs` | 总学时 | `TEXT` | |
| `jxxs` | 教学学时 | `TEXT` | |
| `syxs` | 实验学时 | `TEXT` | |
| `sjxs` | 实践学时 | `TEXT` | |
| `qtxs` | 其他学时 | `TEXT` | |
| `zxxs` | 自学学时 | `TEXT` | |
| `kcxf` | 学分 | `TEXT` | Excel 列名为「学分」；PDF `jcxx` 中为「课程学分」，键名同为 `kcxf` |

### 4.2 主讲教师

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `zjjsxm` | 主讲教师姓名 | `TEXT` | 课程库仅含姓名；PDF `jcxx` 另有 `jsgh`、`email`、`lxdh` |

### 4.3 课程库专有字段

Excel 中有、PDF 基本信息通常没有的列：

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `qtkc` | 其他课程 | `TEXT` | |
| `sfsx` | 是否生效 | `TEXT` | 如「是」「否」 |
| `shzt` | 审核状态 | `TEXT` | 如「通过」「待审」等，以 Excel 为准 |

### 4.4 导入元数据

| 列名 | 释义 | PostgreSQL 类型 | 说明 |
|------|------|-----------------|------|
| `import_term` | 导入学期 | `TEXT` | 如 `2026-spring`，区分多批次导入 |
| `source_file` | 来源文件 | `TEXT` | Excel 文件名或路径 |
| `imported_at` | 导入时间 | `TIMESTAMPTZ` | 本次导入写入时间 |
| `created_at` | 创建时间 | `TIMESTAMPTZ` | 行首次创建 |
| `updated_at` | 更新时间 | `TIMESTAMPTZ` | 触发器维护 |

---

## 五、与 syllabus_extractions 的对照关系

审核「课程基本信息是否与课程库一致」时，比对 **`courses` 列** 与 **`syllabus_extractions.payload.jcxx`**：

| courses 列 | 释义 | syllabus `jcxx` 键 | 释义 | 比对说明 |
|------------|------|-------------------|------|----------|
| `kcbh` | 课程编号 | `kcbh` | 课程编号 | 直接比对 |
| `kkyx` | 开课（院）系 | `kkyx` | 开课（院）系 | 直接比对 |
| `zwkcmc` | 中文课程名称 | `zwkcmc` | 中文课程名称 | 直接比对 |
| `ywkcmc` | 英文课程名称 | `ywkcmc` | 英文课程名称 | 直接比对 |
| `skyy` | 上课语言 | `skyy` | 授课语言 | 标签不同，键名相同 |
| `yxwxyxk` | 允许学院外选课 | `sfyxwxyxk` | 是否允许外学院选课 | **键名不同**，应用层映射后比对 |
| `khfs` | 考核方式 | `khfs` | 考核方式 | 直接比对 |
| `kcxz` | 课程性质 | `kcxz` | 课程性质 | 直接比对 |
| `kclb` | 课程类别 | `kclb` | 课程类别 | 直接比对 |
| `zxs` | 周学时 | `zxs` | 周学时 | 直接比对 |
| `skzs` | 上课周数 | `skzs` | 上课周数 | 直接比对 |
| `zongxs` | 总学时 | `zongxs` | 总学时 | 直接比对 |
| `jxxs` | 教学学时 | `jxxs` | 教学学时 | 直接比对 |
| `syxs` | 实验学时 | `syxs` | 实验学时 | 直接比对 |
| `sjxs` | 实践学时 | `sjxs` | 实践学时 | 直接比对 |
| `qtxs` | 其他学时 | `qtxs` | 其他学时 | 直接比对 |
| `zxxs` | 自学学时 | `zxxs` | 自学学时 | 直接比对 |
| `kcxf` | 学分 | `kcxf` | 课程学分 | 标签不同，键名相同 |
| `zjjsxm` | 主讲教师姓名 | `rkjsxm` | 任课教师姓名 | **键名不同**，应用层映射后比对 |
| — | — | `jsgh` | 教师工号 | 仅 PDF 有 |
| — | — | `email` | 邮箱 | 仅 PDF 有 |
| — | — | `lxdh` | 联系电话 | 仅 PDF 有 |
| `qtkc` | 其他课程 | — | — | 仅课程库有 |
| `sfsx` | 是否生效 | — | — | 仅课程库有 |
| `shzt` | 审核状态 | — | — | 仅课程库有 |

---

## 六、常用 SQL 示例

### 6.1 导入 upsert（按课程编号）

```sql
INSERT INTO public.courses (
    kcbh, kkyx, zwkcmc, ywkcmc, skyy, yxwxyxk, khfs,
    kcxz, kclb, zxs, skzs, zongxs, jxxs, syxs, sjxs, qtxs, zxxs,
    kcxf, zjjsxm, qtkc, sfsx, shzt, import_term, source_file
) VALUES (
    '0202J92002', '财税学院', '财税量化分析', 'Quantitative Analysis', '中文', '否', '课堂闭卷',
    '专业必修课', '学术学位硕士', '3', '19', '57', '57', '0', '0', '0', '0',
    '3', '张三', NULL, '是', '通过', '2026-spring', '2026年春季课程方案审核情况汇总表.xlsx'
)
ON CONFLICT (kcbh) DO UPDATE SET
    kkyx = EXCLUDED.kkyx,
    zwkcmc = EXCLUDED.zwkcmc,
    ywkcmc = EXCLUDED.ywkcmc,
    skyy = EXCLUDED.skyy,
    yxwxyxk = EXCLUDED.yxwxyxk,
    khfs = EXCLUDED.khfs,
    kcxz = EXCLUDED.kcxz,
    kclb = EXCLUDED.kclb,
    zxs = EXCLUDED.zxs,
    skzs = EXCLUDED.skzs,
    zongxs = EXCLUDED.zongxs,
    jxxs = EXCLUDED.jxxs,
    syxs = EXCLUDED.syxs,
    sjxs = EXCLUDED.sjxs,
    qtxs = EXCLUDED.qtxs,
    zxxs = EXCLUDED.zxxs,
    kcxf = EXCLUDED.kcxf,
    zjjsxm = EXCLUDED.zjjsxm,
    qtkc = EXCLUDED.qtkc,
    sfsx = EXCLUDED.sfsx,
    shzt = EXCLUDED.shzt,
    import_term = EXCLUDED.import_term,
    source_file = EXCLUDED.source_file,
    imported_at = NOW();
```

### 6.2 与 PDF 抽取结果 JOIN 比对

```sql
SELECT
    c.kcbh,
    c.zwkcmc                                            AS lib_name,
    e.payload #>> '{jcxx,zwkcmc}'                       AS pdf_name,
    c.zongxs                                            AS lib_hours,
    e.payload #>> '{jcxx,zongxs}'                       AS pdf_hours,
    c.zjjsxm                                            AS lib_teacher,
    e.payload #>> '{jcxx,rkjsxm}'                       AS pdf_teacher
FROM public.courses c
LEFT JOIN LATERAL (
    SELECT payload
    FROM public.syllabus_extractions
    WHERE course_code = c.kcbh
    ORDER BY created_at DESC
    LIMIT 1
) e ON TRUE
WHERE c.kcbh = '0202J92002';
```

### 6.3 按院系统计

```sql
SELECT kkyx, COUNT(*) AS course_count
FROM public.courses
WHERE import_term = '2026-spring'
GROUP BY kkyx
ORDER BY course_count DESC;
```

---

## 七、字段键速查表

| 列名 | 释义 |
|------|------|
| `kcbh` | 课程编号 |
| `kkyx` | 开课（院）系 |
| `zwkcmc` | 中文课程名称 |
| `ywkcmc` | 英文课程名称 |
| `skyy` | 上课语言 |
| `yxwxyxk` | 允许学院外选课 |
| `khfs` | 考核方式 |
| `kcxz` | 课程性质 |
| `kclb` | 课程类别 |
| `zxs` | 周学时 |
| `skzs` | 上课周数 |
| `zongxs` | 总学时 |
| `jxxs` | 教学学时 |
| `syxs` | 实验学时 |
| `sjxs` | 实践学时 |
| `qtxs` | 其他学时 |
| `zxxs` | 自学学时 |
| `kcxf` | 学分 |
| `zjjsxm` | 主讲教师姓名 |
| `qtkc` | 其他课程 |
| `sfsx` | 是否生效 |
| `shzt` | 审核状态 |

---

## 八、Excel 列名 → 数据库列名映射

导入 `application/prepare/course_library.py`（CLI：`syllabus-auditor prepare course-library`）时使用：

| Excel 列名（中文） | 数据库列名 |
|-------------------|------------|
| 课程编号 | `kcbh` |
| 开课（院）系 | `kkyx` |
| 中文课程名称 | `zwkcmc` |
| 英文课程名称 | `ywkcmc` |
| 上课语言 | `skyy` |
| 允许学院外选课 | `yxwxyxk` |
| 考核方式 | `khfs` |
| 课程性质 | `kcxz` |
| 课程类别 | `kclb` |
| 周学时 | `zxs` |
| 上课周数 | `skzs` |
| 总学时 | `zongxs` |
| 教学学时 | `jxxs` |
| 实验学时 | `syxs` |
| 实践学时 | `sjxs` |
| 其他学时 | `qtxs` |
| 自学学时 | `zxxs` |
| 学分 | `kcxf` |
| 主讲教师姓名 | `zjjsxm` |
| 其他课程 | `qtkc` |
| 是否生效 | `sfsx` |
| 审核状态 | `shzt` |

---

*文档版本：courses v1.0 · PostgreSQL · 拼音首字母列名*
