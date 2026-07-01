"""MinerU 结构化处理：表格→ExtractionRaw、纯文本章节兜底。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from syllabus_auditor.shared.config import load_extraction_config
from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.core.extractors.mineru.tables import normalize_mineru_tables
from syllabus_auditor.core.extractors.pdfplumber.enhance import (
    IDEOLOGY_INTEGRATION,
    KNOWLEDGE,
    SEQ,
    TEACHING_CONTENT,
    TEACHING_METHOD,
    TOPIC,
    build_text_candidates,
    extract_section,
)
from syllabus_auditor.core.extractors.pdfplumber.extractor import (
    RAW_CN_FIELDS,
    apply_khfsb_source,
    fill_overview_fallbacks,
    parse_pair_table,
    parse_sections_from_text,
    parse_teacher,
    parse_two_column_sections,
    put_if_present,
    table_has_labels,
)
from syllabus_auditor.core.extractors.section_table_parser import (
    parse_course_goal_extras,
    parse_section_tables,
)
from syllabus_auditor.core.types import ExtractionRaw

# ---------------------------------------------------------------------------
# 构建：MinerU 表格 + 全文 → ExtractionRaw
# ---------------------------------------------------------------------------


def _extraction_params() -> dict[str, Any]:
    value = load_project_config().get("extraction_params", {})
    return value if isinstance(value, dict) else {}


def _jcxx_regex() -> tuple[tuple[str, str], ...]:
    rows = _extraction_params().get("jcxx_regex") or []
    return tuple((str(row[0]), str(row[1])) for row in rows if isinstance(row, (list, tuple)) and len(row) >= 2)


# 兼容旧测试/诊断脚本
_JCXX_REGEX = _jcxx_regex


def _section_titles(key: str) -> list[str]:
    value = load_extraction_config().get("section_titles", {}).get(key, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _fill_jcxx_from_text(data: dict[str, str], full_text: str) -> None:
    for pattern, field in _jcxx_regex():
        if data.get(field):
            continue
        match = re.search(pattern, full_text, re.DOTALL)
        if match:
            put_if_present(data, field, match.group(1))


def _inject_section_anchors(full_text: str) -> str:
    """MinerU 文本里「（五）教学安排」等标题补锚点，便于 section 兜底。"""
    anchors = _extraction_params().get("section_anchors") or []
    text = full_text
    for row in anchors:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        pattern, title = str(row[0]), str(row[1])
        text = re.sub(pattern, f"\n{title}\n", text, count=1)
    return text


def build_extraction_raw(
    *,
    full_text: str,
    tables: list[list[list[str | None]]],
    source_path: Path,
    page_count: int,
    selected_source: str,
) -> ExtractionRaw:
    all_tables = normalize_mineru_tables(tables)
    full_text = _inject_section_anchors(full_text)

    data = {field: "" for field in RAW_CN_FIELDS}
    teacher_done = False
    for table in all_tables:
        if not table:
            continue
        if table_has_labels(table, ["课程编号"]):
            parse_pair_table(data, table)
        elif table_has_labels(table, ["周学时", "总学时"]):
            parse_pair_table(data, table)
        elif table_has_labels(table, ["教师工号", "职称"]) and not teacher_done:
            parse_teacher(data, table)
            teacher_done = True

    parse_two_column_sections(data, all_tables)
    parsed_sections = parse_section_tables(all_tables)
    teaching_content = parsed_sections["teaching_content"]
    course_schedule = parsed_sections["course_schedule"]
    assessment_rows = parsed_sections["assessment_rows"]
    extraction_warnings = parsed_sections["warnings"]
    course_goal_extras = parse_course_goal_extras(all_tables)

    parse_sections_from_text(data, full_text)
    _fill_jcxx_from_text(data, full_text)
    fill_overview_fallbacks(data, full_text, teaching_content, course_schedule)

    raw = ExtractionRaw(
        cn_data=data,
        full_text=full_text,
        raw_pages=[full_text],
        page_count=max(1, page_count),
        teaching_content=teaching_content,
        course_schedule=course_schedule,
        assessment_rows=assessment_rows,
        course_goal_extras=course_goal_extras,
        extraction_warnings=extraction_warnings,
        section_extraction={
            "selected_source": selected_source,
            **(
                {"content_total_hours": parsed_sections["content_total_hours"]}
                if parsed_sections.get("content_total_hours")
                else {}
            ),
        },
        source_path=source_path,
    )
    apply_mineru_text_fallback(raw)
    khfsb_format = apply_khfsb_source(raw.cn_data, raw.full_text, raw.assessment_rows)
    raw.section_extraction["khfsb_format"] = khfsb_format
    return raw


# ---------------------------------------------------------------------------
# 文本兜底：表格弱/空时用纯文本章节补全
# ---------------------------------------------------------------------------


def _configured_titles(key: str) -> tuple[str, ...]:
    titles = load_extraction_config().get("section_titles", {}).get(key, [])
    return tuple(str(item) for item in titles if str(item).strip())


def _row_completeness(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    total = len(rows) * max(len(fields), 1)
    hits = sum(1 for row in rows for field in fields if str(row.get(field, "")).strip())
    return hits / total


def _merge_row_fields(existing: dict[str, Any], addition: dict[str, Any]) -> None:
    for key, value in addition.items():
        if not str(value or "").strip():
            continue
        if not str(existing.get(key, "")).strip():
            existing[key] = value


def _merge_rows_by_seq(
    table_rows: list[dict[str, Any]],
    text_rows: list[dict[str, Any]],
    seq_key: str = SEQ,
) -> list[dict[str, Any]]:
    if not text_rows:
        return table_rows
    if not table_rows:
        return text_rows
    by_seq: dict[str, dict[str, Any]] = {}
    for row in table_rows:
        seq = str(row.get(seq_key, "")).strip()
        key = seq.split("\n")[0].split("/")[0] if seq else ""
        if key:
            by_seq[key] = dict(row)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text_row in text_rows:
        seq = str(text_row.get(seq_key, "")).strip()
        key = seq.split("\n")[0] if seq else ""
        if key and key in by_seq:
            combined = dict(by_seq[key])
            _merge_row_fields(combined, text_row)
            merged.append(combined)
            seen.add(key)
        elif not table_rows:
            merged.append(dict(text_row))
    for row in table_rows:
        seq = str(row.get(seq_key, "")).strip()
        key = seq.split("\n")[0] if seq else ""
        if key and key in seen:
            continue
        merged.append(dict(row))
    if not merged:
        return table_rows
    return merged


def _pick_rows(
    table_rows: list[dict[str, Any]],
    text_rows: list[dict[str, Any]],
    required: tuple[str, ...],
    *,
    min_table_rows: int = 2,
) -> tuple[list[dict[str, Any]], str | None]:
    table_score = _row_completeness(table_rows, required) + min(len(table_rows), 10) * 0.05
    text_score = _row_completeness(text_rows, required) + min(len(text_rows), 10) * 0.05
    if not table_rows and text_rows:
        return text_rows, "mineru_text_fallback"
    if len(table_rows) < min_table_rows and len(text_rows) >= min_table_rows:
        return _merge_rows_by_seq(table_rows, text_rows), "mineru_text_fallback"
    if text_score > table_score + 0.15 and len(text_rows) >= len(table_rows):
        return _merge_rows_by_seq(table_rows, text_rows), "mineru_text_fallback"
    if table_rows and text_rows:
        merged = _merge_rows_by_seq(table_rows, text_rows)
        if _row_completeness(merged, required) > table_score:
            return merged, "mineru_text_merged"
    return table_rows, None


def apply_mineru_text_fallback(raw: ExtractionRaw) -> None:
    """表格结果不足时用 full_text 章节正则补全/合并。"""
    candidates = build_text_candidates(raw.full_text, "mineru_text_fallback")

    tc_req = (SEQ, TOPIC, KNOWLEDGE)
    tc_rows, tc_source = _pick_rows(
        raw.teaching_content,
        candidates["teaching_content"].rows,
        tc_req,
        min_table_rows=2,
    )
    if tc_source:
        raw.teaching_content = tc_rows
        raw.section_extraction["teaching_content_text_fallback"] = {
            "source": tc_source,
            "row_count": len(tc_rows),
        }
        raw.extraction_warnings.append(
            {
                "section": "教学内容",
                "reason": "validated_text_fallback_used",
                "source": tc_source,
                "severity": "info",
            }
        )

    cs_req = (SEQ, TEACHING_CONTENT)
    cs_rows, cs_source = _pick_rows(
        raw.course_schedule,
        candidates["course_schedule"].rows,
        cs_req,
        min_table_rows=1,
    )
    if cs_source:
        raw.course_schedule = cs_rows
        raw.section_extraction["course_schedule_text_fallback"] = {
            "source": cs_source,
            "row_count": len(cs_rows),
        }
        raw.extraction_warnings.append(
            {
                "section": "教学安排",
                "reason": "validated_text_fallback_used",
                "source": cs_source,
                "severity": "info",
            }
        )

    for field, value in (candidates.get("goal_fields") or {}).items():
        if value and not str(raw.cn_data.get(field, "")).strip():
            raw.cn_data[field] = value

    for row in raw.course_schedule:
        sknr = str(row.get(TEACHING_CONTENT, ""))
        if str(row.get(IDEOLOGY_INTEGRATION, "")).strip():
            continue
        if "思政" in sknr:
            idx = sknr.find("思政")
            row[IDEOLOGY_INTEGRATION] = sknr[idx:].strip()
            row[TEACHING_CONTENT] = sknr[:idx].strip()
        if not str(row.get(TEACHING_METHOD, "")).strip():
            for token in ("讲授", "研讨", "讨论", "案例", "课堂", "阅读", "线上"):
                if token in sknr:
                    row[TEACHING_METHOD] = token
                    break

    if not raw.course_schedule:
        section = extract_section(raw.full_text, _configured_titles("course_schedule"))
        if section and len(section) > 80:
            raw.cn_data["课程安排概述"] = section[:4000]
            raw.section_extraction["course_schedule_overview_fallback"] = {"chars": len(section)}

