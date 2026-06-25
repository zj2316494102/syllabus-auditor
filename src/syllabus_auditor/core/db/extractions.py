from __future__ import annotations

import json
from typing import Any

import psycopg

from syllabus_auditor.core.db.connection import build_dsn


class ExtractionStore:
    def insert(
        self,
        *,
        course_code: str,
        source_path: str,
        payload: dict[str, Any],
        meta: dict[str, Any],
        extractor: str,
        extraction_status: str,
    ) -> int:
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO syllabus_extractions (
                        course_code, source_path, payload, meta,
                        extractor, extraction_status
                    ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s::extraction_status)
                    RETURNING id
                    """,
                    (
                        course_code,
                        source_path,
                        json.dumps(payload, ensure_ascii=False),
                        json.dumps(meta, ensure_ascii=False),
                        extractor,
                        extraction_status,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row[0])

    def has_successful_extraction(self, source_path: str) -> bool:
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM syllabus_extractions
                    WHERE source_path = %s AND extraction_status = 'success'
                    LIMIT 1
                    """,
                    (source_path,),
                )
                return cur.fetchone() is not None
