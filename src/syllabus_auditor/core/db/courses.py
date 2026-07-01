"""courses 表的 upsert 操作。"""

from __future__ import annotations

from typing import Any

import psycopg

from syllabus_auditor.core.db.connection import build_dsn

_UPSERT_COLUMNS = (
    "kcbh",
    "kkyx",
    "zwkcmc",
    "ywkcmc",
    "skyy",
    "yxwxyxk",
    "khfs",
    "kcxz",
    "kclb",
    "zxs",
    "skzs",
    "zongxs",
    "jxxs",
    "syxs",
    "sjxs",
    "qtxs",
    "zxxs",
    "kcxf",
    "zjjsxm",
    "qtkc",
    "sfsx",
    "shzt",
    "import_term",
    "source_file",
)

_SET_CLAUSE = ",\n    ".join(
    f"{col} = EXCLUDED.{col}" for col in _UPSERT_COLUMNS if col != "kcbh"
)


class CourseStore:
    def upsert_many(
        self,
        rows: list[dict[str, Any]],
        *,
        import_term: str | None,
        source_file: str,
    ) -> int:
        if not rows:
            return 0

        placeholders = ", ".join(["%s"] * len(_UPSERT_COLUMNS))
        sql = f"""
            INSERT INTO courses ({", ".join(_UPSERT_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT (kcbh) DO UPDATE SET
                {_SET_CLAUSE},
                imported_at = NOW()
        """

        values = [
            tuple(row.get(col) for col in _UPSERT_COLUMNS)
            for row in rows
        ]

        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, values)
            conn.commit()
        return len(rows)

    def count(self) -> int:
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM courses")
                row = cur.fetchone()
        return int(row[0])
