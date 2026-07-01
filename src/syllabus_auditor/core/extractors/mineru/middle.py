"""从 MinerU middle.json 构建 ExtractionRaw。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from syllabus_auditor.core.extractors.mineru.process import build_extraction_raw
from syllabus_auditor.core.extractors.mineru.tables import html_table_to_grid
from syllabus_auditor.core.extractors.pdfplumber.extractor import clean_text

EXTRACTOR_NAME = "mineru_middle:0.1"


def _walk_blocks(
    node: Any,
    page_idx: int,
    html_tables: list[str],
    text_parts: list[tuple[int, float, float, str]],
) -> None:
    if isinstance(node, dict):
        if node.get("type") == "table" and isinstance(node.get("html"), str):
            html_tables.append(node["html"])
        for span in node.get("spans") or []:
            if not isinstance(span, dict):
                continue
            if span.get("type") == "table" and isinstance(span.get("html"), str):
                html_tables.append(span["html"])
            elif span.get("type") == "text" and span.get("content"):
                bbox = span.get("bbox") or [0, 0, 0, 0]
                text_parts.append((page_idx, float(bbox[1]), float(bbox[0]), str(span["content"])))
        for key in ("lines", "blocks", "preproc_blocks", "discarded_blocks", "para_blocks"):
            for child in node.get(key) or []:
                _walk_blocks(child, page_idx, html_tables, text_parts)
    elif isinstance(node, list):
        for item in node:
            _walk_blocks(item, page_idx, html_tables, text_parts)


def _extract_page_content(page: dict[str, Any]) -> tuple[list[list[list[str | None]]], str]:
    html_tables: list[str] = []
    text_parts: list[tuple[int, float, float, str]] = []
    page_idx = int(page.get("page_idx") or 0)

    for key in ("preproc_blocks", "para_blocks", "discarded_blocks"):
        for block in page.get(key) or []:
            _walk_blocks(block, page_idx, html_tables, text_parts)

    grids = [html_table_to_grid(html) for html in html_tables if html.strip()]
    grids = [g for g in grids if g]

    if text_parts:
        text_parts.sort(key=lambda x: (x[0], x[1], x[2]))
        full_text = "\n".join(clean_text(part[3]) for part in text_parts if clean_text(part[3]))
    else:
        full_text = ""

    return grids, full_text


class MineruMiddleExtractor:
    def extract(self, middle_path: Path, *, source_pdf: Path | None = None):
        payload = json.loads(middle_path.read_text(encoding="utf-8"))
        pages = payload.get("pdf_info") or []
        if not isinstance(pages, list):
            pages = []

        all_tables: list[list[list[str | None]]] = []
        text_chunks: list[str] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            grids, page_text = _extract_page_content(page)
            all_tables.extend(grids)
            if page_text:
                text_chunks.append(page_text)

        full_text = "\n\n".join(text_chunks)
        if not full_text.strip():
            full_text = re.sub(r"<[^>]+>", " ", middle_path.read_text(encoding="utf-8"))
            full_text = re.sub(r"\s+", " ", full_text)

        return build_extraction_raw(
            full_text=full_text,
            tables=all_tables,
            source_path=source_pdf or middle_path,
            page_count=len(pages) or 1,
            selected_source="mineru_middle",
        )
