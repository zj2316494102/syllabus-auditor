"""清空库、跑 N 个 PDF、统计缺失原因并与 PDF 原文对比。"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber
import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from config import load_extraction_config, load_project_config  # noqa: E402
from syllabus_auditor.core.db.connection import build_dsn, get_project_root  # noqa: E402
from syllabus_auditor.core.db.extractions import ExtractionStore  # noqa: E402
from syllabus_auditor.core.extractors.pdfplumber import PdfPlumberExtractor  # noqa: E402
from syllabus_auditor.core.meta_builder import build_meta, relative_source_path  # noqa: E402
from syllabus_auditor.core.payload_builder import build_payload  # noqa: E402
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert  # noqa: E402
from syllabus_auditor.core.status import judge_extraction_status  # noqa: E402
from syllabus_auditor.loaders.syllabus_pdf import list_pdf_files  # noqa: E402

LIMIT = 200
EMPTY_MARKERS = set(load_project_config().get("payload", {}).get("empty_markers", []))
SECTION_HINTS = load_project_config().get("audit", {}).get("xxyzwzfhmb_template", {}).get("section_hints", {})
SECTION_TITLES = load_extraction_config().get("section_titles", {})

FIELD_ALIASES: dict[str, list[str]] = {
    "课程编号": ["课程编号", "课 程 编 号"],
    "开课（院）系": ["开课（院）系", "开课院系", "开课(院)系"],
    "E-mail": ["E-mail", "Email", "电子邮箱", "邮箱"],
    "课程/周次": ["周次", "序号", "课程/周次"],
    "思政元素的融入和预期教学成效": ["思政元素的融入和预期教学成效", "思政元素", "预期教学成效"],
    "课程要求": ["课程要求", "学习要求", "课堂要求"],
    "教学内容条目": ["教学内容", "课程内容"],
    "教学安排条目": ["教学安排", "课程安排", "授课安排", "教学进度"],
    "考核方式条目": ["考核方式", "课程考核", "成绩评定"],
}

REASON_CN = {
    "missing_field": "字段为空",
    "empty_section": "章节/表为空",
    "missing_required_columns": "表缺必需列",
    "unknown_columns": "表含未知列",
    "continued_table_without_header": "续表无表头",
    "suspiciously_few_rows": "解析行数过少",
    "validated_text_fallback_used": "使用文本兜底",
    "alternative_candidate_selected": "选用备选抽取源",
    "pymupdf_extract_failed": "PyMuPDF 布局失败",
    "text_row_low_confidence": "文本行低置信度",
    "missing_teaching_method": "缺授课方式",
    "sanitized_control_chars": "清理控制字符",
}


def clear_database() -> None:
    sql = """
    TRUNCATE TABLE
      audit_artifacts,
      audit_field_findings,
      audit_findings,
      audit_results,
      audit_run_metrics,
      audit_runs,
      syllabus_extractions,
      courses,
      reference_chunks
    RESTART IDENTITY CASCADE;
    """
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def read_pdf_text(pdf_path: Path) -> str:
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
    return "\n".join(parts)


def _has_substantive(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return False
    return cleaned.lower() not in {m.lower() for m in EMPTY_MARKERS if m}


def _section_titles(section: str) -> list[str]:
    hints = list(SECTION_HINTS.get(section, []))
    for key, titles in SECTION_TITLES.items():
        if key in (section, f"{section}_rows"):
            hints.extend(titles)
    mapping = {
        "jxnr": SECTION_TITLES.get("teaching_content", []),
        "jxap": SECTION_TITLES.get("course_schedule", []),
        "khfsb": SECTION_TITLES.get("assessment", []),
        "kcyqb": SECTION_TITLES.get("course_requirements", []),
        "kcmb": SECTION_TITLES.get("course_goal", []),
    }
    hints.extend(mapping.get(section, []))
    return list(dict.fromkeys(str(x) for x in hints if x))


def _label_patterns(label: str) -> list[str]:
    aliases = FIELD_ALIASES.get(label, [])
    base = [label] if label else []
    return list(dict.fromkeys(base + aliases))


def _find_label_content(full_text: str, label: str) -> str | None:
    if not label:
        return None
    for pattern in _label_patterns(label):
        match = re.search(
            rf"{re.escape(pattern)}\s*[：:]\s*(.+?)(?:\n|$)",
            full_text,
            re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
        if pattern in full_text:
            return "__LABEL_PRESENT__"
    return None


def _section_has_content(full_text: str, section: str) -> bool:
    titles = _section_titles(section)
    if section and section not in titles:
        titles.insert(0, section)
    if not titles:
        return False
    for title in titles:
        idx = full_text.find(title)
        if idx < 0:
            continue
        chunk = full_text[idx : idx + 2500]
        body = chunk[len(title) :].strip()
        body = re.sub(r"^[：:\s]+", "", body)
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        substantive = [ln for ln in lines[:30] if _has_substantive(ln) and title not in ln]
        if len(substantive) >= 2:
            return True
        joined = "".join(substantive)
        if _has_substantive(joined) and len(joined) >= 8:
            return True
    return False


def verify_warning_in_pdf(warning: dict, full_text: str) -> str:
    """返回: pdf_missing | extract_failure | uncertain"""
    reason = str(warning.get("reason") or "")
    section = str(warning.get("section") or "")
    label = str(warning.get("label") or "")
    field = str(warning.get("field") or "")

    if reason in {
        "sanitized_control_chars",
        "alternative_candidate_selected",
        "pymupdf_extract_failed",
    }:
        return "uncertain"

    if reason in {
        "missing_required_columns",
        "unknown_columns",
        "continued_table_without_header",
        "suspiciously_few_rows",
        "text_row_low_confidence",
        "missing_teaching_method",
    }:
        if _section_has_content(full_text, section) or section in full_text:
            return "extract_failure"
        return "pdf_missing"

    if reason == "validated_text_fallback_used":
        # 兜底说明结构化表未解析成功，但 PDF 中通常有对应章节文本
        if _section_has_content(full_text, section) or (label and label in full_text):
            return "extract_failure"
        return "pdf_missing"

    if reason == "empty_section" or field == "tm":
        if _section_has_content(full_text, section):
            return "extract_failure"
        return "pdf_missing"

    content = _find_label_content(full_text, label)
    if content == "__LABEL_PRESENT__":
        return "extract_failure"
    if content and _has_substantive(content):
        return "extract_failure"
    if content is None and _section_has_content(full_text, section) and field == "tm":
        return "extract_failure"
    if content is None:
        return "pdf_missing"
    return "pdf_missing"


def process_pdfs(limit: int) -> dict:
    project_root = get_project_root()
    input_dir = project_root / "data"
    pdfs = list_pdf_files(input_dir)[:limit]
    store = ExtractionStore()
    extractor = PdfPlumberExtractor()
    stats = Counter()
    failures: list[dict] = []

    for pdf_path in pdfs:
        rel_path = relative_source_path(pdf_path.resolve(), project_root)
        try:
            raw = extractor.extract(pdf_path)
            payload = build_payload(raw)
            meta = build_meta(raw, rel_path)
            payload, meta = prepare_payload_and_meta_for_insert(payload, meta)
            status = judge_extraction_status(payload, meta)
            course_code = (payload.get("jcxx") or {}).get("kcbh") or ""
            store.insert(
                course_code=course_code,
                source_path=rel_path,
                payload=payload,
                meta=meta,
                extractor="pdfplumber",
                extraction_status=status,
            )
            stats[status] += 1
        except Exception as exc:
            stats["failed"] += 1
            failures.append({"source_path": rel_path, "error": f"{type(exc).__name__}: {exc}"})

    return {"processed": len(pdfs), "stats": dict(stats), "failures": failures}


def load_extractions() -> list[dict]:
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_path, extraction_status, meta
                FROM syllabus_extractions
                ORDER BY id
                """
            )
            rows = cur.fetchall()
    result = []
    for row in rows:
        meta = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        result.append(
            {
                "id": row[0],
                "source_path": row[1],
                "status": row[2],
                "warnings": list(meta.get("extraction_warnings") or []),
            }
        )
    return result


