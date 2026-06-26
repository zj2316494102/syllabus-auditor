"""PR-1 回归：重跑 200 PDF 并统计思政列 missing_field。"""
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

    sz_missing_warnings = 0
    jxap_has_rows = 0
    jxap_missing_sz_pdfs = 0
    total_jxap_rows = 0
    missing_sz_rows = 0
    status_counter: Counter = Counter()

    for pdf_path in pdfs:
        rel = relative_source_path(pdf_path.resolve(), project_root)
        raw = extractor.extract(pdf_path)
        payload = build_payload(raw)
        meta = build_meta(raw, rel)
        payload, meta = prepare_payload_and_meta_for_insert(payload, meta)
        status = judge_extraction_status(payload, meta)
        status_counter[status] += 1

        for w in meta.get("extraction_warnings") or []:
            if w.get("reason") == "missing_field" and w.get("label") == "思政元素的融入和预期教学成效":
                sz_missing_warnings += 1

        rows = (payload.get("jxap") or {}).get("tm") or []
        if rows:
            jxap_has_rows += 1
            row_missing = sum(1 for r in rows if not str(r.get("szyqjxx") or "").strip())
            total_jxap_rows += len(rows)
            missing_sz_rows += row_missing
            if row_missing:
                jxap_missing_sz_pdfs += 1

        store.insert(
            course_code=(payload.get("jcxx") or {}).get("kcbh") or "",
            source_path=rel,
            payload=payload,
            meta=meta,
            extractor=EXTRACTOR_NAME,
            extraction_status=status,
        )

    return {
        "processed": len(pdfs),
        "status": dict(status_counter),
        "sz_missing_field_warnings": sz_missing_warnings,
        "jxap_has_rows_pdfs": jxap_has_rows,
        "jxap_pdfs_with_any_missing_sz": jxap_missing_sz_pdfs,
        "total_jxap_rows": total_jxap_rows,
        "jxap_rows_missing_sz": missing_sz_rows,
        "baseline": {
            "sz_missing_field_warnings": 465,
            "jxap_pdfs_with_any_missing_sz": 75,
        },
    }


def main() -> None:
    print("清空 syllabus_extractions 并重跑 200 份 PDF ...")
    clear_extractions()
    result = run(LIMIT)
    print("\n=== PR-1 测试结果 ===")
    for key, value in result.items():
        if key == "baseline":
            print(f"\n基线 {key}:")
            for k, v in value.items():
                print(f"  {k}: {v}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
