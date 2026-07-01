"""维度：是否将思政元素有效融入各环节（szysfyxrghj）。"""

from __future__ import annotations

import json
from typing import Any

from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.core.audit import FAIL, NO, PASS, YES, AuditSubject, FieldFinding, SectionFinding
from syllabus_auditor.core.llm import EmptyLlmResponseError, build_llm_trace
from syllabus_auditor.shared.reason_text import clean_customer_reason
from syllabus_auditor.utils import (
    CONTENT_LAYOUT_RULES,
    EMPTY_LLM_REASON,
    FALLBACK_REASON,
    MANUAL_REVIEW_SUGGESTION,
    PARSE_ERROR_REASON,
    JsonLlmClient,
    as_dict,
    as_list,
    build_jxap_audit_data,
    build_kcmb_audit_data,
    exact_value,
    extract_source_keyword_segments,
    looks_template_text,
    merge_reasons,
    parse_llm_json,
    result_value,
    string_list,
)

DIMENSION = "szysfyxrghj"
DIMENSION_LABEL = "是否将思政元素有效融入各环节"
FIELD = "szyr"
NO_LLM_REASON = f"未配置 LLM，无法审核{DIMENSION_LABEL}，需人工复核"


def _dimension_config() -> dict[str, Any]:
    audit_config = load_project_config().get("audit", {})
    value = audit_config.get("szysfyxrghj_meta", {}) if isinstance(audit_config, dict) else {}
    return value if isinstance(value, dict) else {}


GOAL_SECTION_HINTS = tuple(str(item) for item in _dimension_config().get("goal_section_hints", []))
ARRANGEMENT_SECTION_HINTS = tuple(str(item) for item in _dimension_config().get("arrangement_section_hints", []))
IDEOLOGY_KEYWORDS = tuple(str(item) for item in _dimension_config().get("ideology_keywords", []))


def audit_szysfyxrghj(subject: AuditSubject, llm_client: JsonLlmClient | None) -> tuple[SectionFinding, list[FieldFinding]]:
    audit_input = build_audit_input(subject.payload, subject.meta)
    prompt = _build_prompt(audit_input)

    if llm_client is None:
        trace = build_llm_trace(llm_client=None, dimension=DIMENSION, item=FIELD, prompt=prompt, status="no_llm")
        return _build_findings(_manual_result(NO_LLM_REASON, trace), audit_input)

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
        result = _normalize_llm_result(parsed, trace)
    except EmptyLlmResponseError as exc:
        reason = f"{EMPTY_LLM_REASON}：{type(exc).__name__}: {exc}"
        trace = build_llm_trace(
            llm_client=llm_client,
            dimension=DIMENSION,
            item=FIELD,
            prompt=prompt,
            raw_response=raw_response,
            parse_error=str(exc),
            status="empty_response",
        )
        result = _manual_result(reason, trace)
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
    return _build_findings(result, audit_input)


def build_audit_input(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    kcmb_data = build_kcmb_audit_data(payload, include_all_goals=False)
    jxap_data = build_jxap_audit_data(payload)
    return {
        "audit_subject": {"dimension": DIMENSION, "label": DIMENSION_LABEL},
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
                    "payload.jxap.tm[].kzzd",
                    "payload.jxap.apgs",
                ],
                "data": jxap_data,
            },
        },
        "meta_context": _build_meta_context(meta, kcmb_data, jxap_data),
    }


def _build_meta_context(meta: dict[str, Any], kcmb_data: dict[str, Any], jxap_data: dict[str, Any]) -> dict[str, Any]:
    warnings = _relevant_warnings(meta)
    return {
        "fallback_flags": {
            "kcmb_needs_meta": _goal_needs_meta(kcmb_data, warnings),
            "jxap_needs_meta": _arrangement_needs_meta(jxap_data, warnings),
        },
        "extraction_warnings": warnings,
        "raw_text_segments": _extract_raw_text_segments(meta),
        "notes": [
            "meta_context 只作为兜底辅助证据，不回写 payload。",
            "如果结构化字段为空但 meta 原文疑似存在相关内容，需复核抽取。",
        ],
    }


