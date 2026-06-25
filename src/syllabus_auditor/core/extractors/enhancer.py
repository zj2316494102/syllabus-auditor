from __future__ import annotations

from pathlib import Path
from typing import Any

from config import load_extraction_config
from syllabus_auditor.core.extractors.fusion import (
    ExtractionCandidate,
    choose_candidate,
    make_row_candidate,
    section_summary,
)
from syllabus_auditor.core.extractors.layout import layout_to_text
from syllabus_auditor.core.extractors.pymupdf import PyMuPdfUnavailable, extract_layout
from syllabus_auditor.core.extractors.text_candidates import build_text_candidates, extract_section
from syllabus_auditor.core.types import ExtractionRaw


def _config() -> dict[str, Any]:
    return load_extraction_config()


def _validated_rules() -> list[dict[str, Any]]:
    return list(_config().get("validated_text_rules", []))


def _configured_titles(section_key: str) -> tuple[str, ...]:
    titles = _config().get("section_titles", {}).get(section_key, [])
    return tuple(str(item) for item in titles if str(item).strip())


def _append_warning(raw: ExtractionRaw, section: str, reason: str, **extra: Any) -> None:
    warning = {"section": section, "reason": reason}
    warning.update(extra)
    raw.extraction_warnings.append(warning)


def _current_candidates(raw: ExtractionRaw) -> dict[str, ExtractionCandidate]:
    return {
        "teaching_content": make_row_candidate(
            "teaching_content",
            "pdfplumber_table",
            raw.teaching_content,
            ("序号", "主题", "知识点", "学时"),
        ),
        "course_schedule": make_row_candidate(
            "course_schedule",
            "pdfplumber_table",
            raw.course_schedule,
            ("序号", "授课内容"),
        ),
        "assessment_rows": make_row_candidate(
            "assessment_rows",
            "pdfplumber_table",
            raw.assessment_rows,
            ("考试形式", "占比"),
        ),
        "course_requirements": make_row_candidate(
            "course_requirements",
            "pdfplumber_table",
            raw.course_requirements,
            (),
        ),
    }


def _candidate_sources(raw: ExtractionRaw, pdf_path: Path) -> tuple[list[dict[str, Any]], str]:
    sources: list[dict[str, Any]] = []
    pdfplumber_candidate = build_text_candidates(raw.full_text, "pdfplumber_text")
    pdfplumber_candidate["source_text"] = raw.full_text
    sources.append(pdfplumber_candidate)

    try:
        pages = extract_layout(pdf_path)
    except PyMuPdfUnavailable:
        pass
    except Exception as exc:  # pragma: no cover - defensive, keeps PDF import alive.
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
    selected = choose_candidate(current, candidates)
    all_candidates = [current, *candidates]
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
        raw.extraction_warnings.append({"section": section_key, **warning})
    return selected


def enhance_raw_extraction(raw: ExtractionRaw, pdf_path: Path) -> ExtractionRaw:
    current = _current_candidates(raw)
    sources, pymupdf_status = _candidate_sources(raw, pdf_path)
    raw.section_extraction["pymupdf"] = {"status": pymupdf_status}

    for section_key in ("teaching_content", "course_schedule", "assessment_rows", "course_requirements"):
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
        elif section_key == "course_requirements":
            raw.course_requirements = selected.rows

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
            _configured_titles("course_goal"),
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

