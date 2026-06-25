from __future__ import annotations

import json
from typing import Any

import psycopg

from syllabus_auditor.core.audit import (
    AuditRunSummary,
    AuditSubject,
    CourseMatch,
    SubjectAudit,
    build_subject_key,
    extract_course_name_from_source_path,
)
from syllabus_auditor.core.audit_labels import audit_wd_label
from syllabus_auditor.core.db.connection import build_dsn


CORE_AUDIT_DIMENSIONS = (
    audit_wd_label("kcjbxxsfykckyz"),
    audit_wd_label("jxnrsfyxspp"),
    audit_wd_label("jxapsfyzcpp"),
    audit_wd_label("jxmbnrfsfhyq"),
    audit_wd_label("szysfyxrghj"),
    audit_wd_label("xxyzwzfhmb"),
)


class AuditStore:
    def list_subjects(self, *, latest_only: bool = True) -> list[AuditSubject]:
        query = """
            SELECT id, course_code, source_path, payload, meta, extraction_status::text
            FROM syllabus_extractions
        """
        if latest_only:
            query = """
                SELECT DISTINCT ON (source_path)
                    id, course_code, source_path, payload, meta, extraction_status::text
                FROM syllabus_extractions
                ORDER BY source_path, created_at DESC, id DESC
            """
        else:
            query += " ORDER BY created_at DESC, id DESC"

        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()

        subjects: list[AuditSubject] = []
        for row in rows:
            extraction_id = int(row[0])
            course_code = str(row[1] or "")
            source_path = str(row[2] or "")
            subjects.append(
                AuditSubject(
                    extraction_id=extraction_id,
                    course_code=course_code,
                    source_path=source_path,
                    payload=_json_object(row[3]),
                    meta=_json_object(row[4]),
                    extraction_status=row[5],
                    subject_key=build_subject_key(
                        extraction_id=extraction_id,
                        course_code=course_code,
                        source_path=source_path,
                    ),
                )
            )
        return subjects

    def match_course(self, subject: AuditSubject) -> CourseMatch:
        jcxx = subject.payload.get("jcxx") if isinstance(subject.payload.get("jcxx"), dict) else {}
        kcbh = str(jcxx.get("kcbh") or subject.course_code or "").strip()
        if kcbh:
            row = self.get_course_by_kcbh(kcbh)
            if row:
                return CourseMatch(status="matched", method="matched_by_kcbh", query=kcbh, course_row=row)

        pdf_name = str(jcxx.get("zwkcmc") or "").strip()
        if pdf_name:
            match = self._match_course_by_name(pdf_name, method="matched_by_pdf_name")
            if match.status == "matched":
                return match
            if match.status == "ambiguous":
                return match

        source_name = extract_course_name_from_source_path(subject.source_path)
        if source_name:
            match = self._match_course_by_name(source_name, method="matched_by_source_path")
            if match.status == "matched":
                return match
            if match.status == "ambiguous":
                return match

        reasons: list[str] = []
        if not kcbh:
            reasons.append("课程编号为空，已尝试通过课程名称和文件路径匹配课程库")
        if pdf_name:
            reasons.append(f"PDF 中的课程名称未能唯一匹配课程库：{pdf_name}")
        if source_name:
            reasons.append(f"文件路径中的课程名称未能唯一匹配课程库：{source_name}")
        if not reasons:
            reasons.append("无法从 PDF 或文件路径中取得可用于匹配课程库的信息")
        return CourseMatch(status="not_found", method="not_found", query=source_name or pdf_name or kcbh, reasons=reasons)

    def get_course_by_kcbh(self, kcbh: str) -> dict[str, Any] | None:
        if not kcbh.strip():
            return None
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        kcbh, kkyx, zwkcmc, ywkcmc, skyy, yxwxyxk, khfs,
                        kcxz, kclb, zxs, skzs, zongxs, jxxs, syxs, sjxs,
                        qtxs, zxxs, kcxf, zjjsxm, qtkc, sfsx, shzt,
                        import_term, source_file
                    FROM courses
                    WHERE kcbh = %s
                    LIMIT 1
                    """,
                    (kcbh,),
                )
                row = cur.fetchone()
                columns = [desc.name for desc in cur.description] if cur.description else []
        if not row:
            return None
        return dict(zip(columns, row))

    def _match_course_by_name(self, name: str, *, method: str) -> CourseMatch:
        query = str(name or "").strip()
        if not query:
            return CourseMatch(status="not_found", method="not_found", query=query)
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        kcbh, kkyx, zwkcmc, ywkcmc, skyy, yxwxyxk, khfs,
                        kcxz, kclb, zxs, skzs, zongxs, jxxs, syxs, sjxs,
                        qtxs, zxxs, kcxf, zjjsxm, qtkc, sfsx, shzt,
                        import_term, source_file
                    FROM courses
                    WHERE zwkcmc = %s
                    ORDER BY kcbh
                    """,
                    (query,),
                )
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description] if cur.description else []
        candidates = [dict(zip(columns, row)) for row in rows]
        if len(candidates) == 1:
            return CourseMatch(status="matched", method=method, query=query, course_row=candidates[0], candidates=candidates)
        if len(candidates) > 1:
            return CourseMatch(
                status="ambiguous",
                method="ambiguous",
                query=query,
                candidates=candidates,
                reasons=[f"课程名称“{query}”匹配到多条课程库记录，需人工复核"],
            )
        return CourseMatch(
            status="not_found",
            method="not_found",
            query=query,
            reasons=[f"课程名称“{query}”未匹配到课程库记录"],
        )

    def create_run(
        self,
        *,
        run_name: str,
        import_term: str | None,
        auditors: list[str],
        config_snapshot: dict[str, Any],
        course_total: int,
    ) -> int:
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_runs (
                        run_name, import_term, auditors, config_snapshot,
                        status, course_total, course_done
                    ) VALUES (%s, %s, %s::jsonb, %s::jsonb, 'running', %s, 0)
                    RETURNING id
                    """,
                    (
                        run_name,
                        import_term,
                        json.dumps(auditors, ensure_ascii=False),
                        json.dumps(config_snapshot, ensure_ascii=False),
                        course_total,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row[0])

    def save_subject_audit(self, *, run_id: int, audit: SubjectAudit) -> int:
        subject = audit.subject
        dimension_findings = [
            finding
            for finding in audit.section_findings
            if audit_wd_label(finding.wd) in CORE_AUDIT_DIMENSIONS
        ]
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_results (
                        run_id, subject_key, kcbh, extraction_id, source_path,
                        overall_status, overall_score, finding_count,
                        fail_count, warning_count, summary, error_message
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s::audit_overall_status, %s, %s,
                        %s, %s, %s::jsonb, %s
                    )
                    RETURNING id
                    """,
                    (
                        run_id,
                        subject.subject_key,
                        subject.course_code,
                        subject.extraction_id,
                        subject.source_path,
                        audit.overall_status,
                        None,
                        len(dimension_findings),
                        audit.fail_count,
                        audit.warning_count,
                        json.dumps(audit.summary, ensure_ascii=False),
                        "",
                    ),
                )
                result_id = int(cur.fetchone()[0])

                cur.executemany(
                    """
                    INSERT INTO audit_field_findings (
                        run_id, result_id, kcbh, subject_key, section, field,
                        path, status, reason, message, expected, actual,
                        evidence, suggestion, llm_trace
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s::audit_finding_status, %s, %s, %s::jsonb, %s::jsonb,
                        %s::jsonb, %s, %s::jsonb
                    )
                    """,
                    [
                        (
                            run_id,
                            result_id,
                            subject.course_code,
                            subject.subject_key,
                            finding.section,
                            finding.field,
                            finding.path,
                            finding.status,
                            finding.reason,
                            finding.message,
                            _json_dump(finding.expected),
                            _json_dump(finding.actual),
                            _json_dump(finding.evidence),
                            finding.suggestion,
                            _json_dump(finding.llm_trace),
                        )
                        for finding in audit.field_findings
                    ],
                )

                cur.executemany(
                    """
                    INSERT INTO audit_findings (
                        run_id, result_id, kcbh, wd, pdfs, status, message,
                        evidence, rule_ref, suggestion, details, llm_trace
                    ) VALUES (
                        %s, %s, %s, %s, %s::audit_judge_type, %s::audit_finding_status, %s,
                        %s::jsonb, '{}'::jsonb, %s, %s::jsonb, %s::jsonb
                    )
                    """,
                    [
                        (
                            run_id,
                            result_id,
                            subject.course_code,
                            audit_wd_label(finding.wd),
                            finding.pdfs,
                            finding.status,
                            finding.message,
                            _json_dump(finding.evidence),
                            finding.suggestion,
                            _json_dump(finding.details),
                            _json_dump(finding.llm_trace),
                        )
                        for finding in dimension_findings
                    ],
                )
            conn.commit()
        return result_id

    def complete_run(self, summary: AuditRunSummary) -> None:
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                metrics = self._compute_run_metrics(cur, summary.run_id)
                self._save_run_metrics(cur, summary.run_id, metrics)
                cur.execute(
                    """
                    UPDATE audit_runs
                    SET status = 'completed',
                        course_done = %s,
                        summary = %s::jsonb,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        summary.total,
                        json.dumps(
                            {
                                "pass_count": summary.pass_count,
                                "fail_count": summary.fail_count,
                                "partial_count": summary.partial_count,
                                "error_count": summary.error_count,
                                "skipped_count": summary.skipped_count,
                                "metrics": metrics,
                            },
                            ensure_ascii=False,
                        ),
                        summary.run_id,
                    ),
                )
            conn.commit()

    def _compute_run_metrics(self, cur: Any, run_id: int) -> dict[str, Any]:
        total_courses = self._scalar(cur, "SELECT COUNT(*) FROM audit_results WHERE run_id = %s", (run_id,))
        dimension_count = len(CORE_AUDIT_DIMENSIONS)
        cur.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT ar.id
                FROM audit_results ar
                LEFT JOIN audit_findings af
                  ON af.result_id = ar.id
                 AND af.wd = ANY(%s)
                WHERE ar.run_id = %s
                GROUP BY ar.id
                HAVING COUNT(af.id) = %s
                   AND COUNT(*) FILTER (WHERE af.status = 'pass') = %s
            ) passed
            """,
            (list(CORE_AUDIT_DIMENSIONS), run_id, dimension_count, dimension_count),
        )
        all_dimensions_pass_count = int(cur.fetchone()[0] or 0)

        cur.execute(
            """
            SELECT wd,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'pass') AS pass_count,
                   COUNT(*) FILTER (WHERE status <> 'pass') AS fail_count
            FROM audit_findings
            WHERE run_id = %s
              AND wd = ANY(%s)
            GROUP BY wd
            """,
            (run_id, list(CORE_AUDIT_DIMENSIONS)),
        )
        dimension_rows = cur.fetchall()
        dimension_pass_rates = {}
        by_wd = {str(row[0]): row for row in dimension_rows}
        for wd in CORE_AUDIT_DIMENSIONS:
            row = by_wd.get(wd)
            total = int(row[1] or 0) if row else 0
            pass_count = int(row[2] or 0) if row else 0
            fail_count = int(row[3] or 0) if row else 0
            dimension_pass_rates[wd] = {
                "total": total,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "pass_rate": _rate(pass_count, total),
            }

        cur.execute(
            """
            SELECT reason, COUNT(*) AS count
            FROM audit_field_findings
            WHERE run_id = %s
              AND status <> 'pass'
              AND COALESCE(reason, '') <> ''
            GROUP BY reason
            ORDER BY count DESC, reason
            LIMIT 10
            """,
            (run_id,),
        )
        reason_top10 = [{"reason": str(row[0]), "count": int(row[1] or 0)} for row in cur.fetchall()]

        cur.execute(
            """
            SELECT section, field, path, reason, COUNT(*) AS count
            FROM audit_field_findings
            WHERE run_id = %s
              AND status <> 'pass'
              AND (
                    reason LIKE '%%为空%%'
                 OR reason LIKE '%%字段缺失%%'
                 OR reason LIKE '%%缺失%%'
              )
            GROUP BY section, field, path, reason
            ORDER BY count DESC, section, field, reason
            LIMIT 10
            """,
            (run_id,),
        )
        missing_field_top10 = [
            {
                "section": str(row[0]),
                "field": str(row[1]),
                "path": str(row[2]),
                "reason": str(row[3]),
                "count": int(row[4] or 0),
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT COUNT(DISTINCT result_id)
            FROM audit_field_findings
            WHERE run_id = %s
              AND (
                    reason LIKE '%%需人工复核%%'
                 OR message LIKE '%%需人工复核%%'
                 OR reason LIKE '%%无法定位课程库记录%%'
                 OR message LIKE '%%无法定位课程库记录%%'
              )
            """,
            (run_id,),
        )
        manual_review_course_count = int(cur.fetchone()[0] or 0)

        cur.execute(
            """
            SELECT COALESCE(call->>'status', '') AS status, COUNT(*) AS count
            FROM audit_findings af
            CROSS JOIN LATERAL jsonb_array_elements(COALESCE(af.llm_trace->'calls', '[]'::jsonb)) call
            WHERE af.run_id = %s
              AND COALESCE(call->>'status', '') IN ('parse_error', 'no_llm')
            GROUP BY COALESCE(call->>'status', '')
            """,
            (run_id,),
        )
        llm_status_counts = {str(row[0]): int(row[1] or 0) for row in cur.fetchall()}
        llm_exception_count = sum(llm_status_counts.values())

        return {
            "overall_pass_rate": {
                "total": total_courses,
                "pass_count": all_dimensions_pass_count,
                "fail_count": max(total_courses - all_dimensions_pass_count, 0),
                "pass_rate": _rate(all_dimensions_pass_count, total_courses),
                "dimension_count": dimension_count,
                "dimensions": list(CORE_AUDIT_DIMENSIONS),
            },
            "dimension_pass_rates": dimension_pass_rates,
            "reason_top10": reason_top10,
            "missing_field_top10": missing_field_top10,
            "manual_review_course_count": manual_review_course_count,
            "llm_exception_count": llm_exception_count,
            "llm_status_counts": llm_status_counts,
        }

    def _save_run_metrics(self, cur: Any, run_id: int, metrics: dict[str, Any]) -> None:
        rows = [(run_id, key, json.dumps(value, ensure_ascii=False)) for key, value in metrics.items()]
        cur.executemany(
            """
            INSERT INTO audit_run_metrics (run_id, metric_key, metric_value)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (run_id, metric_key)
            DO UPDATE SET
                metric_value = EXCLUDED.metric_value,
                updated_at = NOW()
            """,
            rows,
        )

    def _scalar(self, cur: Any, query: str, params: tuple[Any, ...]) -> int:
        cur.execute(query, params)
        return int(cur.fetchone()[0] or 0)

    def fail_run(self, *, run_id: int, error_message: str) -> None:
        with psycopg.connect(build_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE audit_runs
                    SET status = 'failed',
                        error_message = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (error_message, run_id),
                )
            conn.commit()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _json_dump(value: Any) -> str:
    if value is None:
        value = {}
    return json.dumps(value, ensure_ascii=False)


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)
