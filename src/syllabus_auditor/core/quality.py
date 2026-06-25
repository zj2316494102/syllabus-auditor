from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


FIELD_LABELS = {
    "jcxx": {
        "kcbh": "课程编号",
        "zwkcmc": "中文课程名称",
        "ywkcmc": "英文课程名称",
        "kkyx": "开课（院）系",
        "rkjsxm": "任课教师姓名",
    },
    "kcmb": {
        "szmb": "思政目标",
        "nlmb": "能力目标",
        "zsmb": "知识目标",
    },
    "jxnr": {
        "tm": "教学内容条目",
    },
    "jxap": {
        "tm": "教学安排条目",
    },
    "khfsb": {
        "tm": "考核方式条目",
    },
}


def _warning(
    *,
    section: str,
    reason: str,
    path: str,
    field: str = "",
    label: str = "",
    detail: str = "",
) -> dict[str, str]:
    warning = {
        "section": section,
        "field": field,
        "label": label,
        "reason": reason,
        "path": path,
    }
    if detail:
        warning["detail"] = detail
    return warning


def clean_for_jsonb(value: Any, path: str = "") -> tuple[Any, list[dict[str, str]]]:
    warnings: list[dict[str, str]] = []
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            cleaned_item, child_warnings = clean_for_jsonb(item, child_path)
            cleaned[key] = cleaned_item
            warnings.extend(child_warnings)
        return cleaned, warnings

    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for index, item in enumerate(value):
            child_path = f"{path}[{index}]"
            cleaned_item, child_warnings = clean_for_jsonb(item, child_path)
            cleaned_list.append(cleaned_item)
            warnings.extend(child_warnings)
        return cleaned_list, warnings

    if isinstance(value, str):
        cleaned = CONTROL_CHARS.sub("", value)
        if cleaned != value:
            warnings.append(
                _warning(
                    section="system",
                    field="",
                    label="",
                    reason="sanitized_control_chars",
                    path=path,
                    detail="Removed control characters before JSONB insertion.",
                )
            )
        return cleaned, warnings

    return value, warnings


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _append_missing_field(
    warnings: list[dict[str, str]],
    *,
    section: str,
    field: str,
    label: str,
    path: str,
) -> None:
    warnings.append(
        _warning(
            section=section,
            field=field,
            label=label,
            reason="missing_field",
            path=path,
        )
    )


def build_completeness_warnings(payload: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    for section, fields in FIELD_LABELS.items():
        block = payload.get(section) or {}
        for field, label in fields.items():
            value = block.get(field) if isinstance(block, dict) else None
            if _is_empty(value):
                reason = "empty_section" if field == "tm" else "missing_field"
                warnings.append(
                    _warning(
                        section=section,
                        field=field,
                        label=label,
                        reason=reason,
                        path=f"payload.{section}.{field}",
                    )
                )

    for index, item in enumerate(((payload.get("jxnr") or {}).get("tm") or [])):
        for field, label in (("xh", "序号"), ("zt", "主题"), ("zsd", "知识点"), ("xs", "学时")):
            if _is_empty(item.get(field)):
                _append_missing_field(
                    warnings,
                    section="jxnr",
                    field=field,
                    label=label,
                    path=f"payload.jxnr.tm[{index}].{field}",
                )

    for index, item in enumerate(((payload.get("jxap") or {}).get("tm") or [])):
        for field, label in (
            ("zs", "课程/周次"),
            ("sknr", "授课内容"),
            ("skfs", "授课方式"),
            ("szyqjxx", "思政元素的融入和预期教学成效"),
        ):
            if _is_empty(item.get(field)):
                _append_missing_field(
                    warnings,
                    section="jxap",
                    field=field,
                    label=label,
                    path=f"payload.jxap.tm[{index}].{field}",
                )

    for index, item in enumerate(((payload.get("khfsb") or {}).get("tm") or [])):
        for field, label in (("ksxs", "考试形式"), ("kcnr", "考察内容"), ("kcfs", "考察方式"), ("zb", "占比")):
            if _is_empty(item.get(field)):
                _append_missing_field(
                    warnings,
                    section="khfsb",
                    field=field,
                    label=label,
                    path=f"payload.khfsb.tm[{index}].{field}",
                )

    kcyqb = payload.get("kcyqb") or {}
    if _is_empty(payload.get("kcyq")) and _is_empty(kcyqb.get("tm")) and _is_empty(kcyqb.get("yqgs")):
        warnings.append(
            _warning(
                section="kcyqb",
                field="tm",
                label="课程要求",
                reason="empty_section",
                path="payload.kcyqb.tm",
            )
        )

    return warnings


def prepare_payload_and_meta_for_insert(
    payload: dict[str, Any],
    meta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = deepcopy(payload)
    meta = deepcopy(meta)

    existing_warnings = list(meta.get("extraction_warnings") or [])
    existing_warnings.extend(build_completeness_warnings(payload))

    payload, payload_warnings = clean_for_jsonb(payload, "payload")
    meta, meta_warnings = clean_for_jsonb(meta, "meta")

    existing_warnings.extend(payload_warnings)
    existing_warnings.extend(meta_warnings)
    meta["extraction_warnings"] = existing_warnings
    return payload, meta
