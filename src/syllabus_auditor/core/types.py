from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExtractionRaw:
    """PDF 抽取中间结果（中文字段）。"""

    cn_data: dict[str, Any]
    full_text: str
    raw_pages: list[str]
    page_count: int
    teaching_content: list[dict[str, str]] = field(default_factory=list)
    course_schedule: list[dict[str, str]] = field(default_factory=list)
    assessment_rows: list[dict[str, str]] = field(default_factory=list)
    course_requirements: list[dict[str, Any]] = field(default_factory=list)
    course_goal_extras: dict[str, str] = field(default_factory=dict)
    extraction_warnings: list[dict[str, Any]] = field(default_factory=list)
    source_path: Path | None = None


@dataclass(slots=True)
class PrepareSummary:
    total: int = 0
    success: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class CourseLibrarySummary:
    total: int = 0
    imported: int = 0
    skipped: int = 0
