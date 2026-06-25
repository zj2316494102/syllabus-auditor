from __future__ import annotations

import re
from dataclasses import dataclass


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
