from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syllabus_auditor.core.types import ExtractionRaw

EXTRACTOR_VERSION = "pdfplumber:0.11.0"

UNMAPPED_CN_FIELDS = ("课程模块", "职称", "学历")


def build_meta(raw: ExtractionRaw, source_path: str) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    for idx, field in enumerate(UNMAPPED_CN_FIELDS, start=1):
        value = raw.cn_data.get(field, "")
        if value:
            segments.append(
                {
                    "segment_id": f"seg_{idx:03d}",
                    "text": value,
                    "page": 0,
                    "reason": "unmapped_field",
                    "context": field,
                }
            )

    return {
        "source_path": source_path,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "extractor": EXTRACTOR_VERSION,
        "page_count": raw.page_count,
        "full_text": raw.full_text,
        "raw_pages": raw.raw_pages,
        "unmapped_segments": segments,
        "extraction_warnings": raw.extraction_warnings,
    }


def relative_source_path(pdf_path: Path, project_root: Path) -> str:
    try:
        return pdf_path.relative_to(project_root).as_posix()
    except ValueError:
        return pdf_path.as_posix()
