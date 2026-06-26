"""从 MinerU 输出的 Markdown（含 HTML 表格）构建 ExtractionRaw。"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from syllabus_auditor.core.extractors.mineru_build import build_extraction_raw
from syllabus_auditor.core.extractors.mineru_table_normalize import html_table_to_grid

EXTRACTOR_NAME = "mineru_md"


def _html_tables(md_text: str) -> list[list[list[str | None]]]:
    soup = BeautifulSoup(md_text, "html.parser")
    tables: list[list[list[str | None]]] = []
    for table in soup.find_all("table"):
        html = str(table)
        grid = html_table_to_grid(html)
        if grid:
            tables.append(grid)
    return tables


def _plain_text(md_text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", md_text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class MineruMdExtractor:
    def extract(self, md_path: Path, *, source_pdf: Path | None = None):
        md_text = md_path.read_text(encoding="utf-8")
        return build_extraction_raw(
            full_text=_plain_text(md_text),
            tables=_html_tables(md_text),
            source_path=source_pdf or md_path,
            page_count=max(1, len(re.findall(r"^##\s+", md_text, flags=re.MULTILINE))),
            selected_source="mineru_md",
        )
