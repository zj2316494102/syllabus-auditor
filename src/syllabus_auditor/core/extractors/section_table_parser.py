from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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
    text = re.sub(r"[\s:：；;，,、（）()【】\[\]《》<>“”\"'·\-—_]+", "", text)
    return text.lower()


def is_sequence(value: str | None) -> bool:
    text = clean_text(value)
    if not text:
        return False
    return bool(
        re.fullmatch(
            r"(?:第)?\d+(?:\.\d+)?(?:[-－—~～至]\d+(?:\.\d+)?)?(?:周|次|讲|节|课时)?",
            text,
        )
    )


def is_summary_row(row: list[str | None]) -> bool:
    text = "".join(clean_text(cell) for cell in row if cell)
    return any(marker in text for marker in ("课时总计", "学时总计", "总学时", "合计"))


def strip_summary_fragments(row: list[str | None]) -> list[str]:
    cleaned_row: list[str] = []
    for cell in row:
        lines = clean_text(cell, keep_newline=True).splitlines()
        kept = [
            line
            for line in lines
            if not any(marker in line for marker in ("课时总计", "学时总计", "总学时", "合计"))
            and not re.fullmatch(r"\d+\s*[（(]课程教授与实践课[）)]", clean_text(line))
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
            "学时": ("学时", "课时", "教学学时"),
        },
    ),
    SectionProfile(
        name="教学安排",
        result_key="course_schedule",
        first_field="序号",
        required=("授课内容", "授课方式"),
        fields={
            "序号": ("序号", "课程", "课程周", "周次", "时间", "周", "课次"),
            "授课内容": ("授课内容", "讲授内容", "教学内容", "主要内容"),
            "授课方式": ("授课方式", "教学方式", "讲授方式", "教学方法", "授课形式"),
            "作业": ("作业", "作业测验", "作业/测验", "课后作业", "学习任务", "任务"),
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
            "考试形式": ("考试形式", "考核形式", "考核环节", "考核项目", "项目", "成绩构成"),
            "考察内容": ("考察内容", "考核内容", "内容", "评价内容"),
            "考察方式": ("考察方式", "考核方式", "方式", "评价方式"),
            "占比": ("占比", "比例", "权重", "成绩占比", "分值比例"),
        },
    ),
]


def _cell(row: list[str | None], index: int) -> str:
    if index >= len(row):
        return ""
    return clean_text(row[index], keep_newline=True)


def _field_for_header(profile: SectionProfile, header: str) -> str | None:
    normalized = normalize_label(header)
    if not normalized:
        return None

    header_flat = re.sub(r"\s+", "", header or "")
    if profile.name == "教学安排" and any(
        token in header_flat
        for token in ("思政", "预期教学成效", "课程思政", "思政元素", "思政融入")
    ):
        return "思政元素的融入和预期教学成效"

    best_field: str | None = None
    best_len = 0
    for field, aliases in profile.fields.items():
        for alias in aliases:
            alias_norm = normalize_label(alias)
            if not alias_norm:
                continue
            if alias_norm == normalized or alias_norm in normalized or (
                len(normalized) >= 4 and normalized in alias_norm
            ):
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
            if hits >= profile.min_header_hits and required_hits:
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
        return ActiveTable(profile, col_map, headers, max(len(row) for row in table)), row_index + 1, warnings

    if active and _looks_like_continuation(table, active):
        return active, 0, []

    return None, 0, warnings


def _looks_like_continuation(table: list[list[str | None]], active: ActiveTable) -> bool:
    if not table or not table[0] or len(table[0]) < 2:
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

    if drift > 4:
        return False
    if drift > 2 and not has_seq:
        return False

    if has_seq:
        return True
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


def _append_rows(rows: list[list[str | None]], active: ActiveTable, result: list[dict[str, Any]]) -> None:
    first_field = active.profile.first_field
    for row in rows:
        if active.profile.name == "教学内容" and is_summary_row(row):
            row = strip_summary_fragments(row)
            if not any(clean_text(cell) for cell in row):
                continue
        item = _mapped_row(row, active)
        if not item:
            continue
        first_value = str(item.get(first_field or "", "")) if first_field else ""
        starts_new = bool(first_value and (is_sequence(first_value) or not result))
        if active.profile.name == "考核方式" and first_value:
            starts_new = True

        if starts_new or not result:
            result.append(item)
        else:
            _merge_item(result[-1], item)


def parse_section_tables(tables: list[list[list[str | None]]]) -> dict[str, Any]:
    results: dict[str, Any] = {
        "teaching_content": [],
        "course_schedule": [],
        "assessment_rows": [],
        "course_requirements": [],
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
        _append_rows(rows, active, target)

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
