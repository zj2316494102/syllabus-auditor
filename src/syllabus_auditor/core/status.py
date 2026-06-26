from __future__ import annotations

from typing import Any


def _warning_severity(warning: dict[str, Any]) -> str:
    return str(warning.get("severity") or "error")


def judge_extraction_status(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return "failed"

    warnings = meta.get("extraction_warnings") or []
    error_warnings = [item for item in warnings if _warning_severity(item) == "error"]

    jcxx = payload.get("jcxx") or {}
    has_kcbh = bool(jcxx.get("kcbh"))
    has_goals = any((payload.get("kcmb") or {}).get(k) for k in ("szmb", "nlmb", "zsmb", "mbgs"))
    has_jxnr = bool((payload.get("jxnr") or {}).get("tm")) or bool((payload.get("jxnr") or {}).get("nrgs"))
    has_jxap = bool((payload.get("jxap") or {}).get("tm")) or bool((payload.get("jxap") or {}).get("apgs"))

    if error_warnings:
        return "partial"
    if not (has_goals and has_jxnr):
        return "partial"
    if not has_kcbh:
        return "partial"
    if not has_jxap:
        return "partial"

    return "success"
