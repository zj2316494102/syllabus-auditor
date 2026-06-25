"""Initialize PostgreSQL schema for syllabus-auditor."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from syllabus_auditor.core.db.connection import build_dsn

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

EXPECTED_TABLES = frozenset(
    {
        "audit_artifacts",
        "audit_field_findings",
        "audit_findings",
        "audit_results",
        "audit_runs",
        "courses",
        "reference_chunks",
        "syllabus_extractions",
    }
)


def list_tables(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        return [row[0] for row in cur.fetchall()]


def init_database(*, schema_file: Path | None = None) -> list[str]:
    sql_path = schema_file or SCHEMA_FILE
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    sql = sql_path.read_text(encoding="utf-8")
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        return list_tables(conn)


def main() -> int:
    try:
        tables = init_database()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"Database initialization failed: {exc}", file=sys.stderr)
        return 1

    missing = EXPECTED_TABLES - set(tables)

    print("Database initialized successfully.")
    print("Tables in public schema:")
    for name in tables:
        mark = "OK" if name in EXPECTED_TABLES else "  "
        print(f"  [{mark}] {name}")

    if missing:
        print(f"Warning: missing expected tables: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1

    return 0
