"""入库缺失告警 vs 源文档（MD）章节内核对。"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from syllabus_auditor.shared.config import load_extraction_config
from syllabus_auditor.core.extractors.pdfplumber import extract_section, normalize_full_text

SECTION_TITLES = load_extraction_config().get("section_titles", {})

FIELD_ALIASES: dict[str, list[str]] = {
    "课程编号": ["课程编号", "课 程 编 号"],
    "开课（院）系": ["开课（院）系", "开课院系", "开课(院)系"],
    "中文课程名称": ["中文课程名称", "中文名"],
    "英文课程名称": ["英文课程名称", "英文名"],
    "任课教师姓名": ["任课教师姓名", "主讲教师"],
    "E-mail": ["E-mail", "Email", "电子邮箱", "邮箱"],
    "课程/周次": ["周次", "序号", "课程", "课程/周次"],
    "思政元素的融入和预期教学成效": ["思政元素的融入和预期教学成效", "思政元素", "预期教学成效"],
    "课程要求": ["课程要求", "学习要求", "课堂要求"],
    "教学内容条目": ["教学内容", "课程内容"],
    "教学安排条目": ["教学安排", "课程安排", "授课安排", "教学进度"],
    "考核方式条目": ["考核方式", "课程考核", "成绩评定"],
    "序号": ["序号", "编号"],
    "主题": ["主题", "单元"],
    "知识点": ["知识点", "教学内容", "讲授内容"],
    "学时": ["学时", "课时", "教学学时"],
    "授课内容": ["授课内容", "讲授内容"],
    "授课方式": ["授课方式", "教学方式"],
    "考试形式": ["考试形式", "考核形式"],
    "占比": ["占比", "比例", "权重"],
}

WARNING_SECTION_KEYS: dict[str, str] = {
    "kcmb": "course_goal",
    "jxnr": "teaching_content",
    "jxap": "course_schedule",
    "khfsb": "assessment",
    "kcyq": "course_requirements",
}

TABLE_SECTIONS = frozenset({"jxnr", "jxap", "khfsb"})
EMPTY_MARKERS = {"", "无", "暂无", "不填", "none", "null", "n/a"}


def read_md_plain_text(md_path: Path) -> str:
    md_text = md_path.read_text(encoding="utf-8")
    text = re.sub(r"<[^>]+>", " ", md_text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _label_patterns(label: str) -> list[str]:
    base = [label] if label else []
    return list(dict.fromkeys(base + FIELD_ALIASES.get(label, [])))


def _all_stop_titles(exclude_key: str | None = None) -> list[str]:
    titles: list[str] = []
    for key, items in SECTION_TITLES.items():
        if key == exclude_key or not isinstance(items, list):
            continue
        titles.extend(str(x) for x in items if x)
    return list(dict.fromkeys(titles))


def _has_substantive(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return False
    return cleaned.lower() not in EMPTY_MARKERS


def _extract_section_body(full_text: str, section: str) -> str:
    text = normalize_full_text(full_text)
    if section == "jcxx":
        stop = _all_stop_titles()
        for title in ("课程基本信息", "基本信息", "一、课程基本信息"):
            body = extract_section(text, title, stop)
            if body:
                return body
        for stop_title in ("课程中文简介", "课程简介", "课程目标", "预备知识要求", "二、课程学时"):
            match = re.search(rf"(?:^|\n)\s*.*?{re.escape(stop_title)}", text)
            if match:
                return text[: match.start()].strip()
        return text[:4000]

    config_key = WARNING_SECTION_KEYS.get(section)
    if not config_key:
        return ""
    primary = [str(x) for x in SECTION_TITLES.get(config_key, []) if x]
    stop = _all_stop_titles(exclude_key=config_key)
    for title in primary:
        body = extract_section(text, title, stop)
        if body:
            return body
    return ""


def _md_section_html(md_text: str, section: str) -> str:
    """按 ## 标题切分 MD，取与 section 对应章节的原始 HTML 片段。"""
    config_key = WARNING_SECTION_KEYS.get(section)
    if section == "jcxx":
        titles = ["课程基本信息", "基本信息", "一、课程基本信息", "课程学时"]
    elif config_key:
        titles = [str(x) for x in SECTION_TITLES.get(config_key, []) if x]
        if section == "jxap":
            titles = list(dict.fromkeys(titles + ["课程安排", "七、课程安排"]))
    else:
        return ""

    parts = re.split(r"(^##\s+.+$)", md_text, flags=re.MULTILINE)
    chunks: list[tuple[str, str]] = []
    if parts and not parts[0].strip().startswith("##"):
        chunks.append(("_preamble", parts[0]))
    i = 1
    while i + 1 < len(parts):
        header = re.sub(r"^#+\s*", "", parts[i]).strip()
        chunks.append((header, parts[i + 1]))
        i += 2

    for title in titles:
        for header, body in chunks:
            if title in header or header in title:
                return body
    if section == "jcxx" and chunks:
        return chunks[0][1]
    return ""


