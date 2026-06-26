"""50 份 PDF：入库字段缺失 vs PDF 真实缺失（按字段/标签汇总）。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.db.connection import build_dsn, get_project_root  # noqa: E402
from syllabus_auditor.core.extractors.mineru_md import EXTRACTOR_NAME as MINERU_EXTRACTOR  # noqa: E402
from scripts.run_missing_analysis import (  # noqa: E402
    REASON_CN,
    read_pdf_text,
    verify_warning_in_pdf,
)

MANIFEST = PROJECT_ROOT / "data_change" / "manifest" / "index.jsonl"
OUT_JSON = PROJECT_ROOT / "data_change" / "analysis" / "field_missing_50.json"
OUT_CSV = PROJECT_ROOT / "data_change" / "analysis" / "field_missing_50.csv"

FIELD_MISSING_REASONS = {"missing_field", "empty_section"}


def load_success_paths() -> list[str]:
    paths: list[str] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success":
            paths.append(row["source_pdf"])
    return paths


def load_extractions(source_paths: list[str], extractor: str | None = None) -> list[dict]:
    sql = """
        SELECT DISTINCT ON (source_path)
            id, source_path, extraction_status::text, meta, extractor
        FROM syllabus_extractions
        WHERE source_path = ANY(%s)
    """
    params: list = [source_paths]
    if extractor:
        sql += " AND extractor = %s"
        params.append(extractor)
    sql += " ORDER BY source_path, created_at DESC, id DESC"

    rows: list[dict] = []
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            for eid, source_path, status, meta, ext in cur.fetchall():
                meta_obj = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                rows.append(
                    {
                        "id": eid,
                        "source_path": source_path,
                        "status": status,
                        "extractor": ext,
                        "warnings": list(meta_obj.get("extraction_warnings") or []),
                    }
                )
    return rows


def analyze_field_missing(extractions: list[dict]) -> tuple[list[dict], dict]:
    project_root = get_project_root()
    pdf_text_cache: dict[str, str] = {}
    grouped: dict[tuple[str, str, str], dict] = {}
    compare_counter: Counter = Counter()
    reason_counter: Counter = Counter()

    for item in extractions:
        pdf_path = project_root / item["source_path"]
        key_path = str(pdf_path)
        if key_path not in pdf_text_cache:
            try:
                pdf_text_cache[key_path] = read_pdf_text(pdf_path)
            except Exception:
                pdf_text_cache[key_path] = ""
        full_text = pdf_text_cache[key_path]

        for warning in item["warnings"]:
            reason = str(warning.get("reason") or "")
            if reason not in FIELD_MISSING_REASONS:
                continue
            label = str(warning.get("label") or warning.get("field") or "")
            section = str(warning.get("section") or "")
            reason_counter[reason] += 1

            verdict = verify_warning_in_pdf(warning, full_text)
            compare_counter[(reason, label, verdict)] += 1

            gkey = (reason, label, section)
            if gkey not in grouped:
                grouped[gkey] = {
                    "reason": reason,
                    "reason_cn": REASON_CN.get(reason, reason),
                    "label": label,
                    "section": section,
                    "system_count": 0,
                    "pdf_missing": 0,
                    "extract_failure": 0,
                    "uncertain": 0,
                }
            grouped[gkey]["system_count"] += 1
            grouped[gkey][verdict] += 1

    rows = sorted(grouped.values(), key=lambda x: (-x["system_count"], x["reason"], x["label"]))
    total_warnings = sum(reason_counter.values())
    summary = {
        "total_docs": len(extractions),
        "total_field_missing_warnings": total_warnings,
        "reason_breakdown": dict(reason_counter),
        "compare_totals": {
            "pdf_missing": sum(v for (_, _, t), v in compare_counter.items() if t == "pdf_missing"),
            "extract_failure": sum(v for (_, _, t), v in compare_counter.items() if t == "extract_failure"),
            "uncertain": sum(v for (_, _, t), v in compare_counter.items() if t == "uncertain"),
        },
    }
    if total_warnings:
        ct = summary["compare_totals"]
        denom = ct["pdf_missing"] + ct["extract_failure"] + ct["uncertain"]
        summary["false_missing_rate_pct"] = round(ct["extract_failure"] / denom * 100, 1)
        summary["true_missing_rate_pct"] = round(ct["pdf_missing"] / denom * 100, 1)
    else:
        summary["false_missing_rate_pct"] = 0.0
        summary["true_missing_rate_pct"] = 0.0
    return rows, summary


def main() -> int:
    paths = load_success_paths()
    mineru_ext = load_extractions(paths, extractor=MINERU_EXTRACTOR)
    pdfplumber_ext: list[dict] = []
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (source_path)
                    id, source_path, extraction_status::text, meta, extractor
                FROM syllabus_extractions
                WHERE source_path = ANY(%s)
                  AND extractor NOT IN ('mineru_md', 'mineru_middle', 'mineru_middle:0.1')
                ORDER BY source_path, created_at DESC, id DESC
                """,
                (paths,),
            )
            for eid, source_path, status, meta, ext in cur.fetchall():
                meta_obj = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                pdfplumber_ext.append(
                    {
                        "id": eid,
                        "source_path": source_path,
                        "status": status,
                        "extractor": ext,
                        "warnings": list(meta_obj.get("extraction_warnings") or []),
                    }
                )

    mineru_rows, mineru_summary = analyze_field_missing(mineru_ext)
    pdf_rows, pdf_summary = analyze_field_missing(pdfplumber_ext)

    result = {
        "scope": "50 MinerU-success PDFs",
        "field_missing_reasons": sorted(FIELD_MISSING_REASONS),
        "mineru_md": {"summary": mineru_summary, "rows": mineru_rows},
        "pdfplumber_baseline": {"summary": pdf_summary, "rows": pdf_rows},
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_lines = [
        "extractor,reason,label,section,system_count,pdf_missing,extract_failure,uncertain,false_rate_pct"
    ]
    for name, rows in (("mineru_md", mineru_rows), ("pdfplumber", pdf_rows)):
        for row in rows:
            denom = row["system_count"] or 1
            false_rate = round(row["extract_failure"] / denom * 100, 1)
            csv_lines.append(
                f"{name},{row['reason']},{json.dumps(row['label'], ensure_ascii=False)},{row['section']},"
                f"{row['system_count']},{row['pdf_missing']},{row['extract_failure']},{row['uncertain']},{false_rate}"
            )
    OUT_CSV.write_text("\n".join(csv_lines), encoding="utf-8-sig")

    def print_block(title: str, summary: dict, rows: list[dict]) -> None:
        print(f"\n=== {title} ===")
        print(f"文档数: {summary['total_docs']}")
        print(f"字段/章节缺失告警总数: {summary['total_field_missing_warnings']}")
        ct = summary["compare_totals"]
        print(
            f"PDF 真实缺失: {ct['pdf_missing']} ({summary['true_missing_rate_pct']}%) | "
            f"抽取误报: {ct['extract_failure']} ({summary['false_missing_rate_pct']}%) | "
            f"无法判定: {ct['uncertain']}"
        )
        print(f"\n{'原因':<12} {'字段/标签':<30} {'入库缺失':>8} {'PDF真缺':>8} {'抽取误报':>8} {'误报率':>7}")
        print("-" * 85)
        for row in rows[:35]:
            denom = row["system_count"] or 1
            false_rate = row["extract_failure"] / denom * 100
            print(
                f"{row['reason_cn']:<12} {row['label']:<30} "
                f"{row['system_count']:>8} {row['pdf_missing']:>8} {row['extract_failure']:>8} {false_rate:>6.1f}%"
            )

    print_block("MinerU MD 入库 (mineru_md)", mineru_summary, mineru_rows)
    print_block("PDFplumber 基线（同 50 份，仅对比用）", pdf_summary, pdf_rows)
    print(f"\nJSON: {OUT_JSON}")
    print(f"CSV:  {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