def analyze(extractions: list[dict]) -> tuple[list[dict], dict]:
    project_root = get_project_root()
    reason_counter: Counter = Counter()
    field_counter: Counter = Counter()
    compare_counter: Counter = Counter()
    pdf_text_cache: dict[str, str] = {}

    grouped: dict[tuple[str, str, str], dict] = {}

    for item in extractions:
        pdf_path = project_root / item["source_path"]
        if str(pdf_path) not in pdf_text_cache:
            try:
                pdf_text_cache[str(pdf_path)] = read_pdf_text(pdf_path)
            except Exception:
                pdf_text_cache[str(pdf_path)] = ""

        full_text = pdf_text_cache[str(pdf_path)]
        for warning in item["warnings"]:
            reason = str(warning.get("reason") or "unknown")
            label = str(warning.get("label") or warning.get("field") or "")
            section = str(warning.get("section") or "")
            reason_counter[reason] += 1
            field_counter[(reason, label)] += 1

            verdict = verify_warning_in_pdf(warning, full_text)
            compare_counter[(reason, label, verdict)] += 1

            key = (reason, label, section)
            if key not in grouped:
                grouped[key] = {
                    "reason": reason,
                    "reason_cn": REASON_CN.get(reason, reason),
                    "label": label,
                    "section": section,
                    "system_count": 0,
                    "pdf_missing": 0,
                    "extract_failure": 0,
                    "uncertain": 0,
                }
            grouped[key]["system_count"] += 1
            grouped[key][verdict] += 1

    rows = sorted(grouped.values(), key=lambda x: (-x["system_count"], x["reason"], x["label"]))
    summary = {
        "total_extractions": len(extractions),
        "total_warnings": sum(reason_counter.values()),
        "reason_top": reason_counter.most_common(),
        "status_breakdown": Counter(item["status"] for item in extractions),
        "compare_totals": {
            "pdf_missing": sum(v for (_, _, t), v in compare_counter.items() if t == "pdf_missing"),
            "extract_failure": sum(v for (_, _, t), v in compare_counter.items() if t == "extract_failure"),
            "uncertain": sum(v for (_, _, t), v in compare_counter.items() if t == "uncertain"),
        },
    }
    return rows, summary


