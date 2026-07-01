"""50 份 MinerU MD：入库字段缺失 vs MD 源文档章节内核对。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.db.connection import build_dsn, get_project_root  # noqa: E402
from syllabus_auditor.core.extractors.mineru import EXTRACTOR_NAME as MINERU_EXTRACTOR  # noqa: E402
from syllabus_auditor.utils.source_verify import verify_warning_in_md  # noqa: E402

MANIFEST = PROJECT_ROOT / "data_md" / "manifest" / "index.jsonl"
OUT_JSON = PROJECT_ROOT / "docs" / "diagnose" / "field_missing_50.json"
OUT_CSV = PROJECT_ROOT / "docs" / "diagnose" / "field_missing_50.csv"

FIELD_MISSING_REASONS = {"missing_field", "empty_section"}

REASON_CN = {
    "missing_field": "字段为空",
    "empty_section": "章节/表为空",
}

VERDICT_CN = {
    "source_missing": "MD源真缺",
    "extract_failure": "抽取误报",
    "uncertain": "无法判定",
}


def load_manifest() -> dict[str, str]:
    """source_pdf -> md 相对路径"""
    mapping: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success" and row.get("source_pdf") and row.get("md"):
            mapping[row["source_pdf"]] = row["md"]
    return mapping


def load_extractions(source_paths: list[str], extractor: str) -> list[dict]:
    sql = """
        SELECT DISTINCT ON (source_path)
            id, source_path, extraction_status::text, meta, extractor
        FROM syllabus_extractions
        WHERE source_path = ANY(%s) AND extractor = %s
        ORDER BY source_path, created_at DESC, id DESC
    """
    rows: list[dict] = []
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (source_paths, extractor))
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


def analyze_field_missing(extractions: list[dict], pdf_to_md: dict[str, str]) -> tuple[list[dict], dict]:
    project_root = get_project_root()
    grouped: dict[tuple[str, str, str], dict] = {}
    compare_counter: Counter = Counter()
    reason_counter: Counter = Counter()
    skipped_no_md = 0

    for item in extractions:
        md_rel = pdf_to_md.get(item["source_path"])
        if not md_rel:
            skipped_no_md += 1
            continue
        md_path = project_root / Path(md_rel.replace("\\", "/"))
        if not md_path.exists():
            skipped_no_md += 1
            continue

        for warning in item["warnings"]:
            reason = str(warning.get("reason") or "")
            if reason not in FIELD_MISSING_REASONS:
                continue
            label = str(warning.get("label") or warning.get("field") or "")
            section = str(warning.get("section") or "")
            reason_counter[reason] += 1

            verdict = verify_warning_in_md(warning, md_path)
            compare_counter[(reason, label, verdict)] += 1

            gkey = (reason, label, section)
            if gkey not in grouped:
                grouped[gkey] = {
                    "reason": reason,
                    "reason_cn": REASON_CN.get(reason, reason),
                    "label": label,
                    "section": section,
                    "system_count": 0,
                    "source_missing": 0,
                    "extract_failure": 0,
                    "uncertain": 0,
                }
            grouped[gkey]["system_count"] += 1
            grouped[gkey][verdict] += 1

    rows = sorted(grouped.values(), key=lambda x: (-x["system_count"], x["reason"], x["label"]))
    total_warnings = sum(reason_counter.values())
    summary = {
        "total_docs": len(extractions),
        "skipped_no_md": skipped_no_md,
        "verify_source": "mineru_md_file_section",
        "total_field_missing_warnings": total_warnings,
        "reason_breakdown": dict(reason_counter),
        "compare_totals": {
            "source_missing": sum(v for (_, _, t), v in compare_counter.items() if t == "source_missing"),
            "extract_failure": sum(v for (_, _, t), v in compare_counter.items() if t == "extract_failure"),
            "uncertain": sum(v for (_, _, t), v in compare_counter.items() if t == "uncertain"),
        },
    }
    if total_warnings:
        ct = summary["compare_totals"]
        denom = ct["source_missing"] + ct["extract_failure"] + ct["uncertain"]
        summary["false_missing_rate_pct"] = round(ct["extract_failure"] / denom * 100, 1)
        summary["true_missing_rate_pct"] = round(ct["source_missing"] / denom * 100, 1)
    else:
        summary["false_missing_rate_pct"] = 0.0
        summary["true_missing_rate_pct"] = 0.0
    return rows, summary


def main() -> int:
    pdf_to_md = load_manifest()
    paths = list(pdf_to_md.keys())
    mineru_ext = load_extractions(paths, MINERU_EXTRACTOR)
    rows, summary = analyze_field_missing(mineru_ext, pdf_to_md)

    result = {
        "scope": "50 MinerU-success MDs",
        "field_missing_reasons": sorted(FIELD_MISSING_REASONS),
        "verify_note": "核对依据为 MD 对应章节内容（与 mineru_md 抽取输入一致），非 PDF 全文关键字",
        "mineru_md": {"summary": summary, "rows": rows},
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_lines = [
        "extractor,reason,label,section,system_count,source_missing,extract_failure,uncertain,false_rate_pct"
    ]
    for row in rows:
        denom = row["system_count"] or 1
        false_rate = round(row["extract_failure"] / denom * 100, 1)
        csv_lines.append(
            f"mineru_md,{row['reason']},{json.dumps(row['label'], ensure_ascii=False)},{row['section']},"
            f"{row['system_count']},{row['source_missing']},{row['extract_failure']},{row['uncertain']},{false_rate}"
        )
    OUT_CSV.write_text("\n".join(csv_lines), encoding="utf-8-sig")

    print("\n=== MinerU MD 字段缺失 vs MD 源章节核对 ===")
    print(f"文档数: {summary['total_docs']} | 跳过(无MD): {summary['skipped_no_md']}")
    print(f"核对方式: {summary['verify_source']}")
    print(f"字段/章节缺失告警总数: {summary['total_field_missing_warnings']}")
    ct = summary["compare_totals"]
    print(
        f"MD 源真缺: {ct['source_missing']} ({summary['true_missing_rate_pct']}%) | "
        f"抽取误报: {ct['extract_failure']} ({summary['false_missing_rate_pct']}%) | "
        f"无法判定: {ct['uncertain']}"
    )
    print(f"\n{'原因':<12} {'字段/标签':<30} {'入库缺失':>8} {'MD真缺':>8} {'抽取误报':>8} {'误报率':>7}")
    print("-" * 85)
    for row in rows[:35]:
        denom = row["system_count"] or 1
        false_rate = row["extract_failure"] / denom * 100
        print(
            f"{row['reason_cn']:<12} {row['label']:<30} "
            f"{row['system_count']:>8} {row['source_missing']:>8} {row['extract_failure']:>8} {false_rate:>6.1f}%"
        )
    print(f"\nJSON: {OUT_JSON}")
    print(f"CSV:  {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
