"""分析 fusion 抽取链路实际表现。"""
import json
import sys
from collections import Counter, defaultdict

sys.path[:0] = ["src", "."]

from syllabus_auditor.core.db.connection import build_dsn
import psycopg

with psycopg.connect(build_dsn()) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM syllabus_extractions")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT meta->>'extractor', COUNT(*) FROM syllabus_extractions GROUP BY 1"
        )
        extractor_versions = cur.fetchall()
        cur.execute(
            """
            SELECT COALESCE(meta->'section_extraction'->'pymupdf'->>'status','missing'), COUNT(*)
            FROM syllabus_extractions GROUP BY 1
            """
        )
        pymupdf_status = cur.fetchall()

        sections = [
            "teaching_content",
            "course_schedule",
            "assessment_rows",
            "course_requirements",
        ]
        source_counts = {}
        score_stats = defaultdict(list)
        alt_switches = Counter()
        for sec in sections:
            cur.execute(
                f"""
                SELECT
                  COALESCE(meta->'section_extraction'->'{sec}'->>'selected_source','none') AS src,
                  (meta->'section_extraction'->'{sec}'->>'selected_score')::float AS score,
                  jsonb_array_length(COALESCE(meta->'section_extraction'->'{sec}'->'candidate_scores','[]'::jsonb)) AS cand_n
                FROM syllabus_extractions
                """
            )
            rows = cur.fetchall()
            source_counts[sec] = Counter(r[0] for r in rows)
            for src, score, cand_n in rows:
                if score is not None:
                    score_stats[sec].append(score)
                if cand_n and cand_n > 1 and src != "pdfplumber_table":
                    alt_switches[sec] += 1

        cur.execute(
            """
            SELECT w->>'reason', COUNT(*)
            FROM syllabus_extractions e,
                 jsonb_array_elements(e.meta->'extraction_warnings') w
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
        warnings = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*) FROM syllabus_extractions
            WHERE jsonb_path_exists(meta, '$.extraction_warnings[*] ? (@.reason == \"alternative_candidate_selected\")')
            """
        )
        alt_count = cur.fetchone()[0]

        # table vs text row counts in payload
        cur.execute(
            """
            SELECT
              AVG(jsonb_array_length(COALESCE(payload->'jxnr'->'tm','[]'::jsonb))) AS jxnr_rows,
              AVG(jsonb_array_length(COALESCE(payload->'jxap'->'tm','[]'::jsonb))) AS jxap_rows,
              AVG(jsonb_array_length(COALESCE(payload->'khfsb'->'tm','[]'::jsonb))) AS khfsb_rows,
              SUM(CASE WHEN COALESCE(payload->'jxap'->'tm','[]'::jsonb) = '[]'::jsonb THEN 1 ELSE 0 END) AS empty_jxap,
              SUM(CASE WHEN COALESCE(payload->'khfsb'->'tm','[]'::jsonb) = '[]'::jsonb THEN 1 ELSE 0 END) AS empty_khfsb,
              SUM(CASE WHEN COALESCE(payload->'jxnr'->'tm','[]'::jsonb) = '[]'::jsonb THEN 1 ELSE 0 END) AS empty_jxnr
            FROM syllabus_extractions
            """
        )
        payload_stats = cur.fetchone()

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN COALESCE(payload->'jxap'->'tm','[]'::jsonb) != '[]'::jsonb
                        AND EXISTS (
                          SELECT 1 FROM jsonb_array_elements(payload->'jxap'->'tm') row
                          WHERE COALESCE(row->>'szyqjxx','') = ''
                        ) THEN 1 ELSE 0 END) AS jxap_has_rows_missing_sz,
              SUM(CASE WHEN COALESCE(payload->'jxap'->'tm','[]'::jsonb) != '[]'::jsonb THEN 1 ELSE 0 END) AS jxap_has_rows
            FROM syllabus_extractions
            """
        )
        sz_gap = cur.fetchone()

out = {
    "total": total,
    "extractor_versions": extractor_versions,
    "pymupdf_status": pymupdf_status,
    "source_counts": {k: dict(v) for k, v in source_counts.items()},
    "avg_scores": {k: round(sum(v) / len(v), 2) if v else 0 for k, v in score_stats.items()},
    "alt_switches": dict(alt_switches),
    "alt_candidate_pdfs": alt_count,
    "warnings": warnings,
    "payload_stats": {
        "avg_jxnr_rows": float(payload_stats[0] or 0),
        "avg_jxap_rows": float(payload_stats[1] or 0),
        "avg_khfsb_rows": float(payload_stats[2] or 0),
        "empty_jxnr": int(payload_stats[3] or 0),
        "empty_jxap": int(payload_stats[4] or 0),
        "empty_khfsb": int(payload_stats[5] or 0),
    },
    "jxap_sz_gap": {"has_rows": int(sz_gap[1] or 0), "rows_missing_sz": int(sz_gap[0] or 0)},
}
print(json.dumps(out, ensure_ascii=False, indent=2))