def _extract_raw_text_segments(meta: dict[str, Any]) -> list[dict[str, Any]]:
    section_hints = GOAL_SECTION_HINTS + ARRANGEMENT_SECTION_HINTS
    segments = extract_source_keyword_segments(
        meta,
        section_hints,
        accept_snippet=lambda text: _has_ideology_keyword(text),
    )
    if len(segments) >= 12:
        return segments[:12]
    extra = extract_source_keyword_segments(meta, IDEOLOGY_KEYWORDS)
    seen = {(item["source_path"], item["section_hint"], item["text"]) for item in segments}
    for item in extra:
        key = (item["source_path"], item["section_hint"], item["text"])
        if key not in seen:
            seen.add(key)
            segments.append(item)
        if len(segments) >= 12:
            break
    return segments


def _build_prompt(audit_input: dict[str, Any]) -> str:
    input_json = json.dumps(audit_input, ensure_ascii=False, indent=2)
    return f"""你是课程方案审核专家。请审核“是否将思政元素有效融入各环节”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
payload_data 是结构化抽取结果，是主体证据。
meta_context 是辅助证据，只能在 content_layout 为 empty 或抽取明显不完整时参考。
如果 meta_context 中有相关原文但 content_layout 为 empty，应指出“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
不要把 meta 中孤立出现的政策关键词直接当作通过证据。

{CONTENT_LAYOUT_RULES}

审核维度：是否将思政元素有效融入各环节

审核要求：
1. 课程目标中应包含明确的思政目标，能够体现立德树人、价值引领、责任感、使命感、家国情怀、职业伦理、社会责任等内容。
2. 教学安排中应体现思政元素融入，并且思政元素应与具体教学内容、周次、章节、知识点、案例、讨论、实践或教学方法发生关联。
3. 课程目标中的思政目标与教学安排中的思政融入应能形成呼应，不能目标里有思政但教学安排没有落地，也不能教学安排零散出现思政词但课程目标没有对应目标。
4. 不审核预期教学成效。

判断规则：
1. 思政目标明确，且教学安排中有具体、有效、可对应教学环节的思政融入，result 写“是”。
2. content_layout 为 empty，或表述笼统、只有口号、无法与教学环节关联时，result 写“否”。
3. table_only / goals_only 时 apgs 或 mbgs 为空不算缺失，不得因此判否。
4. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
5. 不要因为出现“思政”“立德树人”“价值引领”等少量关键词就直接判通过，要判断是否具体融入课程目标和教学安排。
6. evidence_paths 必须引用输入 JSON 中实际存在的路径。
7. suggestion 必须给出可执行修改建议。
8. 输出必须是严格 JSON，不要输出 Markdown。
9. reasons 和 checks.reason 面向甲方展示，不得输出字段 key、JSON 路径或内部代码名，例如 szmb、jxap、khfsb、kcyq、payload、payload_data；应改写为思政目标、教学安排、考核方式、课程要求、结构化抽取结果等中文业务名称。

输入 JSON：
{input_json}

请输出严格 JSON：
{{
  "dimension": "szysfyxrghj",
  "label": "是否将思政元素有效融入各环节",
  "result": "是或否",
  "reasons": [],
  "checks": {{
    "has_ideological_goal": {{"result": "是或否", "reason": "", "evidence_paths": []}},
    "has_arrangement_integration": {{"result": "是或否", "reason": "", "evidence_paths": []}},
    "is_effectively_integrated": {{"result": "是或否", "reason": "", "evidence_paths": []}}
  }},
  "evidence_paths": [],
  "suggestion": ""
}}
"""


