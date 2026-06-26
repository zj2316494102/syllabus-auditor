"""MinerU 表格 + 全文 → ExtractionRaw（pdfplumber / fusion 不参与）。"""

from __future__ import annotations

import re
from pathlib import Path

from config import load_extraction_config
from syllabus_auditor.core.extractors.mineru_table_normalize import normalize_mineru_tables
from syllabus_auditor.core.extractors.pdfplumber import (
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

_JCXX_REGEX = (
    (r"课程编号\s*[：:]\s*(\S+)", "课程编号"),
    (r"中文课程名称\s*[：:]\s*(.+?)(?:\n|英文课程名称|$)", "中文课程名称"),
    (r"英文课程名称\s*[：:]\s*(.+?)(?:\n|课程性质|$)", "英文课程名称"),
    (r"开课[（(]院[）)]系\s*[：:]\s*(.+?)(?:\n|中文课程名称|$)", "开课（院）系"),
    (r"任课教师姓名\s*[：:]\s*(.+?)(?:\n|教师工号|$)", "任课教师姓名"),
)


def _section_titles(key: str) -> list[str]:
    value = load_extraction_config().get("section_titles", {}).get(key, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _fill_jcxx_from_text(data: dict[str, str], full_text: str) -> None:
    for pattern, field in _JCXX_REGEX:
        if data.get(field):
            continue
        match = re.search(pattern, full_text, re.DOTALL)
        if match:
            put_if_present(data, field, match.group(1))


def _inject_section_anchors(full_text: str) -> str:
    """MinerU 文本里「（五）教学安排」等标题补锚点，便于 section 兜底。"""
    anchors = (
        (r"（五）\s*教学安排", "教学安排"),
        (r"（四）\s*教学内容", "教学内容"),
        (r"（六）\s*课程要求", "课程要求"),
        (r"考核方式", "考核方式"),
    )
    text = full_text
    for pattern, title in anchors:
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
    course_requirements = parsed_sections["course_requirements"]
    extraction_warnings = parsed_sections["warnings"]
    course_goal_extras = parse_course_goal_extras(all_tables)

    parse_sections_from_text(data, full_text)
    khfsb_format = apply_khfsb_source(data, full_text, assessment_rows)
    _fill_jcxx_from_text(data, full_text)
    fill_overview_fallbacks(data, full_text, teaching_content, course_schedule)

    return ExtractionRaw(
        cn_data=data,
        full_text=full_text,
        raw_pages=[full_text],
        page_count=max(1, page_count),
        teaching_content=teaching_content,
        course_schedule=course_schedule,
        assessment_rows=assessment_rows,
        course_requirements=course_requirements,
        course_goal_extras=course_goal_extras,
        extraction_warnings=extraction_warnings,
        section_extraction={"selected_source": selected_source, "khfsb_format": khfsb_format},
        source_path=source_path,
    )
