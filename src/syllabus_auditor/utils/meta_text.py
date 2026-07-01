"""从 meta 原文提取片段与标签值。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from syllabus_auditor.utils.data import as_list, compact_text, exact_value


def meta_text_sources(meta: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    full_text = exact_value(meta.get("full_text"))
    if full_text:
        sources.append({"source_path": "meta.full_text", "text": full_text})
    for index, page in enumerate(as_list(meta.get("raw_pages"))):
        if isinstance(page, dict):
            text = exact_value(page.get("text") or page.get("content") or page.get("raw_text"))
        else:
            text = exact_value(page)
        if text:
            sources.append({"source_path": f"meta.raw_pages[{index}]", "text": text})
    for index, segment in enumerate(as_list(meta.get("unmapped_segments"))):
        if isinstance(segment, dict):
            text = exact_value(segment.get("text") or segment.get("content") or segment.get("snippet"))
        else:
            text = exact_value(segment)
        if text:
            sources.append({"source_path": f"meta.unmapped_segments[{index}]", "text": text})
    return sources


def extract_page_keyword_segments(
    meta: dict[str, Any],
    keywords: tuple[str, ...],
    *,
    max_segments: int = 12,
    window: int = 260,
) -> list[dict[str, Any]]:
    pages = meta.get("raw_pages")
    if isinstance(pages, list):
        texts = [(index, str(text or "")) for index, text in enumerate(pages)]
    else:
        texts = [(0, str(meta.get("full_text") or ""))]

    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for page, text in texts:
        for keyword in keywords:
            for match in re.finditer(re.escape(keyword), text):
                start = max(0, match.start() - window)
                end = min(len(text), match.end() + window)
                snippet = compact_text(text[start:end])
                key = (page, start, keyword)
                if snippet and key not in seen:
                    seen.add(key)
                    segments.append({"page": page, "keyword": keyword, "text": snippet})
                if len(segments) >= max_segments:
                    return segments
    return segments


def extract_source_keyword_segments(
    meta: dict[str, Any],
    keywords: tuple[str, ...],
    *,
    max_segments: int = 12,
    window: int = 320,
    accept_snippet: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for source in meta_text_sources(meta):
        text = source["text"]
        for keyword in keywords:
            for match in re.finditer(re.escape(keyword), text):
                start = max(0, match.start() - window)
                end = min(len(text), match.end() + window)
                snippet = compact_text(text[start:end])
                if accept_snippet and not accept_snippet(snippet):
                    continue
                key = (source["source_path"], keyword, start)
                if snippet and key not in seen:
                    seen.add(key)
                    segments.append(
                        {
                            "source_path": source["source_path"],
                            "section_hint": keyword,
                            "text": snippet,
                        }
                    )
                if len(segments) >= max_segments:
                    return segments
    return segments


def section_snippets(text: str, hints: tuple[str, ...], *, window: int = 800) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for hint in hints:
        for match in re.finditer(re.escape(hint), text):
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + window)
            result.append({"section_hint": hint, "snippet": text[start:end]})
    return result


def label_value(snippet: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s*[:：]?\s*([^\n\r；。]*)"
    match = re.search(pattern, snippet)
    if not match:
        return None
    return match.group(1).strip()


def remove_section_titles(text: str, hints: tuple[str, ...]) -> str:
    result = text
    for hint in hints:
        result = result.replace(hint, "")
    return result
