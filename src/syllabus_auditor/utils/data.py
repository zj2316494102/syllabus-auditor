"""通用数据清洗与空值判断。"""

from __future__ import annotations

import re
from typing import Any


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def exact_value(value: Any) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()


def normalize_kzzd(value: Any) -> dict[str, Any] | list[Any] | str:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    return exact_value(value)


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def json_value(value: Any) -> Any:
    return "" if value is None else value


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def looks_template_text(text: str) -> bool:
    compact = compact_text(text)
    if not compact:
        return True
    placeholders = ("请填写", "待填写", "无", "N/A", "NA")
    return compact in placeholders or len(compact) < 4