def _normalize_llm_result(result: dict[str, Any], llm_trace: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = _normalize_checks(result.get("checks"))
    normalized = {
        "dimension": DIMENSION,
        "label": str(result.get("label") or DIMENSION_LABEL),
        "result": result_value(result.get("result")),
        "reasons": [clean_customer_reason(item) for item in string_list(result.get("reasons"))],
        "checks": checks,
        "evidence_paths": string_list(result.get("evidence_paths")),
        "suggestion": str(result.get("suggestion") or ""),
        "llm_trace": llm_trace or as_dict(result.get("llm_trace")),
    }
    if any(check["result"] == NO for check in checks.values()):
        normalized["result"] = NO
    for check_key, check in checks.items():
        if check["result"] == NO and not check["reason"]:
            check["reason"] = f"{_check_label(check_key)}未通过，模型未给出具体原因，需人工复核"
    if normalized["result"] == NO:
        normalized["reasons"] = merge_reasons(normalized["reasons"], _check_reasons(checks)) or [FALLBACK_REASON]
    return normalized


def _build_findings(result: dict[str, Any], audit_input: dict[str, Any]) -> tuple[SectionFinding, list[FieldFinding]]:
    result = _normalize_llm_result(result, as_dict(result.get("llm_trace")))
    is_pass = result["result"] == YES
    status = PASS if is_pass else FAIL
    reasons = string_list(result.get("reasons"))
    reason = clean_customer_reason("；".join(reasons))
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
        details={"label": DIMENSION_LABEL, "result": result["result"], "reasons": reasons, "checks": result["checks"]},
        pdfs="direct_llm",
        llm_trace=as_dict(result.get("llm_trace")),
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
        llm_trace=as_dict(result.get("llm_trace")),
    )
    return section, [field]


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
        "suggestion": MANUAL_REVIEW_SUGGESTION,
        "llm_trace": llm_trace,
    }


def _normalize_checks(value: Any) -> dict[str, dict[str, Any]]:
    raw = value if isinstance(value, dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for key in ("has_ideological_goal", "has_arrangement_integration", "is_effectively_integrated"):
        item = raw.get(key) if isinstance(raw.get(key), dict) else {}
        result[key] = {
            "result": result_value(item.get("result")),
            "reason": clean_customer_reason(str(item.get("reason") or "").strip()),
            "evidence_paths": string_list(item.get("evidence_paths")),
        }
    return result


def _relevant_warnings(meta: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for warning in as_list(meta.get("extraction_warnings")):
        item = as_dict(warning)
        section = exact_value(item.get("section"))
        field = exact_value(item.get("field"))
        path = exact_value(item.get("path"))
        if section in {"kcmb", "jxap"} or path.startswith("payload.kcmb") or path.startswith("payload.jxap") or field in {"szmb", "szyqjxx"}:
            result.append(item)
    return result


def _goal_needs_meta(kcmb_data: dict[str, Any], warnings: list[dict[str, Any]]) -> bool:
    layout = str(kcmb_data.get("content_layout") or "")
    if layout == "overview_only":
        return exact_value((kcmb_data.get("supplement") or {}).get("mbgs")) == ""
    text = exact_value(kcmb_data.get("szmb"))
    if layout in {"goals_only", "goals_with_supplement"} and len(text) >= 8 and not looks_template_text(text):
        return any(exact_value(item.get("section")) == "kcmb" for item in warnings)
    return len(text) < 8 or looks_template_text(text) or any(exact_value(item.get("section")) == "kcmb" for item in warnings)


def _arrangement_needs_meta(jxap_data: dict[str, Any], warnings: list[dict[str, Any]]) -> bool:
    layout = str(jxap_data.get("content_layout") or "")
    if layout == "overview_only":
        return exact_value((jxap_data.get("supplement") or {}).get("apgs")) == ""
    rows = as_list(jxap_data.get("tm"))
    if not rows:
        return layout == "empty"
    values = [exact_value(as_dict(row).get("szyqjxx")) for row in rows]
    empty_count = sum(1 for value in values if not value)
    mostly_empty = empty_count >= max(1, len(values) // 2)
    only_template = all((not value) or looks_template_text(value) for value in values)
    return mostly_empty or only_template or any(exact_value(item.get("section")) == "jxap" for item in warnings)


def _has_ideology_keyword(text: str) -> bool:
    return any(keyword in text for keyword in IDEOLOGY_KEYWORDS)


def _check_reasons(checks: dict[str, dict[str, Any]]) -> list[str]:
    reasons = [str(item.get("reason") or "").strip() for item in checks.values() if item.get("result") == NO]
    return merge_reasons(reasons)


def _check_label(key: str) -> str:
    labels = {
        "has_ideological_goal": "思政目标",
        "has_arrangement_integration": "教学安排中的思政融入",
        "is_effectively_integrated": "思政目标与教学安排的呼应关系",
    }
    return labels.get(key, key)




