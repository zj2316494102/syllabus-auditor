# syllabus-auditor

课程方案 PDF/MinerU 抽取、PostgreSQL 入库与批处理审核（CLI，无 HTTP API）。

## 环境

```bash
conda activate course   # Python >= 3.10
pip install -e ".[dev]"
cp .env.example .env    # 配置 DATABASE_URL、LLM_* 等
```

## 数据库

```bash
syllabus-auditor init-db
```

## 三条 Pipeline（固定语义）

| 命令 | 作用 |
|------|------|
| `syllabus-auditor prepare mineru` | MinerU MD → 抽取 → `syllabus_extractions` |
| `syllabus-auditor prepare courses` | pdfplumber 扫描 `data_pdf/` 入库 |
| `syllabus-auditor prepare course-library` | 课程库 Excel → `courses` |
| `syllabus-auditor audit run` | 按配置维度批审，写入 `audit_*` |
| `syllabus-auditor report quality` | 生成 `docs/data_quality_report.md` |

### 典型流程

```bash
syllabus-auditor prepare mineru
syllabus-auditor prepare course-library --term 2026-spring
syllabus-auditor audit run --limit 20
syllabus-auditor report quality
```

## 配置

| 文件 | 用途 |
|------|------|
| `project.yaml` | 全部可调配置：LLM profile、路径、阈值、正则、打分、审核文案等 |
| `src/syllabus_auditor/shared/config/schema.py` | 领域 schema：字段映射、章节标题、审核维度（跟代码绑死） |
| `.env` | 密钥与数据库连接 |

加载入口：`from syllabus_auditor.shared.config import load_project_config`

## 目录结构

```
src/syllabus_auditor/
├── application/
│   ├── prepare/     # mineru / pdf / course-library
│   ├── audit/       # 批审
│   └── report/      # 质量报告
├── core/            # 抽取、payload、DB、规则审核
├── auditors/        # 维度审核插件
├── shared/config/   # 配置
└── utils/           # 通用工具（含 source_verify）

tests/
├── unit/            # pytest 默认跑的单元测试
└── integration/     # 需 DB/本地数据的诊断脚本（手动运行，不参与主流程）
```

```bash
pytest tests/unit
ruff check src tests
```

## 路线图

- **Phase 0**：配置进包、registry 对齐、CLI 三条命令（当前）
- **Phase 1**：Pipeline 模块、payload schema 版本、golden 测试
- **Phase 2**：Alembic、结构化日志、CI、`audit_run_metrics`
- **Phase 3**：SLA 基准、备份演练、依赖扫描
