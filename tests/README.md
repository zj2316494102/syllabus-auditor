# tests

| 目录 | 用途 |
|------|------|
| `unit/` | 单元/回归测试，`pytest` 默认只跑这里 |
| `integration/` | 需本地 DB 与 `data_pdf/` 的诊断脚本，**不**参与主流程；手动运行 |

## 单元测试

```bash
pytest
# 或
pytest tests/unit
```

## 集成诊断（示例）

```bash
python tests/integration/field_missing_compare_50.py
python tests/integration/audit_mineru_raw_coverage.py --help
```

主流程请使用 CLI：`syllabus-auditor prepare` / `audit` / `report`。
