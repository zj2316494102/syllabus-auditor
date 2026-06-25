from __future__ import annotations

import json
import re
from typing import Any, Protocol

from syllabus_auditor.auditors.jxmbnrfsfhyq_prompt import build_item_prompt
from syllabus_auditor.core.audit import FAIL, PASS, FieldFinding, SectionFinding, AuditSubject
from syllabus_auditor.core.llm import build_llm_trace, merge_llm_traces


DIMENSION = "jxmbnrfsfhyq"
DIMENSION_LABEL = "教学目标、内容、方式是否符合要求"
ITEMS = (
    ("jxmb", "教学目标是否符合要求"),
    ("jxnr", "教学内容是否符合要求"),
    ("jxfs", "教学方式是否符合要求"),
)
FALLBACK_REASON = "模型未给出不通过原因，需人工复核"
NO_LLM_REASON = "未配置 LLM，无法审核教学目标、内容、方式是否符合要求，需人工复核"


class JsonLlmClient(Protocol):
    def complete_json(self, prompt: str) -> str:
        ...


def audit_jxmbnrfsfhyq(subject: AuditSubject, llm_client: JsonLlmClient | None) -> tuple[SectionFinding, list[FieldFinding]]:
    audit_input = build_audit_input(subject.payload, subject.meta)

    if llm_client is None:
        result = _manual_review_result(NO_LLM_REASON, audit_input=audit_input, llm_client=None)
    else:
        items = []
        for key, label in ITEMS:
            prompt = build_item_prompt(audit_input, key)
            raw_response = ""
            try:
                raw_response = llm_client.complete_json(prompt)
                raw_result = parse_llm_json(raw_response)
                item = normalize_item_result(raw_result, key, label)
                item["llm_trace"] = build_llm_trace(
                    llm_client=llm_client,
                    dimension=DIMENSION,
                    item=key,
                    prompt=prompt,
                    raw_response=raw_response,
                    parsed=raw_result,
                    status="parsed",
                )
                items.append(item)
            except Exception as exc:
                reason = f"模型输出格式无法解析，需人工复核：{label}：{type(exc).__name__}: {exc}"
                item = _manual_item_result(key, label, reason)
                item["llm_trace"] = build_llm_trace(
                    llm_client=llm_client,
                    dimension=DIMENSION,
                    item=key,
                    prompt=prompt,
                    raw_response=raw_response,
                    parse_error=f"{type(exc).__name__}: {exc}",
                    status="parse_error",
                )
                items.append(item)
        result = aggregate_item_results(items)

    return build_findings(result, audit_input)


