"""Excel column to courses-table column mapping."""

from __future__ import annotations

from config import load_project_config


def _course_library_config() -> dict:
    value = load_project_config().get("course_library", {})
    return value if isinstance(value, dict) else {}


EXCEL_TO_DB_COLUMN: dict[str, str] = dict(_course_library_config().get("excel_to_db_column") or {})
COURSE_DB_COLUMNS: tuple[str, ...] = tuple(EXCEL_TO_DB_COLUMN.values())