def main() -> None:
    print("1/4 清空数据库...")
    clear_database()
    print("2/4 处理 PDF...")
    proc = process_pdfs(LIMIT)
    print(f"   已处理 {proc['processed']} 个 PDF，状态分布: {proc['stats']}")
    if proc["failures"]:
        print(f"   导入异常 {len(proc['failures'])} 个")

    print("3/4 读取库内 warnings 并核对 PDF 原文...")
    extractions = load_extractions()
    rows, summary = analyze(extractions)

    print("4/4 输出结果...")
    out_dir = PROJECT_ROOT / "data" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "missing_field_comparison.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "rows": rows, "process": proc}, fh, ensure_ascii=False, indent=2)

    print("\n=== 抽取状态 ===")
    for status, count in sorted(summary["status_breakdown"].items()):
        print(f"  {status}: {count}")

    print("\n=== 缺失原因 Top ===")
    for reason, count in summary["reason_top"][:15]:
        cn = REASON_CN.get(reason, reason)
        print(f"  {cn} ({reason}): {count}")

    print("\n=== PDF 核对总计 ===")
    ct = summary["compare_totals"]
    total = ct["pdf_missing"] + ct["extract_failure"] + ct["uncertain"]
    print(f"  系统告警总数: {summary['total_warnings']}")
    print(f"  PDF 确实缺失: {ct['pdf_missing']} ({ct['pdf_missing']/total*100:.1f}%)")
    print(f"  抽取失败(误报缺失): {ct['extract_failure']} ({ct['extract_failure']/total*100:.1f}%)")
    print(f"  无法判定: {ct['uncertain']} ({ct['uncertain']/total*100:.1f}%)")

    print("\n=== 对比表 (reason + 字段) ===")
    header = f"{'原因':<16} {'字段/标签':<28} {'系统计数':>8} {'PDF缺失':>8} {'抽取失败':>8} {'误报率':>8}"
    print(header)
    print("-" * len(header.encode('gbk', errors='ignore')))
    for row in rows[:40]:
        denom = row["system_count"] or 1
        false_rate = row["extract_failure"] / denom * 100
        print(
            f"{row['reason_cn']:<14} {row['label']:<26} "
            f"{row['system_count']:>8} {row['pdf_missing']:>8} {row['extract_failure']:>8} {false_rate:>7.1f}%"
        )

    print(f"\n完整 JSON: {json_path}")


if __name__ == "__main__":
    main()
