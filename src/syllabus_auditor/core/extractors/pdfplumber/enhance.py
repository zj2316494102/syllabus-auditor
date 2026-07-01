"""pdfplumber 抽取增强：纯文本候选、多源融合、PyMuPDF 兜底。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from syllabus_auditor.shared.config import load_extraction_config, load_project_config
from syllabus_auditor.core.extractors.pdfplumber.pymupdf_layout import (
    PyMuPdfUnavailable,
    extract_layout,
    layout_to_text,
)
from syllabus_auditor.core.types import ExtractionRaw


# ---------------------------------------------------------------------------
# 融合：候选打分与多源选择
# ---------------------------------------------------------------------------


def _candidate_scoring() -> dict[str, Any]:
    value = load_project_config().get("candidate_scoring", {})
    return value if isinstance(value, dict) else {}


def _extraction_params() -> dict[str, Any]:
    value = load_project_config().get("extraction_params", {})
    return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class ExtractionCandidate:
    section: str
    source: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


def row_completeness(rows: list[dict[str, Any]], required_fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    total = len(rows) * max(len(required_fields), 1)
    hits = sum(1 for row in rows for field in required_fields if str(row.get(field, "")).strip())
    return hits / total


def score_rows(rows: list[dict[str, Any]], required_fields: tuple[str, ...]) -> float:
    scoring = _candidate_scoring()
    row_bonus_cap = int(scoring.get("row_bonus_cap", 20))
    if not rows:
        return 0.0
    complete = row_completeness(rows, required_fields)
    row_bonus = min(len(rows), row_bonus_cap) / row_bonus_cap
    return complete * 80 + row_bonus * row_bonus_cap


def score_rows_weighted(
    rows: list[dict[str, Any]],
    *,
    required: tuple[str, ...],
    weighted: dict[str, int] | None = None,
    min_rows: int = 1,
    warning_penalty: int = 5,
    warnings: list[dict[str, Any]] | None = None,
) -> float:
    scoring_cfg = _candidate_scoring()
    row_bonus_cap = int(scoring_cfg.get("row_bonus_cap", 20))
    row_complete_weight = float(scoring_cfg.get("row_complete_weight", 50.0))
    weighted_field_weight = float(scoring_cfg.get("weighted_field_weight", 30.0))
    if not rows:
        return 0.0

    weighted = weighted or {}
    base = row_completeness(rows, required) * row_complete_weight

    if weighted:
        weight_total = sum(weighted.values()) or 1
        weight_hits = sum(
            weight
            for row in rows
            for field, weight in weighted.items()
            if str(row.get(field, "")).strip()
        )
        base += (weight_hits / (len(rows) * weight_total)) * weighted_field_weight

    row_bonus = min(len(rows), row_bonus_cap) / row_bonus_cap * row_bonus_cap
    if len(rows) < min_rows:
        base *= len(rows) / max(min_rows, 1)

    penalty = len(warnings or []) * int(scoring_cfg.get("warning_penalty", warning_penalty))
    return max(base + row_bonus - penalty, 0.0)


def make_row_candidate(
    section: str,
    source: str,
    rows: list[dict[str, Any]],
    required_fields: tuple[str, ...],
    *,
    warnings: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    scoring_config: dict[str, Any] | None = None,
) -> ExtractionCandidate:
    if scoring_config:
        score = score_rows_weighted(
            rows,
            required=tuple(scoring_config.get("required") or required_fields),
            weighted=scoring_config.get("weighted") or {},
            min_rows=int(scoring_config.get("min_rows", 1)),
            warnings=warnings,
        )
    else:
        score = score_rows(rows, required_fields)

    return ExtractionCandidate(
        section=section,
        source=source,
        rows=rows,
        warnings=list(warnings or []),
        evidence=dict(evidence or {}),
        score=score,
    )


def apply_fusion_scoring(
    candidate: ExtractionCandidate,
    scoring_config: dict[str, Any] | None,
    *,
    required_fields: tuple[str, ...] = (),
) -> ExtractionCandidate:
    if not scoring_config:
        return candidate
    candidate.score = score_rows_weighted(
        candidate.rows,
        required=tuple(scoring_config.get("required") or required_fields),
        weighted=scoring_config.get("weighted") or {},
        min_rows=int(scoring_config.get("min_rows", 1)),
        warnings=candidate.warnings,
    )
    return candidate


def choose_candidate(
    current: ExtractionCandidate,
    alternatives: list[ExtractionCandidate],
    *,
    min_improvement: float | None = None,
) -> ExtractionCandidate:
    if min_improvement is None:
        min_improvement = float(_candidate_scoring().get("default_min_improvement", 8.0))
    selected = current
    for candidate in alternatives:
        if candidate.score <= 0:
            continue
        if selected.score <= 0 or candidate.score >= selected.score + min_improvement:
            selected = candidate
    return selected


def section_summary(selected: ExtractionCandidate, candidates: list[ExtractionCandidate]) -> dict[str, Any]:
    return {
        "selected_source": selected.source,
        "selected_score": round(selected.score, 2),
        "candidate_scores": [
            {
                "source": candidate.source,
                "score": round(candidate.score, 2),
                "rows": len(candidate.rows),
                "warnings": candidate.warnings,
            }
            for candidate in candidates
        ],
        "evidence": selected.evidence,
    }


# ---------------------------------------------------------------------------
# 文本候选：纯文本章节解析
# ---------------------------------------------------------------------------

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
    params = _extraction_params()
    prefix = str(params.get("title_regex_prefix") or "")
    suffix = str(params.get("title_regex_suffix") or "")
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
    line_pattern = str(_extraction_params().get("teaching_content_line_pattern") or "")
    excerpt_len = int(_extraction_params().get("section_excerpt_max_len", 500))
    for line in section.splitlines():
        if _is_noise_line(line):
            continue
        match = re.match(line_pattern, line) if line_pattern else None
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
        evidence={"section_title": "教学内容", "section_excerpt": section[:excerpt_len]},
    )


def parse_course_schedule(text: str, source: str) -> ExtractionCandidate:
    section = extract_section(text, _configured_titles("course_schedule"))
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    params = _extraction_params()
    schedule_pattern = str(params.get("course_schedule_line_pattern") or "")
    fallback_pattern = str(params.get("course_schedule_fallback_line_pattern") or "")
    method_keywords = params.get("teaching_method_keywords") or []
    method_pattern = "|".join(re.escape(str(item)) for item in method_keywords if str(item).strip())
    excerpt_len = int(params.get("section_excerpt_max_len", 500))
    for line in section.splitlines():
        if _is_noise_line(line):
            continue
        match = re.match(schedule_pattern, line) if schedule_pattern else None
        if not match and fallback_pattern:
            match = re.match(fallback_pattern, line)
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
            method_match = re.search(rf"({method_pattern})", rest) if method_pattern else None
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
        evidence={"section_title": "教学安排", "section_excerpt": section[:excerpt_len]},
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
    return {
        "teaching_content": parse_teaching_content(text, source),
        "course_schedule": parse_course_schedule(text, source),
        "assessment_rows": parse_assessment(text, source),
        "goal_fields": parse_goal_fields(text),
    }


# ---------------------------------------------------------------------------
# 增强器：pdfplumber 抽取增强与 PyMuPDF 兜底
# ---------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    return load_extraction_config()


def _validated_rules() -> list[dict[str, Any]]:
    return list(_config().get("validated_text_rules", []))


def _section_titles(section_key: str) -> tuple[str, ...]:
    titles = _config().get("section_titles", {}).get(section_key, [])
    return tuple(str(item) for item in titles if str(item).strip())


def _fusion_scoring(section_key: str) -> dict[str, Any]:
    cfg = load_project_config().get("fusion_scoring", {})
    if not isinstance(cfg, dict):
        return {}
    value = cfg.get(section_key, {})
    return value if isinstance(value, dict) else {}


def _append_warning(raw: ExtractionRaw, section: str, reason: str, **extra: Any) -> None:
    severity = _default_warning_severity(reason)
    warning = {"section": section, "reason": reason, "severity": severity}
    warning.update(extra)
    raw.extraction_warnings.append(warning)


def _default_warning_severity(reason: str) -> str:
    mapping = load_project_config().get("warning_severity", {})
    if isinstance(mapping, dict) and reason in mapping:
        return str(mapping[reason])
    return "error"


def _current_candidates(raw: ExtractionRaw) -> dict[str, ExtractionCandidate]:
    sections = {
        "teaching_content": (raw.teaching_content, ("序号", "主题", "知识点", "学时")),
        "course_schedule": (raw.course_schedule, ("序号", "授课内容")),
        "assessment_rows": (raw.assessment_rows, ("考试形式", "占比")),
    }
    candidates: dict[str, ExtractionCandidate] = {}
    for section_key, (rows, required_fields) in sections.items():
        scoring = _fusion_scoring(section_key)
        candidate = make_row_candidate(
            section_key,
            "pdfplumber_table",
            rows,
            required_fields,
            scoring_config=scoring or None,
        )
        candidates[section_key] = apply_fusion_scoring(candidate, scoring, required_fields=required_fields)
    return candidates


def _candidate_sources(raw: ExtractionRaw, pdf_path: Path) -> tuple[list[dict[str, Any]], str]:
    sources: list[dict[str, Any]] = []
    pdfplumber_candidate = build_text_candidates(raw.full_text, "pdfplumber_text")
    pdfplumber_candidate["source_text"] = raw.full_text
    sources.append(pdfplumber_candidate)

    try:
        pages = extract_layout(pdf_path)
    except PyMuPdfUnavailable:
        pass
    except Exception as exc:  # pragma: no cover - 防御性兜底，避免 PDF 导入失败
        _append_warning(raw, "pdf", "pymupdf_extract_failed", message=str(exc))
    else:
        layout_text = layout_to_text(pages)
        if layout_text and layout_text != raw.full_text:
            layout_candidate = build_text_candidates(layout_text, "pymupdf_layout")
            layout_candidate["source_text"] = layout_text
            sources.append(layout_candidate)
        return sources, "enabled"

    return sources, "unavailable"


def _select_rows(
    raw: ExtractionRaw,
    section_key: str,
    current: ExtractionCandidate,
    candidates: list[ExtractionCandidate],
) -> ExtractionCandidate:
    scoring = _fusion_scoring(section_key)
    required = tuple(scoring.get("required") or ())
    min_improvement = float(scoring.get("min_improvement", 8.0))

    scored_current = apply_fusion_scoring(current, scoring, required_fields=required)
    scored_candidates = [
        apply_fusion_scoring(candidate, scoring, required_fields=required)
        for candidate in candidates
    ]

    selected = choose_candidate(scored_current, scored_candidates, min_improvement=min_improvement)
    all_candidates = [scored_current, *scored_candidates]
    raw.section_extraction[section_key] = section_summary(selected, all_candidates)
    if selected.source != current.source:
        _append_warning(
            raw,
            section_key,
            "alternative_candidate_selected",
            source=selected.source,
            score=round(selected.score, 2),
        )
    for warning in selected.warnings:
        item = {"section": section_key, **warning}
        if "severity" not in item:
            item["severity"] = _default_warning_severity(str(warning.get("reason") or ""))
        raw.extraction_warnings.append(item)
    return selected


def enhance_raw_extraction(raw: ExtractionRaw, pdf_path: Path) -> ExtractionRaw:
    current = _current_candidates(raw)
    sources, pymupdf_status = _candidate_sources(raw, pdf_path)
    raw.section_extraction["pymupdf"] = {"status": pymupdf_status}

    for section_key in ("teaching_content", "course_schedule", "assessment_rows"):
        selected = _select_rows(
            raw,
            section_key,
            current[section_key],
            [source[section_key] for source in sources if section_key in source],
        )
        if selected.source == current[section_key].source:
            continue
        if section_key == "teaching_content":
            raw.teaching_content = selected.rows
        elif section_key == "course_schedule":
            raw.course_schedule = selected.rows
        elif section_key == "assessment_rows":
            raw.assessment_rows = selected.rows

    _fill_validated_text_fallbacks(raw, sources)
    return raw


def _fill_validated_text_fallbacks(raw: ExtractionRaw, sources: list[dict[str, Any]]) -> None:
    for source in sources:
        source_text = str(source.get("source_text") or "")
        if not source_text:
            continue
        source_name = str(source.get("source") or "text_fallback")

        for rule in _validated_rules():
            field = str(rule["field"])
            if str(raw.cn_data.get(field, "")).strip():
                continue
            excerpt = _validated_section_excerpt(
                source_text,
                tuple(rule["titles"]),
                tuple(rule["keywords"]),
                min_len=int(rule.get("min_len", 12)),
            )
            if not excerpt:
                continue
            raw.cn_data[field] = excerpt
            raw.section_extraction[str(rule["meta_key"])] = {
                "source": source_name,
                "field": field,
                "text": excerpt[:500],
                "validated": True,
                "section_hint": str(rule["titles"][0]),
            }
            _append_warning(
                raw,
                str(rule["warning_section"]),
                "validated_text_fallback_used",
                field=field,
                source=source_name,
            )

    _fill_goal_fields(raw)


def _fill_goal_fields(raw: ExtractionRaw) -> None:
    split_fields = ("思政目标", "能力目标", "知识目标")
    if any(str(raw.cn_data.get(key, "")).strip() for key in split_fields):
        return
    overview = str(raw.cn_data.get("课程目标概述", "")).strip()
    if overview:
        return
    for source_text in _text_sources(raw):
        excerpt = _validated_section_excerpt(
            source_text,
            _section_titles("course_goal"),
            ("思政", "能力", "知识", "价值", "育人", "目标"),
            min_len=8,
        )
        if not excerpt:
            continue
        raw.cn_data["课程目标概述"] = excerpt
        raw.section_extraction["course_goal_text_fallback"] = {
            "source": "validated_text_fallback",
            "field": "课程目标概述",
            "text": excerpt[:500],
            "validated": True,
            "section_hint": "课程目标",
        }
        _append_warning(raw, "course_goal", "validated_text_fallback_used", field="课程目标概述", source="validated_text_fallback")
        break


def _validated_section_excerpt(text: str, titles: tuple[str, ...], keywords: tuple[str, ...], *, min_len: int = 12) -> str:
    section = extract_section(text, titles)
    body = str(section or "").strip()
    if len(body) < min_len:
        return ""
    if not any(keyword in body for keyword in keywords):
        return ""
    return body


def _text_sources(raw: ExtractionRaw) -> list[str]:
    sources = [raw.full_text]
    sources.extend(raw.raw_pages)
    for segment in raw.extraction_warnings:
        text = str(segment.get("text") or "")
        if text:
            sources.append(text)
    return [text for text in sources if text]