def build_audit_input(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    audit_inputs = {
        "jxmb": {
            "label": "教学目标",
            "payload_paths": ["payload.kcmb"],
            "data": _build_jxmb_data(payload),
        },
        "jxnr": {
            "label": "教学内容",
            "payload_paths": ["payload.jxnr"],
            "data": _build_jxnr_data(payload),
        },
        "jxfs": {
            "label": "教学方式",
            "payload_paths": ["payload.jxap", "payload.khfsb", "payload.kcyq", "payload.kcyqb"],
            "data": _build_jxfs_data(payload),
        },
    }
    meta_context = {
        "extraction_warnings": meta.get("extraction_warnings") or [],
        "unmapped_segments": meta.get("unmapped_segments") or [],
        "raw_text_segments": extract_raw_text_segments(meta),
    }
    return {
        "audit_subject": {
            "dimension": DIMENSION,
            "label": DIMENSION_LABEL,
        },
        "audit_inputs": audit_inputs,
        "meta_context": meta_context,
    }


def _build_jxmb_data(payload: dict[str, Any]) -> dict[str, Any]:
    kcmb = _as_dict(payload.get("kcmb"))
    return {
        "szmb": _exact_value(kcmb.get("szmb")),
        "nlmb": _exact_value(kcmb.get("nlmb")),
        "zsmb": _exact_value(kcmb.get("zsmb")),
        "mbgs": _exact_value(kcmb.get("mbgs")),
        "kzzd": _normalize_kzzd(kcmb.get("kzzd")),
    }


def _build_jxnr_data(payload: dict[str, Any]) -> dict[str, Any]:
    jxnr = _as_dict(payload.get("jxnr"))
    return {
        "tm": _as_list(jxnr.get("tm")),
        "zongxs": _exact_value(jxnr.get("zongxs")),
        "nrgs": _exact_value(jxnr.get("nrgs")),
    }


def _build_jxfs_data(payload: dict[str, Any]) -> dict[str, Any]:
    jxap = _as_dict(payload.get("jxap"))
    khfsb = _as_dict(payload.get("khfsb"))
    kcyqb = _as_dict(payload.get("kcyqb"))
    return {
        "jxap": {
            "tm": _as_list(jxap.get("tm")),
            "apgs": _exact_value(jxap.get("apgs")),
        },
        "khfsb": {
            "tm": _as_list(khfsb.get("tm")),
            "khgs": _exact_value(khfsb.get("khgs")),
        },
        "kcyq": _exact_value(payload.get("kcyq")),
        "kcyqb": {
            "tm": _as_list(kcyqb.get("tm")),
            "yqgs": _exact_value(kcyqb.get("yqgs")),
            "kzzd": _normalize_kzzd(kcyqb.get("kzzd")),
        },
    }


def extract_raw_text_segments(meta: dict[str, Any], *, max_segments: int = 12, window: int = 260) -> list[dict[str, Any]]:
    keywords = ("课程目标", "教学目标", "教学内容", "教学安排", "课程要求", "考核方式", "教学方法", "授课方式", "课程思政")
    pages = meta.get("raw_pages")
    if isinstance(pages, list):
        texts = [(index, str(text or "")) for index, text in enumerate(pages)]
    else:
        texts = [(0, str(meta.get("full_text") or ""))]

    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for page, text in texts:
        for keyword in keywords:
            for match in re.finditer(re.escape(keyword), text):
                start = max(0, match.start() - window)
                end = min(len(text), match.end() + window)
                snippet = re.sub(r"\s+", " ", text[start:end]).strip()
                key = (page, start, keyword)
                if snippet and key not in seen:
                    seen.add(key)
                    segments.append({"page": page, "keyword": keyword, "text": snippet})
                if len(segments) >= max_segments:
                    return segments
    return segments


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("LLM result is not a JSON object")
    return parsed


def normalize_llm_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "dimension": DIMENSION,
        "label": DIMENSION_LABEL,
        "result": _result_value(result.get("result")),
        "reasons": _string_list(result.get("reasons")),
        "items": [],
    }
    item_by_key = {str(item.get("key")): item for item in result.get("items") or [] if isinstance(item, dict)}
    for key, label in ITEMS:
        raw = item_by_key.get(key, {})
        item_result = _result_value(raw.get("result"))
        reasons = _string_list(raw.get("reasons"))
        if item_result == "否" and not reasons:
            reasons = [FALLBACK_REASON]
        normalized["items"].append(
            {
                "key": key,
                "label": str(raw.get("label") or label),
                "result": item_result,
                "reasons": reasons,
                "evidence_paths": _string_list(raw.get("evidence_paths")),
                "suggestion": str(raw.get("suggestion") or ""),
                "llm_trace": _as_dict(raw.get("llm_trace")),
            }
        )

    if any(item["result"] == "否" for item in normalized["items"]):
        normalized["result"] = "否"
    if normalized["result"] == "否" and not normalized["reasons"]:
        normalized["reasons"] = _collect_item_reasons(normalized["items"]) or [FALLBACK_REASON]
    return normalized


