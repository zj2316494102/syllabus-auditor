"""逐条诊断 extract_failure 误报：MD 有值但 payload 缺失。"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.db.connection import build_dsn, get_project_root
from syllabus_auditor.core.extractors.mineru import EXTRACTOR_NAME, MineruMdExtractor
from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.utils.source_verify import verify_warning_in_md

MANIFEST = PROJECT_ROOT / "data_md" / "manifest" / "index.jsonl"
OUT = PROJECT_ROOT / "docs" / "diagnose" / "extract_failure_detail.json"

FIELD_TO_PAYLOAD = {
    ("jxnr", "主题"): ("jxnr", "tm", "主题"),
    ("jxnr", "知识点"): ("jxnr", "zsd", "知识点"),
    ("jxnr", "学时"): ("jxnr", "xs", "学时"),
    ("jxap", "课程/周次"): ("jxap", "kc", "课程/周次"),
    ("jxap", "授课内容"): ("jxap", "sknr", "授课内容"),
    ("jxap", "授课方式"): ("jxap", "skfs", "授课方式"),
    ("jxap", "思政元素的融入和预期教学成效"): ("jxap", "sz", "思政元素的融入和预期教学成效"),
    ("jcxx", "课程编号"): ("jcxx", "kcbh", "课程编号"),
    ("kcmb", "知识目标"): ("kcmb", "zsm", "知识目标"),
}


def load_manifest() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") == "success" and row.get("source_pdf") and row.get("md"):
            mapping[row["source_pdf"]] = row["md"]
    return mapping


def load_extractions(source_paths: list[str]) -> list[dict]:
    sql = """
        SELECT DISTINCT ON (source_path)
            source_path, meta
        FROM syllabus_extractions
        WHERE source_path = ANY(%s) AND extractor = %s
        ORDER BY source_path, created_at DESC, id DESC
    """
    rows = []
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (source_paths, EXTRACTOR_NAME))
            for source_path, meta in cur.fetchall():
                meta_obj = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                rows.append({"source_path": source_path, "warnings": meta_obj.get("extraction_warnings") or []})
    return rows


def get_row_field(raw, section: str, field_key: str, row_idx: int | None = None):
    if section == "jxnr":
        rows = raw.teaching_content
    elif section == "jxap":
        rows = raw.course_schedule
    elif section == "jcxx":
        return getattr(raw, "basic_info", {}).get(field_key)
    elif section == "kcmb":
        return getattr(raw, "course_goals", {}).get(field_key)
    else:
        return None
    if row_idx is not None and 0 <= row_idx < len(rows):
        return rows[row_idx].get(field_key)
    return rows


def main() -> int:
    pdf_to_md = load_manifest()
    extractions = load_extractions(list(pdf_to_md.keys()))
    root = get_project_root()
    extractor = MineruMdExtractor()

    by_field: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for item in extractions:
        md_rel = pdf_to_md.get(item["source_path"])
        if not md_rel:
            continue
        md_path = root / Path(md_rel.replace("\\", "/"))
        stem = Path(item["source_path"]).stem

        raw = extractor.extract(md_path, source_pdf=Path(item["source_path"]))
        payload = build_payload(raw)

        for w in item["warnings"]:
            if w.get("reason") not in ("missing_field", "empty_section"):
                continue
            verdict = verify_warning_in_md(w, md_path)
            if verdict != "extract_failure":
                continue
            section = str(w.get("section") or "")
            label = str(w.get("label") or w.get("field") or "")
            row_idx = w.get("row_index")
            detail = {
                "doc": stem,
                "section": section,
                "label": label,
                "reason": w.get("reason"),
                "row_index": row_idx,
            }
            mapping = FIELD_TO_PAYLOAD.get((section, label))
            if mapping:
                sec, key, _ = mapping
                if w.get("reason") == "empty_section":
                    if sec == "jxnr":
                        detail["payload_count"] = len(raw.teaching_content)
                    elif sec == "jxap":
                        detail["payload_count"] = len(raw.course_schedule)
                elif row_idx is not None:
                    rows = raw.teaching_content if sec == "jxnr" else raw.course_schedule
                    if isinstance(row_idx, int) and 0 <= row_idx < len(rows):
                        detail["payload_row"] = {k: v for k, v in rows[row_idx].items() if v}
                elif sec == "jcxx":
                    detail["payload_value"] = getattr(raw, "basic_info", {}).get(key)
                elif sec == "kcmb":
                    detail["payload_value"] = getattr(raw, "course_goals", {}).get(key)
            by_field[(section, label)].append(detail)

    out = {
        "total_failures": sum(len(v) for v in by_field.values()),
        "by_field": {
            f"{sec}/{label}": {"count": len(items), "samples": items[:8]}
            for (sec, label), items in sorted(by_field.items(), key=lambda x: -len(x[1]))
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} total={out['total_failures']}")
    for key, block in out["by_field"].items():
        print(f"  {key}: {block['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
