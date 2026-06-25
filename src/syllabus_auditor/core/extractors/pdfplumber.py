from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from syllabus_auditor.core.meta_builder import EXTRACTOR_VERSION
from syllabus_auditor.core.types import ExtractionRaw
from syllabus_auditor.core.extractors.base import BaseExtractor
from syllabus_auditor.core.extractors.section_table_parser import (
    parse_course_goal_extras,
    parse_section_tables,
)

RAW_CN_FIELDS = [
    "课程编号",
    "开课（院）系",
    "中文课程名称",
    "英文课程名称",
    "课程性质",
    "课程类别",
    "课程模块",
    "授课语言",
    "是否允许外学院选课",
    "考核方式",
    "周学时",
    "上课周数",
    "总学时",
    "教学学时",
    "实验学时",
    "实践学时",
    "其他学时",
    "自学学时",
    "课程学分",
    "任课教师姓名",
    "教师工号",
    "职称",
    "学历",
    "E-mail",
    "联系电话",
    "课程中文简介",
    "课程英文简介",
    "思政目标",
    "能力目标",
    "知识目标",
    "课程目标概述",
    "教学内容概述",
    "课程安排概述",
    "预备知识要求",
    "课程要求",
    "阅读材料",
    "考核方式说明",
]


def normalize_label(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def clean_text(value: str | None, keep_newline: bool = False) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r" *\n *", "\n" if keep_newline else "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def cell(row: list[str | None], index: int) -> str:
    if index >= len(row):
        return ""
    return clean_text(row[index])


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
    direct_keys = {
        "课程编号",
        "开课（院）系",
        "中文课程名称",
        "英文课程名称",
        "课程性质",
        "课程类别",
        "课程模块",
        "授课语言",
        "考核方式",
        "周学时",
        "上课周数",
        "总学时",
        "教学学时",
        "实验学时",
        "实践学时",
        "其他学时",
        "自学学时",
        "课程学分",
    }
    for row in table:
        values = [clean_text(c) for c in row]
        for idx in range(0, len(values), 2):
            key = normalize_label(values[idx])
            value = values[idx + 1] if idx + 1 < len(values) else ""
            if not key:
                continue
            if key in direct_keys:
                put_if_present(data, key, value)
            elif key in ("是否允许外学院选课", "允许外学院选课"):
                put_if_present(data, "是否允许外学院选课", value)


def parse_teacher(data: dict[str, str], table: list[list[str | None]]) -> None:
    if not table_has_labels(table, ["教师工号", "职称"]):
        return
    for row in table:
        values = [clean_text(c) for c in row]
        for idx in range(0, len(values), 2):
            key = normalize_label(values[idx])
            value = values[idx + 1] if idx + 1 < len(values) else ""
            if key == "任课教师姓名":
                put_if_present(data, "任课教师姓名", value)
            elif key == "教师工号":
                put_if_present(data, "教师工号", value)
            elif key == "职称":
                put_if_present(data, "职称", value)
            elif key == "学历":
                put_if_present(data, "学历", value)
            elif key.lower() == "e-mail":
                put_if_present(data, "E-mail", value)
            elif key == "联系电话":
                data["联系电话"] = value
    if not data.get("任课教师姓名"):
        for row in table:
            for idx, value in enumerate(row):
                if "任课教师" in normalize_label(str(value or "")) and idx + 1 < len(row):
                    put_if_present(data, "任课教师姓名", row[idx + 1])
                    return


def parse_two_column_sections(data: dict[str, str], tables: list[list[list[str | None]]]) -> None:
    target_labels = {
        "课程中文简介",
        "课程英文简介",
        "思政目标",
        "能力目标",
        "知识目标",
        "预备知识要求",
    }
    current_label: str | None = None
    for table in tables:
        max_cols = max((len(row) for row in table), default=0)
        if max_cols < 2:
            current_label = None
            continue
        for row in table:
            values = [clean_text(c, keep_newline=True) for c in row]
            label_idx = next((idx for idx, value in enumerate(values) if normalize_label(value) in target_labels), -1)
            if label_idx >= 0:
                label = normalize_label(values[label_idx])
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


def extract_section(
    text: str,
    title: str,
    next_titles: list[str],
    *,
    prefer_last: bool = False,
) -> str:
    title_pattern = rf"(?m)^\s*(?:[（(][一二三四五六七八九十]+[）)]\s*)?{re.escape(title)}\s*$"
    matches = list(re.finditer(title_pattern, text))
    if not matches:
        return ""
    match = matches[-1] if prefer_last else matches[0]
    start = match.end()
    end = len(text)
    for next_title in next_titles:
        next_pattern = rf"(?m)^\s*(?:[（(][一二三四五六七八九十]+[）)]\s*)?{re.escape(next_title)}\s*$"
        next_match = re.search(next_pattern, text[start:])
        if next_match:
            end = min(end, start + next_match.start())
    return clean_text(text[start:end], keep_newline=True)


def parse_sections_from_text(data: dict[str, str], full_text: str) -> None:
    text = normalize_full_text(full_text)

    if not data.get("预备知识要求"):
        data["预备知识要求"] = extract_section(
            text,
            "预备知识要求",
            ["课程目标", "教学内容", "教学安排", "阅读材料", "考核方式", "课程要求"],
        )

    if not any(data.get(k) for k in ("思政目标", "能力目标", "知识目标")):
        overview = extract_section(
            text,
            "课程目标",
            ["教学内容", "教学安排", "阅读材料", "考核方式", "课程要求"],
        )
        if overview:
            data["课程目标概述"] = overview

    data["课程要求"] = extract_section(
        text,
        "课程要求",
        ["教学内容", "教学安排", "阅读材料", "考核方式"],
    )
    data["阅读材料"] = extract_section(text, "阅读材料", ["课程要求", "考核方式"])
    data["考核方式说明"] = extract_section(text, "考核方式", ["课程要求", "阅读材料"], prefer_last=True)


def fill_overview_fallbacks(
    data: dict[str, str],
    full_text: str,
    teaching_content: list[dict[str, str]],
    course_schedule: list[dict[str, str]],
) -> None:
    text = normalize_full_text(full_text)
    if not teaching_content and not data.get("教学内容概述"):
        data["教学内容概述"] = extract_section(
            text,
            "教学内容",
            ["教学安排", "阅读材料", "考核方式", "课程要求"],
        )
    if not course_schedule and not data.get("课程安排概述"):
        data["课程安排概述"] = extract_section(
            text,
            "教学安排",
            ["阅读材料", "考核方式", "课程要求"],
        )


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
        course_requirements = parsed_sections["course_requirements"]
        extraction_warnings = parsed_sections["warnings"]
        course_goal_extras = parse_course_goal_extras(all_tables)

        parse_sections_from_text(data, full_text)
        fill_overview_fallbacks(data, full_text, teaching_content, course_schedule)

        return ExtractionRaw(
            cn_data=data,
            full_text=full_text,
            raw_pages=raw_pages,
            page_count=page_count,
            teaching_content=teaching_content,
            course_schedule=course_schedule,
            assessment_rows=assessment_rows,
            course_requirements=course_requirements,
            course_goal_extras=course_goal_extras,
            extraction_warnings=extraction_warnings,
            source_path=pdf_path,
        )


EXTRACTOR_NAME = EXTRACTOR_VERSION

