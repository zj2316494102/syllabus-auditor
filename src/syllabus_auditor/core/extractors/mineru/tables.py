"""MinerU HTML 表格归一化：展开 rowspan/colspan、修复标签值粘连。"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from syllabus_auditor.core.extractors.pdfplumber.extractor import (
    BASIC_PAIR_LABELS,
    TEACHER_LABELS,
    clean_text,
    normalize_label,
    table_has_labels,
)

_PAIR_LABELS = sorted(
    set(BASIC_PAIR_LABELS)
    | set(TEACHER_LABELS)
    | {"是否允许外学院选课", "允许外学院选课", "开课院系", "开课(院)系", "开课（院）系"},
    key=len,
    reverse=True,
)

_COURSE_CODE_IN_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}")


def html_table_to_grid(html: str) -> list[list[str | None]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    max_cols = 0
    parsed_rows: list[list[dict[str, Any]]] = []
    for tr in rows:
        cells: list[dict[str, Any]] = []
        for td in tr.find_all(["td", "th"]):
            text = td.get_text(" ", strip=True) or None
            rowspan = int(td.get("rowspan") or 1)
            colspan = int(td.get("colspan") or 1)
            cells.append({"text": text, "rowspan": rowspan, "colspan": colspan})
        parsed_rows.append(cells)
        width = sum(c["colspan"] for c in cells)
        max_cols = max(max_cols, width)

    grid: list[list[str | None]] = [[None] * max_cols for _ in parsed_rows]
    carry: dict[tuple[int, int], str | None] = {}

    for r, cells in enumerate(parsed_rows):
        c = 0
        for cell in cells:
            while c < max_cols and (r, c) in carry:
                grid[r][c] = carry.pop((r, c))
                c += 1
            while c < max_cols and grid[r][c] is not None:
                c += 1
            text = cell["text"]
            colspan = cell["colspan"]
            rowspan = cell["rowspan"]
            for dc in range(colspan):
                if c + dc < max_cols:
                    grid[r][c + dc] = text if dc == 0 else None
            for dr in range(1, rowspan):
                for dc in range(colspan):
                    col = c + dc
                    if col < max_cols:
                        carry[(r + dr, col)] = text
            c += colspan

    return [[clean_text(v) or None for v in row] for row in grid]


def _flex_label_pattern(label: str) -> str:
    normalized = label.replace("(", "（").replace(")", "）")
    return r"\s*".join(re.escape(ch) for ch in normalized)


def _match_label_prefix(text: str, label: str) -> str | None:
    if not text:
        return None
    pattern = rf"^\s*{_flex_label_pattern(label)}\s*[：:]?\s*(.*)$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    if normalize_label(text) == normalize_label(label):
        return ""
    return None


def _find_embedded_label_pos(text: str, labels: list[str]) -> int | None:
    if not text:
        return None
    best: int | None = None
    for label in labels:
        for match in re.finditer(_flex_label_pattern(label), text):
            if match.start() <= 0:
                continue
            if best is None or match.start() < best:
                best = match.start()
    return best


def _canonical_pair_label(label: str) -> str:
    if normalize_label(label) in {normalize_label("允许外学院选课"), normalize_label("是否允许外学院选课")}:
        return "是否允许外学院选课"
    if normalize_label(label) in {normalize_label("开课院系"), normalize_label("开课(院)系"), normalize_label("开课（院）系")}:
        return "开课（院）系"
    return label


def _scan_text_label_pairs(text: str, labels: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match_info: tuple[str, re.Match[str]] | None = None
        for label in labels:
            pattern = rf"^\s*{_flex_label_pattern(label)}\s*[：:]?\s*"
            match = re.match(pattern, text[pos:], re.DOTALL)
            if match and (match_info is None or len(label) > len(match_info[0])):
                match_info = (label, match)
        if match_info is None:
            break
        label, match = match_info
        pos += match.end()
        next_start = len(text)
        embedded = _find_embedded_label_pos(text[pos:], labels)
        if embedded is not None:
            next_start = pos + embedded
        value = clean_text(text[pos:next_start])
        pairs.append((_canonical_pair_label(label), value))
        pos = next_start
    return pairs


def _split_glued_pair_value(first_label: str, raw_value: str, labels: list[str]) -> list[tuple[str, str]]:
    value = clean_text(raw_value)
    if not value:
        return [(first_label, "")]

    results: list[tuple[str, str]] = []
    text = value

    if normalize_label(first_label) == normalize_label("课程编号"):
        code_match = _COURSE_CODE_IN_VALUE.match(text)
        if code_match:
            results.append((first_label, code_match.group(0)))
            text = text[code_match.end() :].strip()

    if not text:
        return results if results else [(first_label, value)]

    if not results:
        return [(first_label, value)]

    results.extend(_scan_text_label_pairs(text, labels))
    return results


def scan_row_label_pairs(cells: list[str | None], labels: list[str] | None = None) -> list[tuple[str, str]]:
    texts = [clean_text(c) for c in cells if clean_text(c)]
    labels = labels or _PAIR_LABELS
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(texts):
        matched = False
        for label in labels:
            remainder = _match_label_prefix(texts[i], label)
            if remainder is None:
                continue
            i += 1
            value_parts = [remainder] if remainder else []
            while i < len(texts):
                if any(_match_label_prefix(texts[i], candidate) is not None for candidate in labels):
                    break
                value_parts.append(texts[i])
                i += 1
            value = clean_text("".join(value_parts))
            for sub_label, sub_value in _split_glued_pair_value(label, value, labels):
                pairs.append((_canonical_pair_label(sub_label), sub_value))
            matched = True
            break
        if not matched:
            i += 1
    return pairs


def repair_pair_table(table: list[list[str | None]]) -> list[list[str | None]]:
    if not table:
        return table
    flat_text = "".join(normalize_label(c) for row in table for c in row if c)
    triggers = (
        "课程编号",
        "周学时",
        "教师工号",
        "任课教师姓名",
        "中文课程名称",
        "英文课程名称",
        "开课（院）系",
        "开课(院)系",
        "开课院系",
    )
    looks_like_pair = any(normalize_label(label) in flat_text for label in triggers)
    if not looks_like_pair:
        for row in table[:4]:
            if scan_row_label_pairs(row):
                looks_like_pair = True
                break
    if not looks_like_pair:
        return table

    repaired: list[list[str | None]] = []
    for row in table:
        pairs = scan_row_label_pairs(row)
        if pairs:
            flat: list[str | None] = []
            for key, value in pairs:
                flat.extend([key, value or None])
            repaired.append(flat)
        else:
            repaired.append([clean_text(c) or None for c in row])
    return repaired


def normalize_mineru_tables(tables: list[list[list[str | None]]]) -> list[list[list[str | None]]]:
    normalized: list[list[list[str | None]]] = []
    seen: set[str] = set()
    for table in tables:
        if not table:
            continue
        fixed = repair_pair_table(table)
        key = "|".join("|".join(clean_text(c) for c in row if c) for row in fixed)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(fixed)
    return normalized
