"""逐条诊断「抽取误报」(extract_failure) 的根因。"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.shared.config import load_project_config  # noqa: E402
from syllabus_auditor.utils.source_verify import (  # noqa: E402
    _jcxx_label_value_in_tables,
    _label_patterns,
    _md_section_html,
    _table_column_has_values,
    _table_has_column,
    verify_warning_in_md,
)
from syllabus_auditor.core.db.connection import build_dsn, get_project_root  # noqa: E402
from syllabus_auditor.core.extractors.mineru import MineruMdExtractor, repair_md_html  # noqa: E402
from syllabus_auditor.core.extractors.mineru import _JCXX_REGEX, _fill_jcxx_from_text  # noqa: E402
from syllabus_auditor.core.extractors.mineru import (  # noqa: E402
    normalize_mineru_tables,
    scan_row_label_pairs,
)
from syllabus_auditor.core.extractors.pdfplumber import (  # noqa: E402
    BASIC_PAIR_LABELS,
    clean_text,
    normalize_label,
    parse_pair_table,
    table_has_labels,
)
from syllabus_auditor.core.payload_builder import _clean_course_code, build_payload  # noqa: E402

MANIFEST = PROJECT_ROOT / "data_md" / "manifest" / "index.jsonl"
OUT_JSON = PROJECT_ROOT / "docs" / "diagnose" / "false_missing_root_causes.json"
OUT_CSV = PROJECT_ROOT / "docs" / "diagnose" / "false_missing_root_causes.csv"

FIELD_MISSING_REASONS = {"missing_field", "empty_section"}
MINERU_EXTRACTOR = "mineru_md"

LABEL_TO_JCXX_CN = {
    "课程编号": "课程编号",
    "开课（院）系": "开课（院）系",
    "中文课程名称": "中文课程名称",
    "英文课程名称": "英文课程名称",
    "任课教师姓名": "任课教师姓名",
}

LABEL_TO_ROW_FIELD = {
    "序号": ("jxnr", "xh"),
    "主题": ("jxnr", "zt"),
    "知识点": ("jxnr", "zsd"),
    "学时": ("jxnr", "xs"),
    "课程/周次": ("jxap", "zs"),
    "授课内容": ("jxap", "sknr"),
    "授课方式": ("jxap", "skfs"),
    "思政元素的融入和预期教学成效": ("jxap", "szyqjxx"),
    "考试形式": ("khfsb", "ksxs"),
    "考察内容": ("khfsb", "kcnr"),
    "考察方式": ("khfsb", "kcfs"),
    "占比": ("khfsb", "zb"),
}

SECTION_PROFILE_NAME = {
    "jxnr": "教学内容",
    "jxap": "教学安排",
    "khfsb": "考核方式",
}

ROOT_CAUSE_CN = {
    "label_value_glued_unsplit": "标签与值粘在同一单元格，repair_pair_table 未能拆出",
    "pair_table_odd_columns": "pair 表列数为奇数，标签后缺少值列",
    "pair_table_label_mismatch": "标签文本与 BASIC_PAIR_LABELS 不匹配（OCR/别名）",
    "no_pair_table_trigger": "无含「课程编号」触发表，基本信息 pair 解析未执行",
    "pair_table_parsed_empty_for_label": "pair 表已解析但该标签对应值为空",
    "course_code_validation_rejected": "cn_data 有课程编号但 _clean_course_code 格式校验未通过",
    "regex_fallback_pattern_gap": "MD 文本有该字段但 _JCXX_REGEX 正则未匹配",
    "section_table_not_detected": "章节表格未被识别（payload 无 tm 行）",
    "column_header_unmapped": "MD 表头存在但未映射到标准列名",
    "partial_rows_column_empty": "部分行该列为空",
    "all_parsed_rows_column_empty": "已解析行但该列全部为空（列映射或单元格丢失）",
    "missing_required_columns": "表头缺少必需列导致章节解析不完整",
    "empty_section_table_exists": "章节 tm 为空但 MD 有对应表格",
    "unknown_table_issue": "表格相关，未能进一步归类",
}


def load_manifest() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success" and row.get("source_pdf") and row.get("md"):
            mapping[row["source_pdf"]] = row
    return mapping


def load_extractions(source_paths: list[str]) -> list[dict]:
    sql = """
        SELECT DISTINCT ON (source_path)
            id, source_path, payload, meta
        FROM syllabus_extractions
        WHERE source_path = ANY(%s) AND extractor = %s
        ORDER BY source_path, created_at DESC, id DESC
    """
    rows: list[dict] = []
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (source_paths, MINERU_EXTRACTOR))
            for eid, source_path, payload, meta in cur.fetchall():
                payload_obj = payload if isinstance(payload, dict) else json.loads(payload or "{}")
                meta_obj = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                rows.append(
                    {
                        "id": eid,
                        "source_path": source_path,
                        "payload": payload_obj,
                        "warnings": list(meta_obj.get("extraction_warnings") or []),
                    }
                )
    return rows


def _cell_has_glued_label(cell: str | None, label: str) -> bool:
    if not cell:
        return False
    compact = normalize_label(cell)
    for pattern in _label_patterns(label):
        pn = normalize_label(pattern)
        if pn and pn in compact and len(compact) > len(pn) + 1:
            return True
    return False


def _find_unmapped_headers(section_html: str, label: str) -> list[str]:
    patterns = _label_patterns(label)
    headers: list[str] = []
    soup = BeautifulSoup(section_html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = rows[0].get_text(" ", strip=True)
        if any(p in header_text for p in patterns):
            continue
        for cell in rows[0].find_all(["td", "th"]):
            text = cell.get_text(" ", strip=True)
            if text and any(alias in text for alias in patterns):
                headers.append(text)
    return headers


def diagnose_jcxx(label: str, md_path: Path, payload: dict, raw) -> str:
    cn_label = LABEL_TO_JCXX_CN.get(label, label)
    md_text = md_path.read_text(encoding="utf-8")
    section_html = _md_section_html(md_text, "jcxx")

    jcxx = payload.get("jcxx") or {}
    py_key = load_project_config().get("payload", {}).get("jcxx_field_map", {}).get(cn_label)
    if py_key and jcxx.get(py_key):
        return "unknown_table_issue"

    cn_val = (raw.cn_data.get(cn_label) if raw else "") or ""
    if cn_label == "课程编号" and cn_val and not _clean_course_code(cn_val):
        return "course_code_validation_rejected"

    from syllabus_auditor.core.extractors.mineru import html_tables_from_md, repair_md_html

    tables = normalize_mineru_tables(html_tables_from_md(repair_md_html(md_text)))

    pair_tables = [t for t in tables if table_has_labels(t, ["课程编号"])]
    if not pair_tables:
        for t in tables:
            flat = "".join(normalize_label(c) for row in t for c in row if c)
            if normalize_label(cn_label) in flat:
                return "no_pair_table_trigger"
        if _jcxx_label_value_in_tables(section_html, label):
            return "no_pair_table_trigger"
        return "unknown_table_issue"

    for table in pair_tables:
        for row in table:
            for cell in row:
                if _cell_has_glued_label(cell, cn_label):
                    pairs = scan_row_label_pairs(row)
                    matched = [(k, v) for k, v in pairs if normalize_label(k) == normalize_label(cn_label)]
                    if not matched or not clean_text(matched[0][1]):
                        return "label_value_glued_unsplit"

    for table in pair_tables:
        for row in table:
            values = [clean_text(c) for c in row]
            for idx in range(0, len(values), 2):
                key = normalize_label(values[idx])
                if key == normalize_label(cn_label):
                    value = values[idx + 1] if idx + 1 < len(values) else ""
                    if not value:
                        if idx + 1 >= len(values):
                            return "pair_table_odd_columns"
                        return "pair_table_parsed_empty_for_label"

    trial: dict[str, str] = {}
    for table in pair_tables:
        parse_pair_table(trial, table)
    if cn_label == "课程编号" and trial.get(cn_label) and not _clean_course_code(trial[cn_label]):
        return "course_code_validation_rejected"
    if not trial.get(cn_label):
        if _jcxx_label_value_in_tables(section_html, label):
            for table in pair_tables:
                for row in table:
                    if any(_cell_has_glued_label(c, cn_label) for c in row):
                        return "label_value_glued_unsplit"
            return "pair_table_parsed_empty_for_label"
        return "unknown_table_issue"

    full_text = raw.full_text if raw else ""
    text_data = dict(trial)
    _fill_jcxx_from_text(text_data, full_text)
    if not text_data.get(cn_label) and _jcxx_label_value_in_tables(section_html, label):
        return "regex_fallback_pattern_gap"
    return "pair_table_parsed_empty_for_label"


def diagnose_table_field(
    section: str,
    label: str,
    warning: dict,
    md_path: Path,
    payload: dict,
    raw,
) -> str:
    md_text = md_path.read_text(encoding="utf-8")
    section_html = _md_section_html(md_text, section)
    mapping = LABEL_TO_ROW_FIELD.get(label)
    if not mapping:
        return "unknown_table_issue"
    sec_key, field_key = mapping
    rows = (payload.get(sec_key) or {}).get("tm") or []
    profile_name = SECTION_PROFILE_NAME.get(section, "")

    raw_warnings = list(getattr(raw, "extraction_warnings", None) or [])
    for w in raw_warnings:
        if w.get("reason") == "missing_required_columns" and profile_name in str(w.get("section", "")):
            return "missing_required_columns"
        if w.get("reason") == "unknown_columns" and profile_name in str(w.get("section", "")):
            unknown = w.get("fields") or []
            patterns = _label_patterns(label)
            if any(any(p in str(u) for p in patterns) for u in unknown):
                return "column_header_unmapped"
            unmapped = _find_unmapped_headers(section_html, label)
            if unmapped:
                return "column_header_unmapped"

    if not rows:
        if section_html.strip() and BeautifulSoup(section_html, "html.parser").find("table"):
            if _table_column_has_values(section_html, label) or _table_has_column(section_html, label):
                return "section_table_not_detected"
            return "empty_section_table_exists"
        return "section_table_not_detected"

    empty_count = sum(1 for row in rows if not str(row.get(field_key) or "").strip())
    if empty_count == 0:
        return "unknown_table_issue"
    if 0 < empty_count < len(rows):
        return "partial_rows_column_empty"
    if _table_column_has_values(section_html, label):
        return "all_parsed_rows_column_empty"
    return "unknown_table_issue"


def diagnose_one(warning: dict, md_path: Path, payload: dict, raw) -> str:
    section = str(warning.get("section") or "")
    label = str(warning.get("label") or "")
    reason = str(warning.get("reason") or "")

    if reason == "empty_section":
        md_text = md_path.read_text(encoding="utf-8")
        section_html = _md_section_html(md_text, section)
        if section_html.strip() and BeautifulSoup(section_html, "html.parser").find("table"):
            return "empty_section_table_exists"
        return "section_table_not_detected"

    if section == "jcxx" and label in LABEL_TO_JCXX_CN:
        return diagnose_jcxx(label, md_path, payload, raw)

    if section in SECTION_PROFILE_NAME:
        return diagnose_table_field(section, label, warning, md_path, payload, raw)

    return "unknown_table_issue"


def main() -> int:
    project_root = get_project_root()
    manifest = load_manifest()
    extractions = load_extractions(list(manifest.keys()))
    extractor = MineruMdExtractor()

    by_field_cause: Counter[tuple[str, str, str, str]] = Counter()
    samples: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    total_false = 0

    for item in extractions:
        entry = manifest.get(item["source_path"])
        if not entry:
            continue
        md_path = project_root / Path(entry["md"].replace("\\", "/"))
        if not md_path.exists():
            continue

        middle_path = None
        middle_rel = (entry.get("json") or {}).get("middle")
        if middle_rel:
            candidate = project_root / Path(middle_rel.replace("\\", "/"))
            if candidate.exists():
                middle_path = candidate

        pdf_path = project_root / Path(entry["source_pdf"].replace("\\", "/"))
        try:
            raw = extractor.extract(md_path, source_pdf=pdf_path, middle_path=middle_path)
            payload = build_payload(raw)
        except Exception:
            raw = None
            payload = item["payload"]

        stem = entry.get("stem", md_path.stem)

        for warning in item["warnings"]:
            if str(warning.get("reason") or "") not in FIELD_MISSING_REASONS:
                continue
            if verify_warning_in_md(warning, md_path) != "extract_failure":
                continue
            total_false += 1
            label = str(warning.get("label") or "")
            section = str(warning.get("section") or "")
            reason = str(warning.get("reason") or "")
            cause = diagnose_one(warning, md_path, item["payload"], raw)
            key = (reason, section, label, cause)
            by_field_cause[key] += 1
            if len(samples[key]) < 3:
                samples[key].append(stem)

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (reason, section, label, cause), count in by_field_cause.most_common():
        grouped[(label, section)].append(
            {
                "reason": reason,
                "root_cause": cause,
                "root_cause_cn": ROOT_CAUSE_CN.get(cause, cause),
                "count": count,
                "samples": samples[(reason, section, label, cause)],
            }
        )

    summary_rows = []
    for (label, section), causes in sorted(
        grouped.items(),
        key=lambda x: (-sum(c["count"] for c in x[1]), x[0][0]),
    ):
        total = sum(c["count"] for c in causes)
        summary_rows.append(
            {
                "label": label,
                "section": section,
                "false_missing_total": total,
                "causes": sorted(causes, key=lambda c: -c["count"]),
            }
        )

    result = {
        "total_extract_failures": total_false,
        "root_cause_legend": ROOT_CAUSE_CN,
        "by_field": summary_rows,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_lines = ["label,section,root_cause,root_cause_cn,count,samples"]
    for row in summary_rows:
        for cause in row["causes"]:
            csv_lines.append(
                f"{json.dumps(row['label'], ensure_ascii=False)},{row['section']},"
                f"{cause['root_cause']},{json.dumps(cause['root_cause_cn'], ensure_ascii=False)},"
                f"{cause['count']},{json.dumps(cause['samples'], ensure_ascii=False)}"
            )
    OUT_CSV.write_text("\n".join(csv_lines), encoding="utf-8-sig")

    print(f"\n=== 抽取误报根因诊断（共 {total_false} 条）===\n")
    for row in summary_rows:
        if row["false_missing_total"] == 0:
            continue
        print(f"【{row['label']}】({row['section']}) — 误报 {row['false_missing_total']} 次")
        for cause in row["causes"]:
            print(f"  · {cause['root_cause_cn']}: {cause['count']}")
            if cause["samples"]:
                print(f"    样例: {', '.join(cause['samples'][:2])}")
        print()

    print(f"JSON: {OUT_JSON}")
    print(f"CSV:  {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
