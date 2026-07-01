"""LLM 返回 JSON 的解析与理由合并。"""

from __future__ import annotations

import json
import re
from typing import Any

from syllabus_auditor.core.audit import NO, YES


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("LLM result is not a JSON object")
    return parsed


def result_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {YES, "yes", "pass", "passed", "true", "1"} or text.startswith("是"):
        return YES
    return NO


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def merge_reasons(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for reason in group:
            text = str(reason or "").strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
