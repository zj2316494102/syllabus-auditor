from __future__ import annotations

from pathlib import Path
from typing import Any

from syllabus_auditor.core.extractors.layout import PageLayout, TextLine, clean_line


class PyMuPdfUnavailable(RuntimeError):
    pass


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
