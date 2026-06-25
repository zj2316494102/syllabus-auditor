from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from config import load_project_config
from syllabus_auditor.core.db.connection import get_project_root
from syllabus_auditor.core.db.courses import CourseStore
from syllabus_auditor.core.field_mapping import EXCEL_TO_DB_COLUMN
from syllabus_auditor.core.meta_builder import relative_source_path
from syllabus_auditor.core.types import CourseLibrarySummary

LOADER_CONFIG = load_project_config().get("loader", {})
EXCEL_SUFFIXES = set(LOADER_CONFIG.get("excel_suffixes", []))
DEFAULT_LIBRARY_FILENAME = str(LOADER_CONFIG.get("default_course_library_filename") or "")


def _normalize_column_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "")).strip()


def _normalize_cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return text


def _normalize_kcbh(value: Any) -> str | None:
    text = _normalize_cell(value)
    if not text:
        return None
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def detect_header_row(excel_path: Path, *, scan_rows: int = 5) -> int:
    preview = pd.read_excel(excel_path, header=None, nrows=scan_rows)
    for idx, row in preview.iterrows():
        for cell in row:
            label = _normalize_column_name(str(cell or ""))
            if label == "课程编号":
                return int(idx)
    return 0


def read_course_library_excel(excel_path: Path) -> list[dict[str, str | None]]:
    header_row = detect_header_row(excel_path)
    df = pd.read_excel(excel_path, header=header_row, dtype=str)
    df.columns = [_normalize_column_name(col) for col in df.columns]

    column_map: dict[str, str] = {}
    for excel_col, db_col in EXCEL_TO_DB_COLUMN.items():
        normalized = _normalize_column_name(excel_col)
        if normalized in df.columns and normalized not in column_map:
            column_map[normalized] = db_col

    rows: list[dict[str, str | None]] = []
    for _, series in df.iterrows():
        record: dict[str, str | None] = {col: None for col in set(EXCEL_TO_DB_COLUMN.values())}
        for excel_col, db_col in column_map.items():
            record[db_col] = _normalize_cell(series.get(excel_col))

        kcbh = _normalize_kcbh(record.get("kcbh"))
        if not kcbh:
            continue
        record["kcbh"] = kcbh
        rows.append(record)

    return rows


def find_course_library_excel(data_dir: Path, *, explicit: Path | None = None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"课程库 Excel 不存在: {explicit}")
        if explicit.suffix.lower() not in EXCEL_SUFFIXES:
            raise ValueError(f"不是 Excel 课程库文件: {explicit}")
        return explicit

    default_path = data_dir / DEFAULT_LIBRARY_FILENAME
    if default_path.is_file():
        return default_path

    candidates = sorted(path for path in data_dir.iterdir() if path.is_file() and path.suffix.lower() in EXCEL_SUFFIXES)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(f"在 {data_dir} 下未找到课程库 Excel（xls/xlsx）")
    names = ", ".join(path.name for path in candidates)
    raise FileNotFoundError(f"data/ 下有多个 Excel，请用 --input 指定课程库文件: {names}")


def prepare_course_library(excel_path: Path, *, import_term: str | None = None, store: CourseStore | None = None) -> CourseLibrarySummary:
    project_root = get_project_root()
    store = store or CourseStore()
    source_file = relative_source_path(excel_path.resolve(), project_root)

    raw_rows = read_course_library_excel(excel_path)
    summary = CourseLibrarySummary(total=len(raw_rows))

    db_rows: list[dict[str, Any]] = []
    seen_kcbh: set[str] = set()
    for row in raw_rows:
        kcbh = row.get("kcbh")
        if not kcbh:
            summary.skipped += 1
            continue
        if kcbh in seen_kcbh:
            summary.skipped += 1
            continue
        seen_kcbh.add(kcbh)
        db_rows.append({**row, "import_term": import_term, "source_file": source_file})

    summary.imported = store.upsert_many(db_rows, import_term=import_term, source_file=source_file)
    return summary


def run_prepare_course_library(
    data_dir: Path,
    *,
    explicit: Path | None = None,
    import_term: str | None = None,
    list_only: bool = False,
) -> CourseLibrarySummary | None:
    excel_path = find_course_library_excel(data_dir, explicit=explicit)

    if list_only:
        rows = read_course_library_excel(excel_path)
        print(f"文件: {excel_path.name}")
        print(f"有效课程行: {len(rows)}")
        if rows:
            sample = rows[0]
            filled = [k for k, v in sample.items() if v]
            print(f"示例 kcbh={sample.get('kcbh')}，有值字段数={len(filled)}")
        return None

    summary = prepare_course_library(excel_path, import_term=import_term)
    print(f"完成：读取 {summary.total} 行，导入 {summary.imported} 门课，跳过 {summary.skipped} 行")
    return summary

