"""PyMuPDF 版面抽取与文本行重建。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_no: int


@dataclass(frozen=True, slots=True)
class PageLayout:
    page_no: int
    width: float
    height: float
    lines: list[TextLine]


class PyMuPdfUnavailable(RuntimeError):
    pass


def clean_line(value: str | None) -> str:
    text = str(value or "").replace("\r", "\n")
    text = re.sub(r"[\t\u3000]+", " ", text)
    text = re.sub(r" {2,}", "  ", text)
    return text.strip()


def layout_to_text(pages: list[PageLayout]) -> str:
    parts: list[str] = []
    for page in pages:
        for line in sorted(page.lines, key=lambda item: (item.y0, item.x0)):
            text = clean_line(line.text)
            if text:
                parts.append(text)
    return "\n".join(parts)


def extract_layout(pdf_path: Path) -> list[PageLayout]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise PyMuPdfUnavailable("PyMuPDF is not installed") from exc

    pages: list[PageLayout] = []
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            page_dict: dict[str, Any] = page.get_text("dict")
            lines: list[TextLine] = []
            for block in page_dict.get("blocks", []):
                for raw_line in block.get("lines", []):
                    spans = raw_line.get("spans", [])
                    text = clean_line("".join(str(span.get("text", "")) for span in spans))
                    if not text:
                        continue
                    x0, y0, x1, y1 = raw_line.get("bbox", (0, 0, 0, 0))
                    lines.append(
                        TextLine(
                            text=text,
                            x0=float(x0),
                            y0=float(y0),
                            x1=float(x1),
                            y1=float(y1),
                            page_no=page_index,
                        )
                    )
            pages.append(
                PageLayout(
                    page_no=page_index,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    lines=lines,
                )
            )
    return pages
