from __future__ import annotations

import re
from typing import Any

from config import load_extraction_config
from syllabus_auditor.core.extractors.fusion import ExtractionCandidate, make_row_candidate

SEQ = "序号"
TOPIC = "主题"
KNOWLEDGE = "知识点"
HOURS = "学时"
TEACHING_CONTENT = "授课内容"
TEACHING_METHOD = "授课方式"
HOMEWORK = "作业"
IDEOLOGY_INTEGRATION = "思政元素的融入和预期教学成效"
ASSESSMENT_FORM = "考试形式"
ASSESSMENT_CONTENT = "考察内容"
ASSESSMENT_METHOD = "考察方式"
ASSESSMENT_RATIO = "占比"
REQ_TYPE = "要求类型"
REQ_CONTENT = "要求内容"
SZ_GOAL = "思政目标"
NL_GOAL = "能力目标"
ZS_GOAL = "知识目标"
GOAL_OVERVIEW = "课程目标概述"
COURSE_REQUIREMENT = "课程要求"
ASSESSMENT_DESC = "考核方式说明"


def _configured_titles(key: str) -> tuple[str, ...]:
    titles = load_extraction_config().get("section_titles", {}).get(key, [])
    return tuple(str(item) for item in titles if str(item).strip())


SECTION_TITLES = _configured_titles("all")


def normalize_text(text: str) -> str:
    lines = []
    for line in str(text or "").replace("\r", "\n").splitlines():
        cleaned = re.sub(r"[\t\u3000]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _title_regex(title: str) -> str:
    prefix = r"(?:[（(]?[一二三四五六七八九十0-9]+[）)]?\s*[、.．-]?\s*)?"
    suffix = r"(?:[与及和、][^\n]{0,12})?"
    return rf"^\s*{prefix}{re.escape(title)}{suffix}\s*$"


def extract_section(text: str, titles: tuple[str, ...], stop_titles: tuple[str, ...] = SECTION_TITLES) -> str:
    normalized = normalize_text(text)
    matches: list[re.Match[str]] = []
    for title in titles:
        matches.extend(re.finditer(_title_regex(title), normalized, flags=re.MULTILINE))
    if not matches:
        return ""
    match = sorted(matches, key=lambda item: item.start())[0]
    start = match.end()
    end = len(normalized)
    for stop_title in stop_titles:
        if stop_title in titles:
            continue
        stop_match = re.search(_title_regex(stop_title), normalized[start:], flags=re.MULTILINE)
        if stop_match:
            end = min(end, start + stop_match.start())
    return normalized[start:end].strip()


def _split_columns(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s{2,}|\t+|\|", line) if part.strip()]


def _is_noise_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return not compact or compact in {"序号主题知识点学时", "周次授课内容授课方式"}


def parse_teaching_content(text: str, source: str) -> ExtractionCandidate:
    section = extract_section(text, _configured_titles("teaching_content"))
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for line in section.splitlines():
        if _is_noise_line(line):
            continue
        match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[、.．-]?\s+(.+?)\s+(\d+(?:\.\d+)?)\s*(?:学时)?\s*$", line)
        if not match:
            continue
        seq, middle, hours = match.groups()
        columns = _split_columns(middle)
        if len(columns) >= 2:
            topic = columns[0]
            knowledge = " ".join(columns[1:])
        else:
            topic = columns[0] if columns else middle
            knowledge = middle
            warnings.append({"reason": "text_row_low_confidence", "line": line})
        rows.append({SEQ: seq, TOPIC: topic, KNOWLEDGE: knowledge, HOURS: hours})
    return make_row_candidate(
        "teaching_content",
        source,
        rows,
        (SEQ, TOPIC, KNOWLEDGE, HOURS),
        warnings=warnings,
        evidence={"section_title": "教学内容", "section_excerpt": section[:500]},
    )


def parse_course_schedule(text: str, source: str) -> ExtractionCandidate:
    section = extract_section(text, _configured_titles("course_schedule"))
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for line in section.splitlines():
        if _is_noise_line(line):
            continue
        match = re.match(
            r"^\s*(?:第)?(\d+(?:\s*[-~～至,，、]\s*\d+)*)\s*(?:周|周次)?\s+(.+)$",
            line,
        )
        if not match:
            continue
        weeks, rest = match.groups()
        columns = _split_columns(rest)
        item: dict[str, Any] = {SEQ: weeks.strip()}
        if columns:
            item[TEACHING_CONTENT] = columns[0]
        if len(columns) >= 2:
            item[TEACHING_METHOD] = columns[1]
        if len(columns) >= 3:
            item[IDEOLOGY_INTEGRATION] = " ".join(columns[2:])
        if IDEOLOGY_INTEGRATION not in item and "思政" in rest:
            item[IDEOLOGY_INTEGRATION] = rest[rest.find("思政") :]
        if TEACHING_METHOD not in item:
            method_match = re.search(r"(讲授|讨论|案例|实践|翻转课堂|实验)", rest)
            if method_match:
                item[TEACHING_METHOD] = method_match.group(1)
            else:
                warnings.append({"reason": "missing_teaching_method", "line": line})
        rows.append(item)
    return make_row_candidate(
        "course_schedule",
        source,
        rows,
        (SEQ, TEACHING_CONTENT),
        warnings=warnings,
        evidence={"section_title": "教学安排", "section_excerpt": section[:500]},
    )


def parse_assessment(text: str, source: str) -> ExtractionCandidate:
    section = extract_section(text, _configured_titles("assessment"))
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()、]{2,24}?)(?:成绩|考试|考核|作业|表现|论文|考勤)?"
        r"[^0-9%\n％]{0,24}?(\d+(?:\.\d+)?)\s*[%％]"
    )
    for match in pattern.finditer(section):
        label = re.sub(r"^[，,。.、\s]+", "", match.group(1)).strip()
        ratio = f"{match.group(2)}%"
        if not label or (label, ratio) in seen:
            continue
        seen.add((label, ratio))
        rows.append(
            {
                ASSESSMENT_FORM: label,
                ASSESSMENT_CONTENT: label,
                ASSESSMENT_METHOD: label,
                ASSESSMENT_RATIO: ratio,
            }
        )
    return make_row_candidate(
        "assessment_rows",
        source,
        rows,
        (ASSESSMENT_FORM, ASSESSMENT_RATIO),
        evidence={"section_title": "考核方式", "section_excerpt": section[:500]},
    )


