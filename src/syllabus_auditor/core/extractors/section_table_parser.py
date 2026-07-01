"""通用章节表格解析（教学内容/安排/考核等复杂表格）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from syllabus_auditor.shared.config import load_project_config


def _extraction_params() -> dict[str, Any]:
    value = load_project_config().get("extraction_params", {})
    return value if isinstance(value, dict) else {}


def _table_parser_cfg() -> dict[str, Any]:
    value = load_project_config().get("table_parser", {})
    return value if isinstance(value, dict) else {}


def clean_text(value: str | None, keep_newline: bool = False) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r" *\n *", "\n" if keep_newline else "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def join_text(existing: str, addition: str) -> str:
    existing = clean_text(existing, keep_newline=True)
    addition = clean_text(addition, keep_newline=True)
    if not existing:
        return addition
    if not addition:
        return existing
    return f"{existing}\n{addition}"


def normalize_label(value: str | None) -> str:
    text = clean_text(value)
    pattern = str(_extraction_params().get("label_normalize_pattern") or r"[\s:：；;，,、（）()【】\[\]《》<>“”\"'·\-—_]+")
    text = re.sub(pattern, "", text)
    return text.lower()


def is_sequence(value: str | None) -> bool:
    text = clean_text(value)
    if not text:
        return False
    pattern = str(_extraction_params().get("sequence_pattern") or r"(?:第)?\d+(?:\.\d+)?(?:[-－—~～至]\d+(?:\.\d+)?)?(?:周|次|讲|节|课时)?")
    return bool(re.fullmatch(pattern, text))


def is_summary_row(row: list[str | None]) -> bool:
    text = "".join(clean_text(cell) for cell in row if cell)
    markers = _extraction_params().get("summary_row_markers") or ("课时总计", "学时总计", "总学时", "合计")
    return any(marker in text for marker in markers)


def strip_summary_fragments(row: list[str | None]) -> list[str]:
    markers = _extraction_params().get("summary_row_markers") or ("课时总计", "学时总计", "总学时", "合计")
    practice_pattern = str(
        _extraction_params().get("practice_line_pattern") or r"\d+\s*[（(]课程教授与实践(?:课)?[）)]"
    )
    cleaned_row: list[str] = []
    for cell in row:
        lines = clean_text(cell, keep_newline=True).splitlines()
        kept = [
            line
            for line in lines
            if not any(marker in line for marker in markers)
            and not re.fullmatch(practice_pattern, clean_text(line))
        ]
        cleaned_row.append("\n".join(kept))
    return cleaned_row


@dataclass(frozen=True)
class SectionProfile:
    name: str
    result_key: str
    fields: dict[str, tuple[str, ...]]
    required: tuple[str, ...]
    first_field: str | None = None
    min_header_hits: int = 2
    min_cols: int = 2


@dataclass
class ActiveTable:
    profile: SectionProfile
    col_map: dict[int, str]
    headers: dict[int, str]
    col_count: int


PROFILES = [
    SectionProfile(
        name="教学内容",
        result_key="teaching_content",
        first_field="序号",
        required=("主题", "知识点"),
        fields={
            "序号": ("序号", "编号", "章节", "章次"),
            "主题": ("主题", "教学主题", "内容主题", "单元", "章节名称"),
            "知识点": ("知识点", "教学内容", "主要内容", "内容", "讲授内容"),
            "学时": (
                "学时",
                "课时",
                "教学学时",
                "学时课堂讲授",
                "学时讲授",
                "课堂讲授学时",
            ),
        },
    ),
    SectionProfile(
        name="教学安排",
        result_key="course_schedule",
        first_field="序号",
        required=("授课内容", "授课方式"),
        fields={
            "序号": ("序号", "课程", "课程周", "周次", "时间", "周", "课次", "class"),
            "授课内容": (
                "授课内容",
                "课程内容",
                "课程主题",
                "讲授内容",
                "教学内容",
                "主要内容",
                "topic/reading",
                "topic",
                "reading",
            ),
            "授课方式": ("授课方式", "教学方式", "讲授方式", "教学方法", "授课形式"),
            "思政元素的融入和预期教学成效": (
                "思政元素的融入和预期教学成效",
                "思政元素和预期教学成效",
                "思政元素的融入及预期教学成效",
                "思政元素融入和预期教学成效",
                "融入的思政元素和预期教学成效",
                "课程思政元素的融入",
                "思政元素",
                "预期教学成效",
                "课程思政",
                "思政融入",
                "思政元素融入",
            ),
        },
    ),
    SectionProfile(
        name="考核方式",
        result_key="assessment_rows",
        first_field="考试形式",
        required=("考试形式",),
        fields={
            "考试形式": (
                "考试形式",
                "考核形式",
                "考核方式",
                "考核环节",
                "考核项目",
                "项目",
                "成绩构成",
                "平时成绩",
                "期末成绩",
            ),
            "考察内容": ("考察内容", "考核内容", "内容", "评价内容", "要求"),
            "考察方式": ("考察方式", "方式", "评价方式"),
            "占比": ("占比", "比例", "权重", "成绩占比", "分值比例"),
            "分值": ("分值", "成绩分值", "分数", "满分", "价值"),
        },
    ),
]


def _cell(row: list[str | None], index: int) -> str:
    if index >= len(row):
        return ""
    return clean_text(row[index], keep_newline=True)


_HEADER_FALSE_POSITIVE = {
    "主题": ("报告", "会议", "名称"),
    "知识点": ("报告", "会议"),
}


def _alias_matches_header(alias_norm: str, normalized: str) -> bool:
    if not alias_norm or not normalized:
        return False
    if alias_norm == normalized:
        return True
    if len(alias_norm) <= 2:
        return normalized.startswith(alias_norm) and len(normalized) <= len(alias_norm) + 1
    if len(alias_norm) >= 4 and alias_norm in normalized:
        return True
    if len(normalized) >= 4 and normalized in alias_norm:
        return True
    return False


def _header_match_variants(header: str) -> list[str]:
    """表头匹配变体：去括号说明、按顿号拆分粘连列名。"""
    text = clean_text(header)
    if not text:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        value = clean_text(value)
        if not value or value in seen:
            return
        seen.add(value)
        variants.append(value)

    _add(text)
    stripped = re.sub(r"[（(][^）)]*[）)]", "", text)
    stripped = re.sub(r"\s+", "", stripped)
    if stripped:
        _add(stripped)
    if any(sep in text for sep in ("、", "，", ",", "；", ";", "/")):
        for part in re.split(r"[、，,；;/]+", text):
            part = re.sub(r"[（(][^）)]*[）)]", "", part)
            _add(part)
    return variants


_GOAL_HEADER_LABELS = frozenset({"思政目标", "能力目标", "知识目标", "课程目标", "成长目标"})


def _is_course_goal_header_row(row: list[str | None]) -> bool:
    """2 列「目标 | 长文本」课程目标表，不应识别为教学安排。"""
    if len(row) > 2:
        return False
    label = clean_text(row[0] if row else None)
    if not label or len(label) > int(_table_parser_cfg().get("pair_label_max_len", 24)):
        return False
    if label in _GOAL_HEADER_LABELS:
        return True
    return label.endswith("目标") and "授课" not in label and "周" not in label


def _score_jxap_candidate(
    *,
    col_count: int,
    col_map: dict[int, str],
    hits: int,
    required_hits: int,
) -> int | None:
    mapped = set(col_map.values())
    if "授课内容" not in mapped:
        return None
    score = hits * 10 + required_hits
    if "授课方式" in mapped:
        score += 8
    if "序号" in mapped:
        score += 5
    if "授课方式" not in mapped:
        score -= 18
    if "序号" not in mapped:
        score -= 6
    if col_count <= 2:
        score -= 40
    elif col_count == 3 and "授课方式" not in mapped:
        score -= 12
    return score


def _field_for_header(profile: SectionProfile, header: str) -> str | None:
    best_field: str | None = None
    best_len = 0
    for variant in _header_match_variants(header):
        header_flat = re.sub(r"\s+", "", variant or "")
        if profile.name == "教学安排" and any(
            token in header_flat
            for token in ("思政", "预期教学成效", "课程思政", "思政元素", "思政融入")
        ):
            return "思政元素的融入和预期教学成效"

        normalized = normalize_label(variant)
        if not normalized:
            continue

        for field, aliases in profile.fields.items():
            for alias in aliases:
                alias_norm = normalize_label(alias)
                if not alias_norm:
                    continue
                if not _alias_matches_header(alias_norm, normalized):
                    continue
                if field in _HEADER_FALSE_POSITIVE and any(
                    token in header_flat for token in _HEADER_FALSE_POSITIVE[field]
                ):
                    continue
                if len(alias_norm) > best_len:
                    best_field = field
                    best_len = len(alias_norm)
    return best_field


def _detect_header(
    table: list[list[str | None]],
    active: ActiveTable | None,
) -> tuple[ActiveTable | None, int, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    scan_limit = min(3, len(table))
    best: tuple[int, int, SectionProfile, dict[int, str], dict[int, str]] | None = None
    for row_index in range(scan_limit):
        row = table[row_index]
        col_count = len(row)
        if col_count < 2:
            continue
        for profile in PROFILES:
            if col_count < profile.min_cols:
                continue
            col_map: dict[int, str] = {}
            headers: dict[int, str] = {}
            for col_index, raw_header in enumerate(row):
                header = clean_text(raw_header)
                field = _field_for_header(profile, header)
                if field:
                    col_map[col_index] = field
                    headers[col_index] = header or field
                elif header:
                    headers[col_index] = header
            hits = len(set(col_map.values()))
            required_hits = sum(1 for field in profile.required if field in col_map.values())
            if profile.name == "教学安排":
                if _is_course_goal_header_row(row):
                    continue
                required_ok = "授课内容" in col_map.values()
                if not required_ok or hits < profile.min_header_hits:
                    continue
                score = _score_jxap_candidate(
                    col_count=col_count,
                    col_map=col_map,
                    hits=hits,
                    required_hits=required_hits,
                )
                if score is None or score < profile.min_header_hits * 10:
                    continue
            elif profile.name == "考核方式":
                required_ok = (
                    "考试形式" in col_map.values()
                    or (
                        "考察内容" in col_map.values()
                        and ("分值" in col_map.values() or "占比" in col_map.values())
                    )
                    or (
                        "考察方式" in col_map.values()
                        and ("分值" in col_map.values() or "占比" in col_map.values())
                    )
                    or (
                        ("分值" in col_map.values() or "占比" in col_map.values())
                        and hits >= 1
                        and _looks_like_assessment_table(table)
                    )
                )
                if not required_ok or hits < profile.min_header_hits:
                    continue
                score = hits * 10 + required_hits
            else:
                required_ok = required_hits == len(profile.required)
                if not required_ok or hits < profile.min_header_hits:
                    continue
                score = hits * 10 + required_hits
            if best is None or score > best[0]:
                best = (score, row_index, profile, col_map, headers)

    if best is not None:
        _, row_index, profile, col_map, headers = best
        if (
            active
            and active.profile.name == profile.name
            and row_index == 0
            and is_sequence(_cell(table[0], 0))
        ):
            return active, 0, []
        missing = [field for field in profile.required if field not in col_map.values()]
        if missing:
            warnings.append(
                {
                    "section": profile.name,
                    "reason": "missing_required_columns",
                    "fields": missing,
                }
            )
        unknown_headers = [
            header
            for index, header in headers.items()
            if header and index not in col_map and normalize_label(header)
        ]
        if unknown_headers:
            warnings.append(
                {
                    "section": profile.name,
                    "reason": "unknown_columns",
                    "fields": unknown_headers,
                }
            )
        start_row = row_index + 1
        if profile.name == "考核方式":
            col_map, headers = _maybe_infer_khfsb_cols(table, start_row, col_map, headers)
        return ActiveTable(profile, col_map, headers, max(len(row) for row in table)), start_row, warnings

    if active and _looks_like_continuation(table, active):
        return active, 0, []

    return None, 0, warnings


_ASSESSMENT_ROW_MARKERS = (
    "平时成绩",
    "平时作业",
    "期末",
    "闭卷",
    "开卷",
    "论文",
    "考勤",
    "课堂表现",
    "课程报告",
    "答辩",
    "考核",
    "成绩",
)


def _looks_like_assessment_table(table: list[list[str | None]]) -> bool:
    flat = "".join(clean_text(cell) for row in table[:6] for cell in row if cell)
    if not flat:
        return False
    if any(marker in flat for marker in _ASSESSMENT_ROW_MARKERS):
        return True
    header = clean_text(_cell(table[0], 1)) + clean_text(_cell(table[0], 2))
    return header in {"要求分值", "要求价值", "考察内容分值", "考核内容分值"}


def _maybe_infer_khfsb_cols(
    table: list[list[str | None]],
    start_row: int,
    col_map: dict[int, str],
    headers: dict[int, str],
) -> tuple[dict[int, str], dict[int, str]]:
    if 0 in col_map:
        return col_map, headers
    sample_rows = table[start_row : start_row + 4]
    hits = sum(
        1
        for row in sample_rows
        if any(marker in clean_text(_cell(row, 0)) for marker in _ASSESSMENT_ROW_MARKERS)
    )
    if hits == 0:
        return col_map, headers
    inferred = dict(col_map)
    inferred_headers = dict(headers)
    inferred[0] = "考试形式"
    inferred_headers.setdefault(0, "考试形式")
    return inferred, inferred_headers


def _is_jxap_sequence(value: str) -> bool:
    if is_sequence(value):
        return True
    if re.fullmatch(r"\d+", value):
        return True
    if re.search(r"[（(]\s*\d+\s*周\s*[）)]", value):
        return True
    if re.search(r"第[一二三四五六七八九十百千\d]+篇", value):
        return True
    if re.search(r"(导论|绪论|概述)", value) and re.search(r"\d+\s*周", value):
        return True
    return False


def _looks_like_continuation(table: list[list[str | None]], active: ActiveTable) -> bool:
    if not table or not table[0] or len(table[0]) < 2:
        return False
    if active.profile.name == "教学安排":
        if _looks_like_assessment_table(table):
            return False
        if _is_course_goal_header_row(table[0]):
            return False
    col_count = max(len(row) for row in table)
    non_empty_rows = [
        row
        for row in table[:5]
        if any(clean_text(cell) for cell in row)
    ]
    if not non_empty_rows:
        return False

    has_seq = any(is_sequence(_cell(row, 0)) for row in non_empty_rows)
    drift = abs(col_count - active.col_count)

    if drift > int(_table_parser_cfg().get("header_drift_strict", 2)):
        return False
    if drift > int(_table_parser_cfg().get("header_drift_relaxed", 1)) and not has_seq:
        return False

    if active.profile.name == "教学内容":
        xs_col = next((idx for idx, field in active.col_map.items() if field == "学时"), None)
        if xs_col is not None:
            has_hours = any(
                re.fullmatch(r"\d+(?:\.\d+)?", clean_text(row[xs_col] if xs_col < len(row) else None) or "")
                for row in non_empty_rows
            )
            if not has_hours:
                return False

    if has_seq:
        active_fields = set(active.col_map.values())
        sknr_col = next((idx for idx, field in active.col_map.items() if field == "授课内容"), None)
        for sample in non_empty_rows:
            mapped = sum(
                1
                for idx, field in active.col_map.items()
                if field in active_fields and clean_text(_cell(sample, idx))
            )
            if mapped >= max(1, len(active_fields) // 2):
                return True
            if sknr_col is not None and not clean_text(_cell(sample, 0)) and clean_text(_cell(sample, sknr_col)):
                return True
        return False

    return any(
        not clean_text(row[0]) and sum(bool(clean_text(cell)) for cell in row[1:]) >= 1
        for row in non_empty_rows
    )


def _mapped_row(row: list[str | None], active: ActiveTable) -> dict[str, Any]:
    item: dict[str, Any] = {}
    extras: dict[str, str] = {}
    for col_index in range(max(len(row), active.col_count)):
        value = _cell(row, col_index)
        if not value:
            continue
        field = active.col_map.get(col_index)
        if field:
            item[field] = join_text(item.get(field, ""), value)
        else:
            header = active.headers.get(col_index, "")
            if normalize_label(header):
                extras[header] = join_text(extras.get(header, ""), value)
    if extras:
        item["kzzd"] = extras
    return item


def _merge_item(existing: dict[str, Any], addition: dict[str, Any]) -> None:
    for key, value in addition.items():
        if key == "kzzd" and isinstance(value, dict):
            target = existing.setdefault("kzzd", {})
            if isinstance(target, dict):
                for extra_key, extra_value in value.items():
                    target[extra_key] = join_text(str(target.get(extra_key, "")), str(extra_value))
            continue
        if isinstance(value, str):
            existing[key] = join_text(str(existing.get(key, "")), value)


_INVALID_SEQ_MARKERS = (
    "课程中文简介",
    "课程英文简介",
    "课程简介",
    "英文简介",
    "中文简介",
)

FILL_DOWN_FIELDS: dict[str, tuple[str, ...]] = {
    "教学内容": ("序号", "主题", "知识点", "学时"),
    "教学安排": ("序号", "授课内容", "授课方式", "思政元素的融入和预期教学成效"),
    "考核方式": ("考试形式", "考察内容", "考察方式", "占比", "分值"),
}


def _row_has_other_content(row: list[str | None], skip_col: int, width: int) -> bool:
    for index in range(width):
        if index == skip_col:
            continue
        if clean_text(row[index] if index < len(row) else None):
            return True
    return False


def _is_valid_data_row(active: ActiveTable, item: dict[str, Any]) -> bool:
    first_field = active.profile.first_field
    if not first_field:
        return True
    seq = clean_text(item.get(first_field))
    if not seq:
        if active.profile.name == "教学安排":
            sknr = clean_text(item.get("授课内容"))
            if not sknr:
                return False
        return True
    if any(marker in seq for marker in _INVALID_SEQ_MARKERS):
        return False
    if active.profile.name in ("教学内容", "教学安排") and not _is_jxap_sequence(seq):
        if active.profile.name == "教学安排" and seq.lower() in {"class", "date", "topic"}:
            return False
        return False
    return True


def _forward_fill_rows(rows: list[list[str | None]], active: ActiveTable) -> list[list[str | None]]:
    """rowspan 展开后子行常缺合并列，按列向下继承上一行的值。"""
    fill_fields = FILL_DOWN_FIELDS.get(active.profile.name)
    if not fill_fields:
        return rows
    col_by_field = {field: idx for idx, field in active.col_map.items()}
    last: dict[str, str] = {}
    filled: list[list[str | None]] = []
    width = active.col_count
    for row in rows:
        new_row = list(row) + [None] * max(0, width - len(row))
        has_any = any(clean_text(cell) for cell in new_row)
        for field in fill_fields:
            col = col_by_field.get(field)
            if col is None:
                continue
            value = clean_text(new_row[col] if col < len(new_row) else None)
            if value:
                last[field] = value
            elif last.get(field) and has_any and _row_has_other_content(new_row, col, width):
                new_row[col] = last[field]
        filled.append(new_row)
    return filled


def _normalize_seq(value: str) -> str:
    parts = [clean_text(p) for p in re.split(r"[\n／/]+", value) if clean_text(p)]
    return parts[0] if parts else ""


def _starts_new_row(active: ActiveTable, item: dict[str, Any], result: list[dict[str, Any]], first_field: str | None) -> bool:
    if not result:
        return True
    if active.profile.name == "考核方式":
        return bool(item.get(first_field or ""))
    first_value = _normalize_seq(str(item.get(first_field or "", ""))) if first_field else ""
    if not first_value:
        return False
    if active.profile.name == "教学安排":
        if not _is_jxap_sequence(first_value):
            return False
    elif not is_sequence(first_value) and not re.fullmatch(r"\d+", first_value):
        return False
    last_value = _normalize_seq(str(result[-1].get(first_field or "", ""))) if first_field else ""
    if last_value and first_value == last_value:
        return False
    return True


def _practice_total_from_row(row: list[str | None]) -> str:
    practice_pattern = str(
        _extraction_params().get("practice_line_pattern") or r"\d+\s*[（(]课程教授与实践(?:课)?[）)]"
    )
    for cell in row:
        for line in clean_text(cell, keep_newline=True).splitlines():
            match = re.fullmatch(practice_pattern, clean_text(line))
            if match:
                leading = re.match(r"(\d+)", clean_text(line))
                if leading:
                    return leading.group(1)
    return ""


def _content_summary_total_from_row(row: list[str | None]) -> str:
    markers = _extraction_params().get("summary_row_markers") or ("课时总计", "学时总计", "总学时", "合计")
    cells = [clean_text(cell, keep_newline=True) for cell in row]
    marker_indexes = [index for index, cell in enumerate(cells) if any(marker in cell for marker in markers)]
    if not marker_indexes:
        return ""

    for index in marker_indexes:
        for line in cells[index].splitlines():
            if not any(marker in line for marker in markers):
                continue
            numbers = re.findall(r"\d+(?:\.\d+)?", line)
            if numbers:
                return numbers[-1]

    for index, cell in enumerate(cells):
        if index in marker_indexes:
            continue
        text = clean_text(cell)
        match = re.fullmatch(r"(?:学时|课时)?\s*(\d+(?:\.\d+)?)\s*(?:学时|课时)?", text)
        if match:
            return match.group(1)
    return ""

def _is_dedicated_content_summary_row(row: list[str | None]) -> bool:
    if not is_summary_row(row):
        return False
    stripped = strip_summary_fragments(row)
    non_empty = [clean_text(cell) for cell in stripped if clean_text(cell)]
    return all(re.fullmatch(r"(?:学时|课时)?\s*\d+(?:\.\d+)?\s*(?:学时|课时)?", cell) for cell in non_empty)

def _append_rows(
    rows: list[list[str | None]],
    active: ActiveTable,
    result: list[dict[str, Any]],
    *,
    content_total_hours: list[str] | None = None,
) -> None:
    first_field = active.profile.first_field
    rows = _forward_fill_rows(rows, active)
    for row in rows:
        if active.profile.name == "教学内容":
            practice_total = _practice_total_from_row(row)
            summary_total = _content_summary_total_from_row(row)
            if practice_total and content_total_hours is not None:
                content_total_hours[:] = [practice_total]
            elif summary_total and content_total_hours is not None:
                content_total_hours[:] = [summary_total]
            if summary_total and _is_dedicated_content_summary_row(row):
                continue
        if active.profile.name == "教学内容" and is_summary_row(row):
            row = strip_summary_fragments(row)
            if not any(clean_text(cell) for cell in row):
                continue
        item = _mapped_row(row, active)
        if not item:
            continue
        if not _is_valid_data_row(active, item):
            continue
        if _starts_new_row(active, item, result, first_field):
            result.append(item)
        else:
            _merge_item(result[-1], item)


def parse_section_tables(tables: list[list[list[str | None]]]) -> dict[str, Any]:
    content_total_hours: list[str] = []
    results: dict[str, Any] = {
        "teaching_content": [],
        "course_schedule": [],
        "assessment_rows": [],
        "content_total_hours": "",
        "warnings": [],
        "continuation_info": [],
    }
    active: ActiveTable | None = None
    for table in tables:
        if not table:
            continue
        if max((len(row) for row in table), default=0) < 2:
            continue

        detected, start_row, warnings = _detect_header(table, active)
        results["warnings"].extend(warnings)
        if not detected:
            active = None
            continue

        if (
            active is not None
            and detected.profile.name == active.profile.name
            and start_row == 0
            and _looks_like_continuation(table, active)
        ):
            results["continuation_info"].append({"section": active.profile.name, "merged": True})

        active = detected
        rows = table[start_row:]
        target = results[active.profile.result_key]
        _append_rows(rows, active, target, content_total_hours=content_total_hours)

    results["content_total_hours"] = content_total_hours[0] if content_total_hours else ""
    results["assessment_rows"] = normalize_assessment_rows(results["assessment_rows"])

    for profile in PROFILES:
        rows = results[profile.result_key]
        if profile.name in ("教学内容", "教学安排") and len(rows) == 1:
            results["warnings"].append(
                {
                    "section": profile.name,
                    "reason": "suspiciously_few_rows",
                    "row_count": len(rows),
                }
            )
    return results


def parse_course_goal_extras(tables: list[list[list[str | None]]]) -> dict[str, str]:
    extras: dict[str, str] = {}
    known = {"思政目标", "能力目标", "知识目标", "课程目标"}
    for table in tables:
        if max((len(row) for row in table), default=0) != 2:
            continue
        for row in table:
            label = clean_text(row[0])
            value = clean_text(row[1], keep_newline=True) if len(row) > 1 else ""
            if label.endswith("目标") and label not in known and value:
                extras[label] = join_text(extras.get(label, ""), value)
    return extras


# --- 考核方式表：分值/占比列归一化 ---

_RATIO_FIELD = "占比"
_SCORE_FIELD = "分值"
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")
_NUMERIC_RE = re.compile(r"^(\d+(?:\.\d+)?)$")


def _parse_weight_value(text: str) -> tuple[float | None, bool]:
    raw = clean_text(text)
    if not raw:
        return None, False
    percent_match = _PERCENT_RE.search(raw)
    if percent_match:
        return float(percent_match.group(1)), True
    numeric_match = _NUMERIC_RE.match(raw.replace(",", ""))
    if numeric_match:
        return float(numeric_match.group(1)), False
    embedded = re.search(r"(\d+(?:\.\d+)?)", raw)
    if embedded and len(raw) <= 8:
        return float(embedded.group(1)), False
    return None, False


def _format_percent(value: float) -> str:
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded))}%"
    return f"{rounded:g}%"


def _format_score(value: float) -> str:
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:g}"


def _looks_like_percent_set(values: list[float]) -> bool:
    if not values:
        return False
    return 95 <= sum(values) <= 105


def normalize_assessment_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统一考核表「分值/占比」列：实质为占比则写入占比；实质为分值则保留分值并换算占比。"""
    if not rows:
        return rows

    normalized: list[dict[str, Any]] = [dict(row) for row in rows]
    for row in normalized:
        legacy_score = clean_text(row.get("分数"))
        if legacy_score and not clean_text(row.get(_SCORE_FIELD)):
            row[_SCORE_FIELD] = legacy_score
        row.pop("分数", None)
    explicit_scores = [clean_text(row.get(_SCORE_FIELD)) for row in normalized]
    ratio_values = [clean_text(row.get(_RATIO_FIELD)) for row in normalized]

    if any(explicit_scores):
        parsed_scores: list[tuple[int, float]] = []
        for index, text in enumerate(explicit_scores):
            number, _ = _parse_weight_value(text)
            if number is not None:
                parsed_scores.append((index, number))
        if parsed_scores:
            total = sum(value for _, value in parsed_scores)
            if total > 0:
                for index, value in parsed_scores:
                    normalized[index][_SCORE_FIELD] = _format_score(value)
                    normalized[index][_RATIO_FIELD] = _format_percent(value / total * 100)
            return normalized

    parsed_ratios: list[tuple[int, float, bool]] = []
    for index, text in enumerate(ratio_values):
        number, explicit_percent = _parse_weight_value(text)
        if number is not None:
            parsed_ratios.append((index, number, explicit_percent))

    if not parsed_ratios:
        return normalized

    if any(explicit for _, _, explicit in parsed_ratios):
        for index, value, _ in parsed_ratios:
            normalized[index][_RATIO_FIELD] = _format_percent(value)
        return normalized

    numbers = [value for _, value, _ in parsed_ratios]
    if _looks_like_percent_set(numbers):
        for index, value, _ in parsed_ratios:
            normalized[index][_RATIO_FIELD] = _format_percent(value)
        return normalized

    total = sum(numbers)
    if total <= 0:
        return normalized

    for index, value, _ in parsed_ratios:
        normalized[index][_SCORE_FIELD] = _format_score(value)
        normalized[index][_RATIO_FIELD] = _format_percent(value / total * 100)

    return normalized
