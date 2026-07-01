"""pdfplumber PDF 文本/表格抽取主实现。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber

from syllabus_auditor.shared.config import load_extraction_config, load_project_config
from syllabus_auditor.core.extractors.base import BaseExtractor
from syllabus_auditor.core.extractors.pdfplumber.enhance import enhance_raw_extraction
from syllabus_auditor.core.extractors.section_table_parser import parse_course_goal_extras, parse_section_tables
from syllabus_auditor.core.meta_builder import EXTRACTOR_VERSION
from syllabus_auditor.core.types import ExtractionRaw


def _pdf_config() -> dict[str, Any]:
    value = load_project_config().get("pdf_extractor", {})
    return value if isinstance(value, dict) else {}


def _section_titles(key: str) -> list[str]:
    value = load_extraction_config().get("section_titles", {}).get(key, [])
    return [str(item) for item in value] if isinstance(value, list) else []


RAW_CN_FIELDS = [str(item) for item in (_pdf_config().get("raw_cn_fields") or [])]
BASIC_PAIR_LABELS = {str(item) for item in (_pdf_config().get("basic_pair_labels") or [])}
TEACHER_LABELS = [str(item) for item in (_pdf_config().get("teacher_labels") or [])]
TWO_COLUMN_SECTION_LABELS = {str(item) for item in (_pdf_config().get("two_column_section_labels") or [])}
_GOAL_LABELS = ("思政目标", "能力目标", "知识目标")


def normalize_label(value: str | None) -> str:
    text = re.sub(r"\s+", "", value or "")
    return text.replace("(", "（").replace(")", "）")


_BASIC_PAIR_LABELS_BY_NORM = {normalize_label(label): label for label in BASIC_PAIR_LABELS}
_BASIC_PAIR_LABELS_BY_NORM.setdefault(normalize_label("开课院系"), "开课（院）系")


def _match_section_label(value: str) -> str | None:
    norm = normalize_label(value)
    if norm in TWO_COLUMN_SECTION_LABELS:
        return norm
    for goal in _GOAL_LABELS:
        goal_norm = normalize_label(goal)
        if norm == goal_norm or (len(norm) >= 3 and goal_norm.startswith(norm)):
            return goal
    return None


def clean_text(value: str | None, keep_newline: bool = False) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r" *\n *", "\n" if keep_newline else "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def table_has_labels(table: list[list[str | None]], labels: list[str]) -> bool:
    table_text = "".join(normalize_label(c) for row in table for c in row if c)
    return all(label in table_text for label in labels)


def put_if_present(data: dict[str, str], key: str, value: str | None) -> None:
    value = clean_text(value)
    if value:
        data[key] = value


def join_text(existing: str, addition: str) -> str:
    existing = clean_text(existing, keep_newline=True)
    addition = clean_text(addition, keep_newline=True)
    if not existing:
        return addition
    if not addition:
        return existing
    return f"{existing}\n{addition}"


def parse_pair_table(data: dict[str, str], table: list[list[str | None]]) -> None:
    for row in table:
        values = [clean_text(c) for c in row]
        for idx in range(0, len(values), 2):
            key = normalize_label(values[idx])
            value = values[idx + 1] if idx + 1 < len(values) else ""
            if not key:
                continue
            canonical = _BASIC_PAIR_LABELS_BY_NORM.get(key)
            if canonical:
                put_if_present(data, canonical, value)
            elif key in (normalize_label("是否允许外学院选课"), normalize_label("允许外学院选课")):
                put_if_present(data, "是否允许外学院选课", value)


def parse_teacher(data: dict[str, str], table: list[list[str | None]]) -> None:
    if not table_has_labels(table, ["教师工号", "职称"]):
        return
    for row in table:
        values = [clean_text(c) for c in row]
        for idx in range(0, len(values), 2):
            key = normalize_label(values[idx])
            value = values[idx + 1] if idx + 1 < len(values) else ""
            if key in TEACHER_LABELS:
                data[key] = value
    if not data.get("任课教师姓名"):
        for row in table:
            for idx, value in enumerate(row):
                if "任课教师" in normalize_label(str(value or "")) and idx + 1 < len(row):
                    put_if_present(data, "任课教师姓名", row[idx + 1])
                    return


def parse_two_column_sections(data: dict[str, str], tables: list[list[list[str | None]]]) -> None:
    current_label: str | None = None
    for table in tables:
        max_cols = max((len(row) for row in table), default=0)
        if max_cols < 2:
            current_label = None
            continue
        for row in table:
            values = [clean_text(c, keep_newline=True) for c in row]
            label_idx = next((idx for idx, value in enumerate(values) if _match_section_label(value)), -1)
            if label_idx >= 0:
                label = _match_section_label(values[label_idx]) or ""
                value = clean_text("\n".join(values[label_idx + 1 :]), keep_newline=True)
                current_label = label
                if value:
                    data[current_label] = join_text(data.get(current_label, ""), value)
            elif current_label and not normalize_label(values[0] if values else ""):
                value = clean_text("\n".join(values[1:]), keep_newline=True)
                data[current_label] = join_text(data.get(current_label, ""), value)
            else:
                current_label = None


def normalize_full_text(text: str) -> str:
    lines = [clean_text(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _title_pattern(title: str) -> str:
    prefix = r"(?:[（(]?[一二三四五六七八九十0-9]+[）)]?\s*)?"
    return rf"(?m)^\s*{prefix}{re.escape(title)}\s*$"


def _assessment_title_pattern(title: str) -> str:
    prefix = r"(?P<prefix>[（(]?[一二三四五六七八九十0-9]+[）)]?[、.．]?\s*)?"
    suffix = r"(?:及成绩构成|与成绩构成|说明)?"
    return rf"(?m)^\s*{prefix}{re.escape(title)}{suffix}\s*[：:]?\s*$"


def _has_prior_course_body_section(text: str, pos: int) -> bool:
    prior = text[:pos]
    prior_titles = (
        _section_titles("course_goal")
        + _section_titles("teaching_content")
        + _section_titles("course_schedule")
        + _section_titles("course_requirements")
    )
    return any(re.search(_title_pattern(title), prior) for title in prior_titles)

def extract_section(text: str, title: str, next_titles: list[str], *, prefer_last: bool = False) -> str:
    matches = list(re.finditer(_title_pattern(title), text))
    if not matches:
        return ""
    match = matches[-1] if prefer_last else matches[0]
    start = match.end()
    end = len(text)
    for next_title in next_titles:
        next_match = re.search(_title_pattern(next_title), text[start:])
        if next_match:
            end = min(end, start + next_match.start())
    return clean_text(text[start:end], keep_newline=True)


def extract_assessment_section(text: str) -> str:
    """只抽真正的考核方式章节，避免基础信息表里的短字段污染 khfsb.khgs。"""
    matches: list[re.Match[str]] = []
    for title in _section_titles("assessment"):
        for match in re.finditer(_assessment_title_pattern(title), text):
            prefix = match.groupdict().get("prefix") or ""
            if prefix.strip() or title != "考核方式" or _has_prior_course_body_section(text, match.start()):
                matches.append(match)
    if not matches:
        return ""

    match = sorted(matches, key=lambda item: item.start())[-1]
    start = match.end()
    end = len(text)
    next_titles = _section_titles("course_requirements") + _section_titles("reading_material")
    for next_title in next_titles:
        next_match = re.search(_title_pattern(next_title), text[start:])
        if next_match:
            end = min(end, start + next_match.start())
    return clean_text(text[start:end], keep_newline=True)

def parse_sections_from_text(data: dict[str, str], full_text: str) -> None:
    text = normalize_full_text(full_text)
    stop_after_intro = _section_titles("course_goal") + _section_titles("teaching_content") + _section_titles("course_schedule") + _section_titles("reading_material") + _section_titles("assessment") + _section_titles("course_requirements")

    if not data.get("预备知识要求"):
        data["预备知识要求"] = extract_section(text, "预备知识要求", stop_after_intro)

    if not any(data.get(k) for k in ("思政目标", "能力目标", "知识目标")):
        overview = extract_section(text, "课程目标", _section_titles("teaching_content") + _section_titles("course_schedule") + _section_titles("reading_material") + _section_titles("assessment") + _section_titles("course_requirements"))
        if overview:
            data["课程目标概述"] = overview

    data["课程要求"] = extract_section(text, "课程要求", _section_titles("teaching_content") + _section_titles("course_schedule") + _section_titles("reading_material") + _section_titles("assessment"))
    data["阅读材料"] = extract_section(text, "阅读材料", _section_titles("course_requirements") + _section_titles("assessment"))


def apply_khfsb_source(
    data: dict[str, str],
    full_text: str,
    assessment_rows: list[dict[str, Any]],
) -> str:
    """考核方式类型判别：识别到考核表 → table/tm；否则 → text/khgs（二者互斥）。"""
    if assessment_rows:
        data["考核方式说明"] = ""
        return "table"
    text = normalize_full_text(full_text)
    data["考核方式说明"] = extract_assessment_section(text)
    return "text"


def fill_overview_fallbacks(data: dict[str, str], full_text: str, teaching_content: list[dict[str, str]], course_schedule: list[dict[str, str]]) -> None:
    text = normalize_full_text(full_text)
    if not teaching_content and not data.get("教学内容概述"):
        data["教学内容概述"] = extract_section(text, "教学内容", _section_titles("course_schedule") + _section_titles("reading_material") + _section_titles("assessment") + _section_titles("course_requirements"))
    if not course_schedule and not data.get("课程安排概述"):
        data["课程安排概述"] = extract_section(text, "教学安排", _section_titles("reading_material") + _section_titles("assessment") + _section_titles("course_requirements"))


class PdfPlumberExtractor(BaseExtractor):
    def extract(self, pdf_path: Path) -> ExtractionRaw:
        data = {field: "" for field in RAW_CN_FIELDS}
        all_tables: list[list[list[str | None]]] = []
        raw_pages: list[str] = []

        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                raw_pages.append(page_text)
                all_tables.extend(page.extract_tables() or [])

        full_text = "\n".join(raw_pages)
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
        khfsb_format = apply_khfsb_source(data, full_text, assessment_rows)
        fill_overview_fallbacks(data, full_text, teaching_content, course_schedule)

        section_extraction: dict[str, Any] = {"khfsb_format": khfsb_format}
        content_total_hours = parsed_sections.get("content_total_hours")
        if content_total_hours:
            section_extraction["content_total_hours"] = content_total_hours

        raw = ExtractionRaw(
            cn_data=data,
            full_text=full_text,
            raw_pages=raw_pages,
            page_count=page_count,
            teaching_content=teaching_content,
            course_schedule=course_schedule,
            assessment_rows=assessment_rows,
            course_goal_extras=course_goal_extras,
            extraction_warnings=extraction_warnings,
            section_extraction=section_extraction,
            source_path=pdf_path,
        )
        return enhance_raw_extraction(raw, pdf_path)


EXTRACTOR_NAME = EXTRACTOR_VERSION


