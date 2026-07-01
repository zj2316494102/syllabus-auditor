"""快速 SQL 诊断：教学安排抽取源分布、行数统计及思政字段缺失情况。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from syllabus_auditor.core.db.connection import build_dsn
import psycopg

with psycopg.connect(build_dsn()) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              COALESCE(meta->'section_extraction'->'course_schedule'->>'selected_source','none') AS src,
              CASE WHEN COALESCE(payload->'jxap'->'tm','[]'::jsonb)='[]'::jsonb THEN 'empty' ELSE 'has_rows' END AS jxap,
              COUNT(*)
            FROM syllabus_extractions
            GROUP BY 1,2 ORDER BY 3 DESC
            """
        )
        print("schedule source vs jxap.tm:", cur.fetchall())

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN COALESCE(payload->'jxap'->'tm','[]'::jsonb) = '[]'::jsonb THEN 1 ELSE 0 END),
              SUM(CASE WHEN jsonb_array_length(COALESCE(payload->'jxap'->'tm','[]'::jsonb)) > 0 THEN 1 ELSE 0 END)
            FROM syllabus_extractions
            """
        )
        print("empty jxap / has rows:", cur.fetchall())

        cur.execute(
            """
            SELECT COUNT(*) FROM syllabus_extractions
            WHERE COALESCE(payload->'jxap'->>'apgs','') <> ''
            """
        )
        print("jxap.apgs non-empty:", cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM syllabus_extractions
            WHERE jsonb_array_length(COALESCE(payload->'jxap'->'tm','[]'::jsonb)) > 0
            """
        )
        print("jxap.tm has rows:", cur.fetchone()[0])

        cur.execute(
            """
            SELECT source_path,
                   meta->'section_extraction'->'course_schedule'->>'selected_source' AS src,
                   jsonb_array_length(COALESCE(payload->'jxap'->'tm','[]'::jsonb)) AS payload_rows,
                   LEFT(COALESCE(payload->'jxap'->>'apgs',''), 40) AS apgs
            FROM syllabus_extractions
            WHERE COALESCE(payload->'jxap'->'tm','[]'::jsonb) = '[]'::jsonb
            LIMIT 8
            """
        )
        print("empty jxap but table selected samples:")
        for row in cur.fetchall():
            print(" ", row)

        cur.execute(
            """
            SELECT COUNT(*) FROM syllabus_extractions e
            WHERE EXISTS (
              SELECT 1 FROM jsonb_array_elements(COALESCE(payload->'jxap'->'tm','[]'::jsonb)) row
              WHERE row ? 'kzzd'
            )
            """
        )
        print("jxap rows with kzzd:", cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM syllabus_extractions e
            WHERE EXISTS (
              SELECT 1 FROM jsonb_array_elements(COALESCE(payload->'jxap'->'tm','[]'::jsonb)) row
              WHERE COALESCE(row->>'szyqjxx','') = ''
                AND row ? 'kzzd'
            )
            """
        )
        print("jxap rows missing szyqjxx but have kzzd:", cur.fetchone()[0])
