from __future__ import annotations

import json
import re
from typing import Any, Protocol

from syllabus_auditor.auditors.szysfyxrghj_prompt import build_prompt
from syllabus_auditor.core.audit import FAIL, PASS, AuditSubject, FieldFinding, SectionFinding
from config import load_project_config
from syllabus_auditor.core.llm import build_llm_trace


DIMENSION = "szysfyxrghj"
DIMENSION_LABEL = "\u662f\u5426\u5c06\u601d\u653f\u5143\u7d20\u6709\u6548\u878d\u5165\u5404\u73af\u8282"
FIELD = "szyr"
FIELD_LABEL = "\u601d\u653f\u5143\u7d20\u878d\u5165"
YES = "\u662f"
NO = "\u5426"
FALLBACK_REASON = "\u6a21\u578b\u672a\u7ed9\u51fa\u4e0d\u901a\u8fc7\u539f\u56e0\uff0c\u9700\u4eba\u5de5\u590d\u6838"
NO_LLM_REASON = "\u672a\u914d\u7f6e LLM\uff0c\u65e0\u6cd5\u5ba1\u6838\u662f\u5426\u5c06\u601d\u653f\u5143\u7d20\u6709\u6548\u878d\u5165\u5404\u73af\u8282\uff0c\u9700\u4eba\u5de5\u590d\u6838"
PARSE_ERROR_REASON = "\u6a21\u578b\u8f93\u51fa\u683c\u5f0f\u65e0\u6cd5\u89e3\u6790\uff0c\u9700\u4eba\u5de5\u590d\u6838"

def _dimension_config() -> dict[str, Any]:
    audit_config = load_project_config().get("audit", {})
    value = audit_config.get("szysfyxrghj_meta", {}) if isinstance(audit_config, dict) else {}
    return value if isinstance(value, dict) else {}


GOAL_SECTION_HINTS = tuple(str(item) for item in _dimension_config().get("goal_section_hints", []))
ARRANGEMENT_SECTION_HINTS = tuple(str(item) for item in _dimension_config().get("arrangement_section_hints", []))
IDEOLOGY_KEYWORDS = tuple(str(item) for item in _dimension_config().get("ideology_keywords", []))


class JsonLlmClient(Protocol):
    def complete_json(self, prompt: str) -> str:
        ...


def audit_szysfyxrghj(subject: AuditSubject, llm_client: JsonLlmClient | None) -> tuple[SectionFinding, list[FieldFinding]]:
    audit_input = build_audit_input(subject.payload, subject.meta)
    prompt = build_prompt(audit_input)

    if llm_client is None:
        trace = build_llm_trace(
            llm_client=None,
            dimension=DIMENSION,
            item=FIELD,
            prompt=prompt,
            status="no_llm",
        )
        result = _manual_result(NO_LLM_REASON, trace)
        return build_findings(result, audit_input)

    raw_response = ""
    try:
        raw_response = llm_client.complete_json(prompt)
        parsed = parse_llm_json(raw_response)
        trace = build_llm_trace(
            llm_client=llm_client,
            dimension=DIMENSION,
            item=FIELD,
            prompt=prompt,
            raw_response=raw_response,
            parsed=parsed,
            status="parsed",
        )
        result = normalize_llm_result(parsed, trace)
    except Exception as exc:
        reason = f"{PARSE_ERROR_REASON}：{type(exc).__name__}: {exc}"
        trace = build_llm_trace(
            llm_client=llm_client,
            dimension=DIMENSION,
            item=FIELD,
            prompt=prompt,
            raw_response=raw_response,
            parse_error=f"{type(exc).__name__}: {exc}",
            status="parse_error",
        )
        result = _manual_result(reason, trace)
    return build_findings(result, audit_input)


