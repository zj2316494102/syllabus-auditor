"""入库前 payload/meta 清洗、完整性告警生成与 JSONB 安全化。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.core.content_layout import section_content_layout
from syllabus_auditor.core.extractors.mineru import downgrade_warnings_for_ocr


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

def _default_severity(reason: str) -> str:
    mapping = load_project_config().get("warning_severity", {})
    if isinstance(mapping, dict):
        value = mapping.get(reason)
        if value:
            return str(value)
    return "error"


def _warning(
    *,
    section: str,
    reason: str,
    path: str,
    field: str = "",
    label: str = "",
    detail: str = "",
    severity: str = "",
) -> dict[str, Any]:
    warning: dict[str, Any] = {
        "section": section,
        "field": field,
        "label": label,
        "reason": reason,
        "path": path,
        "severity": severity or _default_severity(reason),
    }
    if detail:
        warning["detail"] = detail
    return warning


def normalize_warning_severities(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in warnings:
        warning = dict(item)
        if not warning.get("severity"):
            warning["severity"] = _default_severity(str(warning.get("reason") or ""))
        normalized.append(warning)
    return normalized


def clean_for_jsonb(value: Any, path: str = "") -> tuple[Any, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
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
                    severity="info",
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
    warnings: list[dict[str, Any]],
    *,
    section: str,
    field: str,
    label: str,
    path: str,
    severity: str = "error",
    detail: str = "",
) -> None:
    warnings.append(
        _warning(
            section=section,
            field=field,
            label=label,
            reason="missing_field",
            path=path,
            severity=severity,
            detail=detail,
        )
    )


def _append_table_row_missing_fields(
    warnings: list[dict[str, Any]],
    *,
    section: str,
    rows: list[dict[str, Any]],
    field_specs: tuple[tuple[str, str], ...],
    severity: str,
) -> None:
    """表格行内字段：同一 section 下每种列字段至多报一条。"""
    for field, label in field_specs:
        empty_count = sum(1 for item in rows if _is_empty(item.get(field)))
        if not empty_count:
            continue
        detail = f"共 {empty_count} 行缺少该字段" if empty_count > 1 else ""
        _append_missing_field(
            warnings,
            section=section,
            field=field,
            label=label,
            path=f"payload.{section}.tm[].{field}",
            severity=severity,
            detail=detail,
        )


CONTENT_SECTIONS = frozenset({"kcmb", "jxnr", "jxap", "khfsb"})


def build_completeness_warnings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    for section, fields in FIELD_LABELS.items():
        block = payload.get(section) or {}
        layout = section_content_layout(section, block) if section in CONTENT_SECTIONS else ""

        for field, label in fields.items():
            value = block.get(field) if isinstance(block, dict) else None
            if not _is_empty(value):
                continue
            if field == "tm":
                if layout == "overview_only":
                    warnings.append(
                        _warning(
                            section=section,
                            field=field,
                            label=label,
                            reason="overview_used_instead_of_table",
                            path=f"payload.{section}.{field}",
                            severity="info",
                        )
                    )
                elif layout == "empty":
                    warnings.append(
                        _warning(
                            section=section,
                            field=field,
                            label=label,
                            reason="empty_section",
                            path=f"payload.{section}.{field}",
                        )
                    )
                continue
            if section == "kcmb" and layout == "overview_only":
                continue
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

    jxnr_block = payload.get("jxnr") or {}
    jxnr_layout = section_content_layout("jxnr", jxnr_block)
    jxnr_rows = (jxnr_block.get("tm") or []) if isinstance(jxnr_block, dict) else []
    _append_table_row_missing_fields(
        warnings,
        section="jxnr",
        rows=jxnr_rows,
        field_specs=(("xh", "序号"), ("zt", "主题"), ("zsd", "知识点"), ("xs", "学时")),
        severity="warn" if jxnr_layout == "overview_only" else "error",
    )

    jxap_block = payload.get("jxap") or {}
    jxap_layout = section_content_layout("jxap", jxap_block)
    jxap_rows = (jxap_block.get("tm") or []) if isinstance(jxap_block, dict) else []
    _append_table_row_missing_fields(
        warnings,
        section="jxap",
        rows=jxap_rows,
        field_specs=(
            ("zs", "课程/周次"),
            ("sknr", "授课内容"),
            ("skfs", "授课方式"),
            ("szyqjxx", "思政元素的融入和预期教学成效"),
        ),
        severity="warn" if jxap_layout == "overview_only" else "error",
    )

    khfsb_block = payload.get("khfsb") or {}
    khfsb_layout = section_content_layout("khfsb", khfsb_block)
    khfsb_rows = (khfsb_block.get("tm") or []) if isinstance(khfsb_block, dict) else []
    _append_table_row_missing_fields(
        warnings,
        section="khfsb",
        rows=khfsb_rows,
        field_specs=(("ksxs", "考试形式"), ("kcnr", "考察内容"), ("kcfs", "考察方式"), ("zb", "占比")),
        severity="warn" if khfsb_layout == "overview_only" else "error",
    )

    if _is_empty(payload.get("kcyq")):
        warnings.append(
            _warning(
                section="kcyq",
                field="content",
                label="课程要求",
                reason="empty_section",
                path="payload.kcyq",
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
    existing_warnings = downgrade_warnings_for_ocr(meta, existing_warnings)
    meta["extraction_warnings"] = normalize_warning_severities(existing_warnings)
    return payload, meta
