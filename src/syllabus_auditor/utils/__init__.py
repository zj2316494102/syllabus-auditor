"""审核模块通用工具。"""

from __future__ import annotations

from typing import Any

from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.utils.data import (
    as_dict,
    as_list,
    compact_text,
    exact_value,
    is_empty,
    json_value,
    looks_template_text,
    normalize_kzzd,
)
from syllabus_auditor.utils.llm_parse import dedupe, merge_reasons, parse_llm_json, result_value, string_list
from syllabus_auditor.utils.llm_protocol import JsonLlmClient
from syllabus_auditor.utils.meta_text import (
    extract_page_keyword_segments,
    extract_source_keyword_segments,
    label_value,
    meta_text_sources,
    remove_section_titles,
    section_snippets,
)
from syllabus_auditor.utils.payload_sections import (
    build_jxap_audit_data,
    build_jxfs_audit_data,
    build_jxnr_audit_data,
    build_kcmb_audit_data,
)

_AUDIT_MESSAGE_ATTRS = {
    "FALLBACK_REASON": "fallback_reason",
    "NO_LLM_SUFFIX": "no_llm_suffix",
    "EMPTY_LLM_REASON": "empty_llm_reason",
    "PARSE_ERROR_REASON": "parse_error_reason",
    "MANUAL_REVIEW_SUGGESTION": "manual_review_suggestion",
}

__all__ = [
    "CONTENT_LAYOUT_RULES",
    "EMPTY_LLM_REASON",
    "FALLBACK_REASON",
    "MANUAL_REVIEW_SUGGESTION",
    "PARSE_ERROR_REASON",
    "JsonLlmClient",
    "as_dict",
    "as_list",
    "build_jxap_audit_data",
    "build_jxfs_audit_data",
    "build_jxnr_audit_data",
    "build_kcmb_audit_data",
    "compact_text",
    "dedupe",
    "exact_value",
    "extract_page_keyword_segments",
    "extract_source_keyword_segments",
    "is_empty",
    "json_value",
    "label_value",
    "looks_template_text",
    "merge_reasons",
    "meta_text_sources",
    "normalize_kzzd",
    "parse_llm_json",
    "remove_section_titles",
    "result_value",
    "section_snippets",
    "string_list",
]


def __getattr__(name: str) -> Any:
    if name == "CONTENT_LAYOUT_RULES":
        text = load_project_config().get("content_layout_rules") or ""
        return f"\n{text.strip()}\n" if text.strip() else ""
    if name in _AUDIT_MESSAGE_ATTRS:
        messages = load_project_config().get("audit_messages") or {}
        key = _AUDIT_MESSAGE_ATTRS[name]
        value = messages.get(key)
        if value is None:
            raise AttributeError(f"project.yaml 缺少 audit_messages.{key}")
        return str(value)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
