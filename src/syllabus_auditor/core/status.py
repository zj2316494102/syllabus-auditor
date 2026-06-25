from __future__ import annotations

from typing import Any


def judge_extraction_status(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return "failed"

    jcxx = payload.get("jcxx") or {}
    has_goals = any((payload.get("kcmb") or {}).get(k) for k in ("szmb", "nlmb", "zsmb", "mbgs"))
    has_content = bool((payload.get("jxnr") or {}).get("tm")) or bool((payload.get("jxnr") or {}).get("nrgs"))

    unmapped = meta.get("unmapped_segments") or []
    warnings = meta.get("extraction_warnings") or []
    has_overview = any(
        (payload.get(block) or {}).get(overview_key)
        for block, overview_key in (
            ("kcmb", "mbgs"),
            ("jxnr", "nrgs"),
            ("jxap", "apgs"),
            ("kcyqb", "yqgs"),
            ("khfsb", "khgs"),
        )
    )

    if unmapped or warnings or has_overview or not (has_goals and has_content):
        return "partial"

    return "success"