def parse_requirements(text: str) -> tuple[list[dict[str, Any]], str]:
    section = extract_section(text, _configured_titles("course_requirements"))
    rows: list[dict[str, Any]] = []
    for line in section.splitlines():
        match = re.match(r"^\s*([\u4e00-\u9fa5]{2,8}要求)[:：]?\s*(.+)$", line)
        if match:
            rows.append({REQ_TYPE: match.group(1), REQ_CONTENT: match.group(2)})
    return rows, section


def parse_goal_fields(text: str) -> dict[str, str]:
    section = extract_section(text, _configured_titles("course_goal"))
    if not section:
        return {}
    result: dict[str, str] = {}
    label_map = {
        SZ_GOAL: (SZ_GOAL, "价值目标", "育人目标", "课程思政目标"),
        NL_GOAL: (NL_GOAL,),
        ZS_GOAL: (ZS_GOAL,),
    }
    stop_labels = [SZ_GOAL, NL_GOAL, ZS_GOAL, "价值目标", "育人目标", "课程思政目标"]
    stop_pattern = "|".join(re.escape(label) for label in stop_labels)
    for field, labels in label_map.items():
        for label in labels:
            pattern = rf"{re.escape(label)}\s*[:：]?\s*(.+?)(?=\n\s*(?:{stop_pattern})\s*[:：]?|\Z)"
            match = re.search(pattern, section, flags=re.DOTALL)
            if match:
                result[field] = match.group(1).strip()
                break
    if not result:
        result[GOAL_OVERVIEW] = section
    return result


def build_text_candidates(text: str, source: str = "text_fallback") -> dict[str, Any]:
    requirements_rows, requirements_text = parse_requirements(text)
    return {
        "teaching_content": parse_teaching_content(text, source),
        "course_schedule": parse_course_schedule(text, source),
        "assessment_rows": parse_assessment(text, source),
        "course_requirements": make_row_candidate(
            "course_requirements",
            source,
            requirements_rows,
            (REQ_TYPE, REQ_CONTENT),
            evidence={"section_title": "课程要求", "section_excerpt": requirements_text[:500]},
        ),
        "course_requirement_text": requirements_text,
        "goal_fields": parse_goal_fields(text),
    }

