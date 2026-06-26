"""PR-1+PR-2+PR-3 回归：200 PDF 关键指标。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.db.connection import build_dsn, get_project_root
from syllabus_auditor.core.db.extractions import ExtractionStore
from syllabus_auditor.core.extractors.pdfplumber import EXTRACTOR_NAME, PdfPlumberExtractor
from syllabus_auditor.core.meta_builder import build_meta, relative_source_path
from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert
from syllabus_auditor.core.status import judge_extraction_status
from syllabus_auditor.loaders.syllabus_pdf import list_pdf_files

LIMIT = 200
BASELINE = {
    "sz_missing_field_warnings": 465,
    "jxap_pdfs_with_any_missing_sz": 75,
    "continued_table_without_header": 447,
    "total_warnings_approx": 2903,
}
PR3 = {
    "total_warnings": 2221,
    "error_warnings": 2221,
    "success": 0,
    "sz_missing_field_warnings": 345,
    "alternative_candidate_selected": 33,
}


def clear_extractions() -> None:
    import psycopg

    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE syllabus_extractions RESTART IDENTITY CASCADE")
        conn.commit()


def run(limit: int) -> dict:
    project_root = get_project_root()
    pdfs = list_pdf_files(project_root / "data")[:limit]
    store = ExtractionStore()
    extractor = PdfPlumberExtractor()

    reason_counter: Counter = Counter()
    severity_counter: Counter = Counter()
    source_counter: Counter = Counter()
    assessment_scores: list[float] = []
    sz_missing_warnings = 0
    jxap_has_rows = 0
    jxap_missing_sz_pdfs = 0
    total_jxap_rows = 0
    missing_sz_rows = 0
    khfsb_rows_total = 0
    khfsb_empty_pdfs = 0
    status_counter: Counter = Counter()

    for pdf_path in pdfs:
        rel = relative_source_path(pdf_path.resolve(), project_root)
        raw = extractor.extract(pdf_path)
        payload = build_payload(raw)
        meta = build_meta(raw, rel)
        payload, meta = prepare_payload_and_meta_for_insert(payload, meta)
        status = judge_extraction_status(payload, meta)
        status_counter[status] += 1

        for section in ("teaching_content", "course_schedule", "assessment_rows", "course_requirements"):
            info = (meta.get("section_extraction") or {}).get(section) or {}
            src = str(info.get("selected_source") or "none")
            source_counter[f"{section}:{src}"] += 1
            if section == "assessment_rows":
                score = info.get("selected_score")
                if score is not None:
                    assessment_scores.append(float(score))

        for w in meta.get("extraction_warnings") or []:
            reason_counter[str(w.get("reason") or "")] += 1
            severity_counter[str(w.get("severity") or "error")] += 1
            if w.get("reason") == "missing_field" and w.get("label") == "思政元素的融入和预期教学成效":
                if str(w.get("severity") or "error") == "error":
                    sz_missing_warnings += 1

        rows = (payload.get("jxap") or {}).get("tm") or []
        if rows:
            jxap_has_rows += 1
            row_missing = sum(1 for r in rows if not str(r.get("szyqjxx") or "").strip())
            total_jxap_rows += len(rows)
            missing_sz_rows += row_missing
            if row_missing:
                jxap_missing_sz_pdfs += 1

        kh_rows = (payload.get("khfsb") or {}).get("tm") or []
        khfsb_rows_total += len(kh_rows)
        if not kh_rows:
            khfsb_empty_pdfs += 1

        store.insert(
            course_code=(payload.get("jcxx") or {}).get("kcbh") or "",
            source_path=rel,
            payload=payload,
            meta=meta,
            extractor=EXTRACTOR_NAME,
            extraction_status=status,
        )

    avg_assessment = round(sum(assessment_scores) / len(assessment_scores), 2) if assessment_scores else 0.0

    return {
        "processed": len(pdfs),
        "status": dict(status_counter),
        "total_warnings": sum(reason_counter.values()),
        "error_warnings": severity_counter.get("error", 0),
        "warn_warnings": severity_counter.get("warn", 0),
        "info_warnings": severity_counter.get("info", 0),
        "overview_used_instead_of_table": reason_counter.get("overview_used_instead_of_table", 0),
        "reason_top5": reason_counter.most_common(5),
        "continued_table_without_header": reason_counter.get("continued_table_without_header", 0),
        "alternative_candidate_selected": reason_counter.get("alternative_candidate_selected", 0),
        "sz_missing_field_warnings": sz_missing_warnings,
        "jxap_has_rows_pdfs": jxap_has_rows,
        "jxap_pdfs_with_any_missing_sz": jxap_missing_sz_pdfs,
        "total_jxap_rows": total_jxap_rows,
        "jxap_rows_missing_sz": missing_sz_rows,
        "jxap_rows_filled_sz": total_jxap_rows - missing_sz_rows,
        "avg_khfsb_rows": round(khfsb_rows_total / max(len(pdfs), 1), 2),
        "khfsb_empty_pdfs": khfsb_empty_pdfs,
        "avg_assessment_selected_score": avg_assessment,
        "fusion_source_top": source_counter.most_common(8),
        "baseline": BASELINE,
        "pr3": PR3,
    }


def main() -> None:
    print("清空 syllabus_extractions 并重跑 200 份 PDF ...")
    clear_extractions()
    result = run(LIMIT)
    print("\n=== PR-1 + PR-2 + PR-3 + PR-4 测试结果 ===")
    for key, value in result.items():
        if key in ("baseline", "pr3"):
            print(f"\n{key}:")
            for k, v in value.items():
                print(f"  {k}: {v}")
        elif key == "reason_top5":
            print(f"{key}:")
            for r, c in value:
                print(f"  {r}: {c}")
        elif key == "fusion_source_top":
            print(f"{key}:")
            for r, c in value:
                print(f"  {r}: {c}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