def _section_body_has_content(body: str, *, min_chars: int = 8) -> bool:
    if not body:
        return False
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    substantive = [ln for ln in lines if _has_substantive(ln)]
    if len(substantive) >= 2:
        return True
    joined = "".join(substantive)
    return _has_substantive(joined) and len(joined) >= min_chars


def _is_placeholder_value(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return True
    return cleaned.lower() in EMPTY_MARKERS


def _label_has_value_in_body(body: str, label: str) -> bool:
    if not body or not label:
        return False
    for pattern in _label_patterns(label):
        match = re.search(rf"{re.escape(pattern)}\s*[：:]\s*(\S+)", body)
        if match and not _is_placeholder_value(match.group(1)):
            return True
        compact_body = re.sub(r"\s+", "", body)
        compact = re.sub(r"\s+", "", pattern)
        if compact and compact in compact_body:
            idx = compact_body.find(compact)
            tail = body[idx:] if idx >= 0 else ""
            tail = re.sub(rf"^{re.escape(pattern)}\s*[：:]?\s*", "", tail, count=1)
            if _has_substantive(tail[:80]) and not _is_placeholder_value(tail[:80]):
                return True
    return False


def _table_column_has_values(html_chunk: str, label: str) -> bool:
    """表头含该列且至少一行有非占位实质值。"""
    return _table_has_column(html_chunk, label)


def _table_has_column(html_chunk: str, label: str) -> bool:
    if not html_chunk.strip():
        return False
    patterns = _label_patterns(label)
    soup = BeautifulSoup(html_chunk, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = rows[0].get_text(" ", strip=True)
        if not any(p in header_text for p in patterns):
            continue
        data_rows = 0
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            substantive = [c for c in cells if _has_substantive(c) and not _is_placeholder_value(c)]
            if substantive:
                data_rows += 1
        if data_rows >= 1:
            return True
    return False


def _norm_label(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _cell_is_label(cell: str, pattern: str) -> bool:
    cn = _norm_label(cell)
    pn = _norm_label(pattern)
    if cn == pn:
        return True
    raw = _clean_cell(cell)
    return bool(re.match(rf"^\s*{re.escape(pattern)}\s*[：:]?", raw))


def _jcxx_label_value_in_tables(html_chunk: str, label: str) -> bool:
    """仅在 jcxx 章节 HTML 表格中核对标签-值对。"""
    if not html_chunk.strip():
        return False
    patterns = _label_patterns(label)
    soup = BeautifulSoup(html_chunk, "html.parser")
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            for idx, cell in enumerate(cells):
                for pattern in patterns:
                    if not _cell_is_label(cell, pattern):
                        continue
                    if idx + 1 >= len(cells):
                        continue
                    value = cells[idx + 1]
                    if _has_substantive(value) and not _is_placeholder_value(value):
                        return True
    return False


def verify_warning_in_md(warning: dict, md_path: Path) -> str:
    """返回 source_missing | extract_failure | uncertain（仅在 MD 对应章节内核对）。"""
    reason = str(warning.get("reason") or "")
    section = str(warning.get("section") or "")
    label = str(warning.get("label") or "")

    if reason in {"sanitized_control_chars", "alternative_candidate_selected", "pymupdf_extract_failed"}:
        return "uncertain"

    md_text = md_path.read_text(encoding="utf-8")
    plain = read_md_plain_text(md_path)
    section_body = _extract_section_body(plain, section)
    section_html = _md_section_html(md_text, section)

    if reason in {
        "missing_required_columns",
        "unknown_columns",
        "continued_table_without_header",
        "suspiciously_few_rows",
        "text_row_low_confidence",
        "missing_teaching_method",
    }:
        return "extract_failure" if _section_body_has_content(section_body) or section_html.strip() else "source_missing"

    if reason == "validated_text_fallback_used":
        return "extract_failure" if _section_body_has_content(section_body) else "source_missing"

        if reason == "empty_section":
            if section in TABLE_SECTIONS:
                if section_html.strip():
                    soup = BeautifulSoup(section_html, "html.parser")
                    if soup.find("table"):
                        if section == "jxap" and label == "教学安排条目":
                            for table in soup.find_all("table"):
                                header = table.find("tr")
                                if header and any(
                                    token in header.get_text(" ", strip=True).lower()
                                    for token in ("授课内容", "topic", "class", "教学安排", "课程安排")
                                ):
                                    return "extract_failure"
                        else:
                            return "extract_failure"
        if _section_body_has_content(section_body, min_chars=20):
            return "extract_failure"
        return "source_missing"

    if reason == "missing_field":
        if section == "jcxx":
            if _jcxx_label_value_in_tables(section_html, label):
                return "extract_failure"
            return "source_missing"
        if section == "kcmb":
            return "extract_failure" if _label_has_value_in_body(section_body, label) else "source_missing"
        if section in TABLE_SECTIONS:
            if _table_column_has_values(section_html, label):
                return "extract_failure"
            if _table_has_column(section_html, label):
                return "uncertain"
            if not section_html.strip() and not _section_body_has_content(section_body):
                return "source_missing"
            return "uncertain"
        if section == "kcyq":
            return "extract_failure" if _section_body_has_content(section_body) else "source_missing"
        return "uncertain"

    return "uncertain"