def build_audit_input(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    kcmb_data = _build_kcmb_data(payload)
    jxap_data = _build_jxap_data(payload)
    meta_context = build_meta_context(meta, kcmb_data, jxap_data)
    return {
        "audit_subject": {
            "dimension": DIMENSION,
            "label": DIMENSION_LABEL,
        },
        "payload_data": {
            "kcmb": {
                "payload_paths": ["payload.kcmb.szmb", "payload.kcmb.mbgs", "payload.kcmb.kzzd"],
                "data": kcmb_data,
            },
            "jxap": {
                "payload_paths": [
                    "payload.jxap.tm[].szyqjxx",
                    "payload.jxap.tm[].sknr",
                    "payload.jxap.tm[].skfs",
                    "payload.jxap.tm[].zy",
                    "payload.jxap.apgs",
                ],
                "data": jxap_data,
            },
        },
        "meta_context": meta_context,
    }


def build_meta_context(meta: dict[str, Any], kcmb_data: dict[str, Any], jxap_data: dict[str, Any]) -> dict[str, Any]:
    warnings = _relevant_warnings(meta)
    return {
        "fallback_flags": {
            "kcmb_needs_meta": _goal_needs_meta(kcmb_data, warnings),
            "jxap_needs_meta": _arrangement_needs_meta(jxap_data, warnings),
        },
        "extraction_warnings": warnings,
        "raw_text_segments": extract_raw_text_segments(meta),
        "notes": [
            "meta_context 只作为兜底辅助证据，不回写 payload。",
            "如果结构化字段为空但 meta 原文疑似存在相关内容，需复核抽取。",
        ],
    }


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("LLM result is not a JSON object")
    return parsed


def normalize_llm_result(result: dict[str, Any], llm_trace: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = _normalize_checks(result.get("checks"))
    normalized = {"dimension": DIMENSION, "label": str(result.get("label") or DIMENSION_LABEL), "result": _result_value(result.get("result")), "reasons": _string_list(result.get("reasons")), "checks": checks, "evidence_paths": _string_list(result.get("evidence_paths")), "suggestion": str(result.get("suggestion") or ""), "llm_trace": llm_trace or _as_dict(result.get("llm_trace"))}
    if any(check["result"] == NO for check in checks.values()):
        normalized["result"] = NO
    for check_key, check in checks.items():
        if check["result"] == NO and not check["reason"]:
            check["reason"] = f"{_check_label(check_key)}\u672a\u901a\u8fc7\uff0c\u6a21\u578b\u672a\u7ed9\u51fa\u5177\u4f53\u539f\u56e0\uff0c\u9700\u4eba\u5de5\u590d\u6838"
    if normalized["result"] == NO:
        normalized["reasons"] = _merge_reasons(normalized["reasons"], _check_reasons(checks)) or [FALLBACK_REASON]
    return normalized


def build_findings(result: dict[str, Any], audit_input: dict[str, Any]) -> tuple[SectionFinding, list[FieldFinding]]:
    result = normalize_llm_result(result, _as_dict(result.get("llm_trace")))
    is_pass = result["result"] == YES
    status = PASS if is_pass else FAIL
    reasons = _string_list(result.get("reasons"))
    reason = "\uff1b".join(reasons)
    evidence = {
        "evidence_paths": result["evidence_paths"],
        "checks": result["checks"],
        "meta_context_used": bool((audit_input.get("meta_context") or {}).get("raw_text_segments")),
        "fallback_flags": (audit_input.get("meta_context") or {}).get("fallback_flags") or {},
    }
    section = SectionFinding(wd=DIMENSION, status=status, message=result["result"], evidence=evidence, suggestion=result["suggestion"] if not is_pass else "", details={"label": DIMENSION_LABEL, "result": result["result"], "reasons": reasons, "checks": result["checks"]}, pdfs="direct_llm", llm_trace=_as_dict(result.get("llm_trace")))
    field = FieldFinding(section=DIMENSION, field=FIELD, path=f"llm.{DIMENSION}.{FIELD}", status=status, reason="" if is_pass else reason or FALLBACK_REASON, message=result["result"] if is_pass else reason or FALLBACK_REASON, expected={"requirement": DIMENSION_LABEL}, actual={"result": result["result"], "checks": result["checks"]}, evidence=evidence, suggestion=result["suggestion"] if not is_pass else "", llm_trace=_as_dict(result.get("llm_trace")))
    return section, [field]


def extract_raw_text_segments(meta: dict[str, Any], *, max_segments: int = 12, window: int = 320) -> list[dict[str, Any]]:
    section_hints = GOAL_SECTION_HINTS + ARRANGEMENT_SECTION_HINTS
    segments: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for source in _meta_text_sources(meta):
        text = source["text"]
        for hint in section_hints:
            for match in re.finditer(re.escape(hint), text):
                start = max(0, match.start() - window)
                end = min(len(text), match.end() + window)
                snippet = _compact_text(text[start:end])
                if not _has_ideology_keyword(snippet):
                    continue
                key = (source["source_path"], hint, start)
                if snippet and key not in seen:
                    seen.add(key)
                    segments.append(
                        {
                            "source_path": source["source_path"],
                            "section_hint": hint,
                            "text": snippet,
                        }
                    )
                if len(segments) >= max_segments:
                    return segments
        for keyword in IDEOLOGY_KEYWORDS:
            for match in re.finditer(re.escape(keyword), text):
                start = max(0, match.start() - window)
                end = min(len(text), match.end() + window)
                snippet = _compact_text(text[start:end])
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


def _manual_result(reason: str, llm_trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "dimension": DIMENSION,
        "label": DIMENSION_LABEL,
        "result": NO,
        "reasons": [reason],
        "checks": {
            "has_ideological_goal": {"result": NO, "reason": reason, "evidence_paths": []},
            "has_arrangement_integration": {"result": NO, "reason": reason, "evidence_paths": []},
            "is_effectively_integrated": {"result": NO, "reason": reason, "evidence_paths": []},
        },
        "evidence_paths": [],
        "suggestion": "\u914d\u7f6e LLM \u540e\u91cd\u65b0\u5ba1\u6838\uff0c\u6216\u8fdb\u884c\u4eba\u5de5\u590d\u6838\u3002",
        "llm_trace": llm_trace,
    }


def _normalize_checks(value: Any) -> dict[str, dict[str, Any]]:
    raw = value if isinstance(value, dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for key in ("has_ideological_goal", "has_arrangement_integration", "is_effectively_integrated"):
        item = raw.get(key) if isinstance(raw.get(key), dict) else {}
        result[key] = {
            "result": _result_value(item.get("result")),
            "reason": str(item.get("reason") or "").strip(),
            "evidence_paths": _string_list(item.get("evidence_paths")),
        }
    return result


def _build_kcmb_data(payload: dict[str, Any]) -> dict[str, Any]:
    kcmb = _as_dict(payload.get("kcmb"))
    return {
        "szmb": _exact_value(kcmb.get("szmb")),
        "mbgs": _exact_value(kcmb.get("mbgs")),
        "kzzd": _normalize_kzzd(kcmb.get("kzzd")),
    }


def _build_jxap_data(payload: dict[str, Any]) -> dict[str, Any]:
    jxap = _as_dict(payload.get("jxap"))
    rows = []
    for row in _as_list(jxap.get("tm")):
        item = _as_dict(row)
        rows.append(
            {
                "zs": _exact_value(item.get("zs")),
                "sknr": _exact_value(item.get("sknr")),
                "skfs": _exact_value(item.get("skfs")),
                "szyqjxx": _exact_value(item.get("szyqjxx")),
                "zy": _exact_value(item.get("zy")),
            }
        )
    return {"tm": rows, "apgs": _exact_value(jxap.get("apgs"))}


def _relevant_warnings(meta: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for warning in _as_list(meta.get("extraction_warnings")):
        item = _as_dict(warning)
        section = _exact_value(item.get("section"))
        field = _exact_value(item.get("field"))
        path = _exact_value(item.get("path"))
        if section in {"kcmb", "jxap"} or path.startswith("payload.kcmb") or path.startswith("payload.jxap") or field in {"szmb", "szyqjxx"}:
            result.append(item)
    return result


def _goal_needs_meta(kcmb_data: dict[str, Any], warnings: list[dict[str, Any]]) -> bool:
    text = _exact_value(kcmb_data.get("szmb"))
    return len(text) < 8 or _looks_template_text(text) or any(_exact_value(item.get("section")) == "kcmb" for item in warnings)


def _arrangement_needs_meta(jxap_data: dict[str, Any], warnings: list[dict[str, Any]]) -> bool:
    rows = _as_list(jxap_data.get("tm"))
    if not rows:
        return True
    values = [_exact_value(_as_dict(row).get("szyqjxx")) for row in rows]
    empty_count = sum(1 for value in values if not value)
    mostly_empty = empty_count >= max(1, len(values) // 2)
    only_template = all((not value) or _looks_template_text(value) for value in values)
    return mostly_empty or only_template or any(_exact_value(item.get("section")) == "jxap" for item in warnings)


def _meta_text_sources(meta: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    full_text = _exact_value(meta.get("full_text"))
    if full_text:
        sources.append({"source_path": "meta.full_text", "text": full_text})
    for index, page in enumerate(_as_list(meta.get("raw_pages"))):
        if isinstance(page, dict):
            text = _exact_value(page.get("text") or page.get("content") or page.get("raw_text"))
        else:
            text = _exact_value(page)
        if text:
            sources.append({"source_path": f"meta.raw_pages[{index}]", "text": text})
    for index, segment in enumerate(_as_list(meta.get("unmapped_segments"))):
        if isinstance(segment, dict):
            text = _exact_value(segment.get("text") or segment.get("content") or segment.get("snippet"))
        else:
            text = _exact_value(segment)
        if text:
            sources.append({"source_path": f"meta.unmapped_segments[{index}]", "text": text})
    return sources


def _result_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {YES, "yes", "pass", "passed", "true", "1"} or text.startswith("\u93c4"):
        return YES
    return NO


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _check_reasons(checks: dict[str, dict[str, Any]]) -> list[str]:
    reasons = [str(item.get("reason") or "").strip() for item in checks.values() if item.get("result") == NO]
    return _merge_reasons(reasons)


def _merge_reasons(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for reason in group:
            text = str(reason or "").strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def _check_label(key: str) -> str:
    labels = {
        "has_ideological_goal": "\u601d\u653f\u76ee\u6807",
        "has_arrangement_integration": "\u6559\u5b66\u5b89\u6392\u4e2d\u7684\u601d\u653f\u878d\u5165",
        "is_effectively_integrated": "\u601d\u653f\u76ee\u6807\u4e0e\u6559\u5b66\u5b89\u6392\u7684\u547c\u5e94\u5173\u7cfb",
    }
    return labels.get(key, key)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _exact_value(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


def _normalize_kzzd(value: Any) -> dict[str, Any] | list[Any] | str:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    return _exact_value(value)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _has_ideology_keyword(text: str) -> bool:
    return any(keyword in text for keyword in IDEOLOGY_KEYWORDS)


def _looks_template_text(text: str) -> bool:
    compact = _compact_text(text)
    if not compact:
        return True
    placeholders = (
        "\u8bf7\u586b\u5199",
        "\u5f85\u586b\u5199",
        "\u65e0",
        "N/A",
        "NA",
    )
    return compact in placeholders or len(compact) < 4