def normalize_item_result(result: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item_result = _result_value(result.get("result"))
    reasons = _string_list(result.get("reasons"))
    if item_result == "否" and not reasons:
        reasons = [f"模型未给出{label}不通过原因，需人工复核"]
    return {
        "key": key,
        "label": str(result.get("label") or label),
        "result": item_result,
        "reasons": reasons,
        "evidence_paths": _string_list(result.get("evidence_paths")),
        "suggestion": str(result.get("suggestion") or ""),
        "llm_trace": _as_dict(result.get("llm_trace")),
    }


def aggregate_item_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_items = []
    item_by_key = {str(item.get("key")): item for item in items if isinstance(item, dict)}
    for key, label in ITEMS:
        normalized_items.append(normalize_item_result(item_by_key.get(key, {}), key, label))
    result = "否" if any(item["result"] == "否" for item in normalized_items) else "是"
    reasons = _collect_item_reasons(normalized_items) if result == "否" else []
    return {
        "dimension": DIMENSION,
        "label": DIMENSION_LABEL,
        "result": result,
        "reasons": reasons or ([FALLBACK_REASON] if result == "否" else []),
        "items": normalized_items,
    }


def build_findings(result: dict[str, Any], audit_input: dict[str, Any]) -> tuple[SectionFinding, list[FieldFinding]]:
    result = normalize_llm_result(result)
    is_pass = result["result"] == "是"
    status = PASS if is_pass else FAIL
    reasons = _string_list(result.get("reasons"))
    evidence = {
        "items": [
            {
                "key": item["key"],
                "result": item["result"],
                "evidence_paths": item["evidence_paths"],
                "reasons": item["reasons"],
            }
            for item in result["items"]
        ],
        "meta_context_used": bool((audit_input.get("meta_context") or {}).get("raw_text_segments")),
    }
    llm_trace = merge_llm_traces(
        [_as_dict(item.get("llm_trace")) for item in result["items"]],
        dimension=DIMENSION,
        mode="direct_llm",
    )
    section = SectionFinding(
        wd=DIMENSION,
        status=status,
        message=result["result"],
        evidence=evidence,
        suggestion="查看 details.items 中各子项建议。" if not is_pass else "",
        details={
            "label": DIMENSION_LABEL,
            "result": result["result"],
            "reasons": reasons,
            "items": result["items"],
        },
        pdfs="direct_llm",
        llm_trace=llm_trace,
    )
    fields = [_item_to_field_finding(item) for item in result["items"]]
    return section, fields


def _item_to_field_finding(item: dict[str, Any]) -> FieldFinding:
    is_pass = item["result"] == "是"
    reasons = _string_list(item.get("reasons"))
    reason = "；".join(reasons)
    if not is_pass and not reason:
        reason = FALLBACK_REASON
    return FieldFinding(
        section=DIMENSION,
        field=item["key"],
        path=f"llm.{DIMENSION}.{item['key']}",
        status=PASS if is_pass else FAIL,
        reason="" if is_pass else reason,
        message=item["result"] if is_pass else reason,
        expected={"requirement": item["label"]},
        actual={"result": item["result"]},
        evidence={"evidence_paths": item.get("evidence_paths") or []},
        suggestion=item.get("suggestion") or "",
        llm_trace=_as_dict(item.get("llm_trace")),
    )


def _manual_review_result(
    reason: str,
    *,
    audit_input: dict[str, Any] | None = None,
    llm_client: JsonLlmClient | None = None,
) -> dict[str, Any]:
    return {
        "dimension": DIMENSION,
        "label": DIMENSION_LABEL,
        "result": "否",
        "reasons": [reason],
        "items": [
            _manual_item_result(
                key,
                label,
                reason,
                llm_trace=build_llm_trace(
                    llm_client=llm_client,
                    dimension=DIMENSION,
                    item=key,
                    prompt=build_item_prompt(audit_input, key) if audit_input else "",
                    status="no_llm",
                ),
            )
            for key, label in ITEMS
        ],
    }


def _manual_item_result(
    key: str,
    label: str,
    reason: str,
    *,
    llm_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "result": "否",
        "reasons": [reason],
        "evidence_paths": [],
        "suggestion": "配置 LLM 后重新审核，或进行人工复核。",
        "llm_trace": llm_trace or {},
    }


def _result_value(value: Any) -> str:
    return "是" if str(value).strip() == "是" else "否"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _collect_item_reasons(items: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in items:
        if item.get("result") == "否":
            reasons.extend(_string_list(item.get("reasons")))
    return reasons


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
