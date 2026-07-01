"""合并根目录 project.yaml 与 schema。"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from syllabus_auditor.core.db.connection import get_project_root
from syllabus_auditor.shared.config.schema import (
    AUDIT_RULES_SCHEMA,
    AUDIT_SCHEMA,
    COURSE_LIBRARY_CONFIG,
    EXTRACTION_CONFIG,
    PDF_EXTRACTOR_CONFIG,
    PAYLOAD_FIELD_MAP,
)


def project_yaml_path() -> Path:
    return get_project_root() / "project.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少配置文件: {path}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_project_yaml() -> dict[str, Any]:
    return _load_yaml(project_yaml_path())


def load_yaml_config() -> dict[str, Any]:
    """兼容旧名：返回 project.yaml 内容。"""
    return load_project_yaml()


def _resolve_active_llm(project: dict[str, Any]) -> dict[str, Any]:
    defaults = project.get("defaults") if isinstance(project.get("defaults"), dict) else {}
    llms = project.get("llms") if isinstance(project.get("llms"), dict) else {}
    active = str(defaults.get("active_llm") or "").strip()
    profile = llms.get(active) if active else {}
    profile = profile if isinstance(profile, dict) else {}

    def _as_env_list(value: Any) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    return {
        "active_profile": active,
        "provider": str(profile.get("provider") or "openai_compatible"),
        "model_env_vars": _as_env_list(profile.get("model_name_env")) or ["LLM_MODEL_NAME", "OPENAI_MODEL_NAME"],
        "api_key_env_vars": _as_env_list(profile.get("api_key_env")) or ["LLM_API_KEY", "OPENAI_API_KEY"],
        "base_url_env_vars": _as_env_list(profile.get("base_url_env")) or ["LLM_BASE_URL", "OPENAI_BASE_URL"],
        "temperature": profile.get("temperature", defaults.get("temperature", 0)),
        "system_prompt": str(defaults.get("system_prompt") or "你是严格输出 JSON 的课程方案审核专家。"),
        "response_format": defaults.get("response_format") or {"type": "json_object"},
        "max_tokens": profile.get("max_tokens"),
    }


def _normalize_fusion_scoring(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section, cfg in (raw or {}).items():
        if not isinstance(cfg, dict):
            continue
        required = cfg.get("required") or []
        weighted = cfg.get("weighted") or {}
        result[section] = {
            "required": tuple(str(item) for item in required),
            "weighted": {str(k): int(v) for k, v in weighted.items()} if isinstance(weighted, dict) else {},
            "min_rows": int(cfg.get("min_rows", 1)),
            "min_improvement": float(cfg.get("min_improvement", 8.0)),
        }
    return result


def _build_payload_config(project: dict[str, Any]) -> dict[str, Any]:
    payload_params = project.get("payload") if isinstance(project.get("payload"), dict) else {}
    return {
        **PAYLOAD_FIELD_MAP,
        "empty_markers": list(payload_params.get("empty_markers") or []),
        "total_hours_patterns": list(payload_params.get("total_hours_patterns") or []),
    }


def _build_audit_config(project: dict[str, Any]) -> dict[str, Any]:
    audit = copy.deepcopy(AUDIT_SCHEMA)
    rules = copy.deepcopy(AUDIT_RULES_SCHEMA)
    tunable = project.get("audit_rules") if isinstance(project.get("audit_rules"), dict) else {}
    for key, value in tunable.items():
        rules[key] = value
    audit["rules"] = rules
    return audit


@lru_cache(maxsize=1)
def load_project_config() -> dict[str, Any]:
    project = load_project_yaml()
    defaults = project.get("defaults") if isinstance(project.get("defaults"), dict) else {}
    return {
        "paths": dict(project.get("paths") or {}),
        "defaults": dict(defaults),
        "llms": copy.deepcopy(project.get("llms") or {}),
        "extraction": copy.deepcopy(EXTRACTION_CONFIG),
        "extraction_params": dict(project.get("extraction") or {}),
        "pdf_extractor": copy.deepcopy(PDF_EXTRACTOR_CONFIG),
        "payload": _build_payload_config(project),
        "course_library": copy.deepcopy(COURSE_LIBRARY_CONFIG),
        "loader": dict(project.get("loader") or {}),
        "llm": _resolve_active_llm(project),
        "audit": _build_audit_config(project),
        "meta": dict(project.get("meta") or {}),
        "fusion_scoring": _normalize_fusion_scoring(project.get("fusion_scoring") or {}),
        "candidate_scoring": dict(project.get("candidate_scoring") or {}),
        "table_parser": dict(project.get("table_parser") or {}),
        "ocr_quality": dict(project.get("ocr_quality") or {}),
        "warning_severity": dict(project.get("warning_severity") or {}),
        "audit_messages": dict(project.get("audit_messages") or {}),
        "content_layout_rules": str(project.get("content_layout_rules") or "").strip(),
        "payload_schema_version": str(defaults.get("payload_schema_version") or "1.0"),
    }


@lru_cache(maxsize=1)
def load_extraction_config() -> dict[str, Any]:
    return load_project_config()["extraction"]


def reload_config() -> None:
    load_project_yaml.cache_clear()
    load_project_config.cache_clear()
    load_extraction_config.cache_clear()
