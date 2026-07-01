# 数据库迁移

当前基线由 `src/syllabus_auditor/core/db/schema.sql` 定义。`init-db` 仍执行该文件。

后续增量变更请在此目录添加版本化 SQL，例如：

```
migrations/002_add_foo_column.sql
```

Phase 2 可接入 Alembic；在此之前请手工记录每次 schema 变更。
