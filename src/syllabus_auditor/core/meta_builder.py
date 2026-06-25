from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import load_project_config
from syllabus_auditor.core.types import ExtractionRaw


def _meta_config() -> dict[str, Any]:
    value = load_project_config().get("meta", {})
    return value if isinstance(value, dict) else {}


EXTRACTOR_VERSION = str(_meta_config().get("extractor_version") or "pdfplumber+pymupdf-fusion")
UNMAPPED_CN_FIELDS = tuple(str(item) for item in _meta_config().get("unmapped_cn_fields", []))


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
        "section_extraction": raw.section_extraction,
    }


def relative_source_path(pdf_path: Path, project_root: Path) -> str:
    try:
        return pdf_path.relative_to(project_root).as_posix()
    except ValueError:
        return pdf_path.as_posix()

