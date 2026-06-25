from __future__ import annotations

import json
import re
from typing import Any, Protocol

from syllabus_auditor.auditors.szysfyxrghj_prompt import build_prompt
from syllabus_auditor.core.audit import FAIL, PASS, AuditSubject, FieldFinding, SectionFinding
from syllabus_auditor.core.llm import build_llm_trace


DIMENSION = "szysfyxrghj"
DIMENSION_LABEL = "是否将思政元素有效融入各环节"
FIELD = "szyr"
FIELD_LABEL = "思政元素融入"
FALLBACK_REASON = "模型未给出不通过原因，需人工复核"
NO_LLM_REASON = "未配置 LLM，无法审核是否将思政元素有效融入各环节，需人工复核"
PARSE_ERROR_REASON = "模型输出格式无法解析，需人工复核"

GOAL_SECTION_HINTS = ("课程目标", "教学目标", "思政目标", "课程思政目标", "价值目标", "育人目标")
ARRANGEMENT_SECTION_HINTS = ("教学安排", "课程安排", "授课安排", "教学进度", "课程思政", "思政元素", "思政元素融入")
IDEOLOGY_KEYWORDS = (
    "思政",
    "立德树人",
    "价值引领",
    "价值观",
    "责任感",
    "使命感",
    "家国情怀",
    "职业伦理",
    "社会责任",
    "诚信",
    "法治",
    "职业道德",
)


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
    normalized = {
        "dimension": DIMENSION,
        "label": str(result.get("label") or DIMENSION_LABEL),
        "result": _result_value(result.get("result")),
        "reasons": _string_list(result.get("reasons")),
        "checks": checks,
        "evidence_paths": _string_list(result.get("evidence_paths")),
        "suggestion": str(result.get("suggestion") or ""),
        "llm_trace": llm_trace or _as_dict(result.get("llm_trace")),
    }
    if any(check["result"] == "否" for check in checks.values()):
        normalized["result"] = "否"
    if normalized["result"] == "否" and not normalized["reasons"]:
        normalized["reasons"] = _check_reasons(checks) or [FALLBACK_REASON]
    for check_key, check in checks.items():
        if check["result"] == "否" and not check["reason"]:
            check["reason"] = f"{_check_label(check_key)}未通过，模型未给出具体原因，需人工复核"
    return normalized


def build_findings(result: dict[str, Any], audit_input: dict[str, Any]) -> tuple[SectionFinding, list[FieldFinding]]:
    result = normalize_llm_result(result, _as_dict(result.get("llm_trace")))
    is_pass = result["result"] == "是"
    status = PASS if is_pass else FAIL
    reasons = _string_list(result.get("reasons"))
    reason = "；".join(reasons)
    evidence = {
        "evidence_paths": result["evidence_paths"],
        "checks": result["checks"],
        "meta_context_used": bool((audit_input.get("meta_context") or {}).get("raw_text_segments")),
        "fallback_flags": (audit_input.get("meta_context") or {}).get("fallback_flags") or {},
    }
    section = SectionFinding(
        wd=DIMENSION,
        status=status,
        message=result["result"],
        evidence=evidence,
        suggestion=result["suggestion"] if not is_pass else "",
        details={
            "label": DIMENSION_LABEL,
            "result": result["result"],
            "reasons": reasons,
            "checks": result["checks"],
        },
        pdfs="direct_llm",
        llm_trace=_as_dict(result.get("llm_trace")),
    )
    field = FieldFinding(
        section=DIMENSION,
        field=FIELD,
        path=f"llm.{DIMENSION}.{FIELD}",
        status=status,
        reason="" if is_pass else reason or FALLBACK_REASON,
        message=result["result"] if is_pass else reason or FALLBACK_REASON,
        expected={"requirement": DIMENSION_LABEL},
        actual={"result": result["result"], "checks": result["checks"]},
        evidence=evidence,
        suggestion=result["suggestion"] if not is_pass else "",
        llm_trace=_as_dict(result.get("llm_trace")),
    )
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
        "result": "否",
        "reasons": [reason],
        "checks": {
            "has_ideological_goal": {"result": "否", "reason": reason, "evidence_paths": []},
            "has_arrangement_integration": {"result": "否", "reason": reason, "evidence_paths": []},
            "is_effectively_integrated": {"result": "否", "reason": reason, "evidence_paths": []},
        },
        "evidence_paths": [],
        "suggestion": "配置 LLM 后重新审核，或进行人工复核。",
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
    return "是" if str(value).strip() == "是" else "否"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _check_reasons(checks: dict[str, dict[str, Any]]) -> list[str]:
    return [item["reason"] for item in checks.values() if item.get("result") == "否" and item.get("reason")]


def _check_label(key: str) -> str:
    labels = {
        "has_ideological_goal": "课程目标中的思政目标",
        "has_arrangement_integration": "教学安排中的思政融入",
        "is_effectively_integrated": "思政元素有效融入各环节",
    }
    return labels.get(key, key)


def _has_ideology_keyword(text: str) -> bool:
    return any(keyword in text for keyword in IDEOLOGY_KEYWORDS)


def _looks_template_text(text: str) -> bool:
    stripped = _exact_value(text)
    return stripped in {"无", "暂无", "无。", "待补充", "课程思政", "思政元素", "融入思政元素"}


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", _exact_value(text)).strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _exact_value(value: Any) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()


def _normalize_kzzd(value: Any) -> dict[str, Any] | list[Any] | str:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    return _exact_value(value)
