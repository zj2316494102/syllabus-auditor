"""维度：教学目标、内容、方式是否符合要求（jxmbnrfsfhyq）。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from syllabus_auditor.core.audit import FAIL, NO, PASS, YES, AuditSubject, FieldFinding, SectionFinding
from syllabus_auditor.core.llm import EmptyLlmResponseError, build_llm_trace, merge_llm_traces
from syllabus_auditor.shared.reason_text import clean_customer_reason
from syllabus_auditor.utils import (
    CONTENT_LAYOUT_RULES,
    EMPTY_LLM_REASON,
    FALLBACK_REASON,
    MANUAL_REVIEW_SUGGESTION,
    JsonLlmClient,
    as_dict,
    build_jxfs_audit_data,
    build_jxnr_audit_data,
    build_kcmb_audit_data,
    extract_page_keyword_segments,
    merge_reasons,
    parse_llm_json,
    result_value,
    string_list,
)

DIMENSION = "jxmbnrfsfhyq"
DIMENSION_LABEL = "教学目标、内容、方式是否符合要求"
NO_LLM_REASON = f"未配置 LLM，无法审核{DIMENSION_LABEL}，需人工复核"

ITEMS = (
    ("jxmb", "教学目标是否符合要求"),
    ("jxnr", "教学内容是否符合要求"),
    ("jxfs", "教学方式是否符合要求"),
)

_ITEM_PROMPTS = {
    "jxmb": {
        "label": "教学目标是否符合要求",
        "data_label": "教学目标",
        "requirement": (
            "重点判断课程目标是否从知识、能力、价值观等方面设定，目标是否明确清晰；"
            "是否体现立德树人、课程思政与专业知识融合；是否引导学生增强责任感、使命感，"
            "将个人追求融入国家富强、民族振兴、人民幸福。"
        ),
        "evidence_examples": (
            "audit_input.data.primary.szmb、audit_input.data.primary.nlmb、audit_input.data.primary.zsmb、"
            "audit_input.data.supplement.mbgs（overview_only 或 goals_with_supplement 时）、"
            "meta_context.raw_text_segments[0].text"
        ),
    },
    "jxnr": {
        "label": "教学内容是否符合要求",
        "data_label": "教学内容",
        "requirement": (
            "重点判断教学内容是否充实、知识体系是否完善、重难点是否清楚、进度是否合理；"
            "是否反映学科前沿并体现新财经战略升级要求；是否有机融入党的二十大精神、"
            "习近平新时代中国特色社会主义思想、党的领导、党史、新中国史、改革开放史、社会主义发展史等内容；"
            "专业学位课程是否体现职业实践性、行业实践和实务实操设计。"
        ),
        "evidence_examples": (
            "audit_input.data.primary.tm[0].zsd、audit_input.data.supplement.nrgs（overview_only 或 table_with_supplement 时）、"
            "meta_context.raw_text_segments[0].text"
        ),
    },
    "jxfs": {
        "label": "教学方式是否符合要求",
        "data_label": "教学方式",
        "requirement": (
            "重点判断教学安排、考核方式、课程要求中是否体现明确、合理、可执行的教学方式；"
            "教学方式可以是单一方式，也可以是多种方式组合，不得仅因教学方式单一判否；"
            "可接受的教学方式包括但不限于讲授、专题讲授、阅读、讨论、案例分析、作业讲评、"
            "实践、实验、汇报、研讨、线上线下结合等；"
            "重点判断教学方式是否与课程目标、教学内容和课程要求基本匹配，是否能支撑课程实施；"
            "如果教学方式较单一但表述明确、能落地执行，应判为“是”，可在 suggestion 中建议进一步丰富教学方法；"
            "只有在教学方式缺失、表述空泛不可执行，或与课程内容明显不匹配时，才判为“否”。"
        ),
        "extra_rules": (
            "教学方式补充规则：\n"
            "- 不得仅因教学方式单一、未体现多种教学方法组合、未出现案例教学/实践/情境模拟等方式而判否。\n"
            "- 如果出现明确教学方式，如“讲授”“课堂讲授”“专题讲授”“阅读”“讨论”“作业讲评”等，即使方式较少，也应视为具备教学方式。\n"
            "- 如果教学方式只是“采用多种方式”“灵活教学”“理论联系实际”等空泛表述，且没有具体方式或实施场景，result 可判“否”。\n"
            "- 如果教学方式较单一但明确可执行，应在 suggestion 中建议进一步丰富教学方法，不应直接判否。"
        ),
        "evidence_examples": (
            "audit_input.data.jxap.primary.tm[0].skfs、audit_input.data.khfsb.primary.tm[0].kcfs、"
            "audit_input.data.kcyq、meta_context.raw_text_segments[0].text"
        ),
    },
}


def _audit_jxmbnrfsfhyq_item(
    audit_input: dict[str, Any],
    key: str,
    label: str,
    llm_client: JsonLlmClient,
) -> dict[str, Any]:
    prompt = _build_item_prompt(audit_input, key)
    raw_response = ""
    try:
        raw_response = llm_client.complete_json(prompt)
        raw_result = parse_llm_json(raw_response)
        item = _normalize_item_result(raw_result, key, label)
        item["llm_trace"] = build_llm_trace(
            llm_client=llm_client,
            dimension=DIMENSION,
            item=key,
            prompt=prompt,
            raw_response=raw_response,
            parsed=raw_result,
            status="parsed",
        )
        return item
    except EmptyLlmResponseError as exc:
        reason = f"{EMPTY_LLM_REASON}：{label}"
        item = _manual_item_result(key, label, reason)
        item["llm_trace"] = build_llm_trace(
            llm_client=llm_client,
            dimension=DIMENSION,
            item=key,
            prompt=prompt,
            raw_response=raw_response,
            parse_error=str(exc),
            status="empty_response",
        )
        return item
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
        return item


def audit_jxmbnrfsfhyq(subject: AuditSubject, llm_client: JsonLlmClient | None) -> tuple[SectionFinding, list[FieldFinding]]:
    audit_input = build_audit_input(subject.payload, subject.meta)
    if llm_client is None:
        result = _manual_review_result(NO_LLM_REASON, audit_input=audit_input, llm_client=None)
    else:
        with ThreadPoolExecutor(max_workers=len(ITEMS)) as executor:
            futures = [
                executor.submit(_audit_jxmbnrfsfhyq_item, audit_input, key, label, llm_client)
                for key, label in ITEMS
            ]
            items = [future.result() for future in futures]
        result = _aggregate_item_results(items)
    return _build_findings(result, audit_input)


def build_audit_input(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_subject": {"dimension": DIMENSION, "label": DIMENSION_LABEL},
        "audit_inputs": {
            "jxmb": {
                "label": "教学目标",
                "payload_paths": ["payload.kcmb"],
                "data": build_kcmb_audit_data(payload),
            },
            "jxnr": {
                "label": "教学内容",
                "payload_paths": ["payload.jxnr"],
                "data": build_jxnr_audit_data(payload),
            },
            "jxfs": {
                "label": "教学方式",
                "payload_paths": ["payload.jxap", "payload.khfsb", "payload.kcyq"],
                "data": build_jxfs_audit_data(payload),
            },
        },
        "meta_context": {
            "extraction_warnings": meta.get("extraction_warnings") or [],
            "unmapped_segments": meta.get("unmapped_segments") or [],
            "raw_text_segments": _extract_raw_text_segments(meta),
        },
    }


def _extract_raw_text_segments(meta: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = (
        "课程目标",
        "教学目标",
        "教学内容",
        "教学安排",
        "课程要求",
        "考核方式",
        "教学方法",
        "授课方式",
        "课程思政",
    )
    return extract_page_keyword_segments(meta, keywords)


def _build_item_prompt(audit_input: dict[str, Any], item_key: str) -> str:
    config = _ITEM_PROMPTS[item_key]
    item_input = {
        "audit_subject": {
            "dimension": DIMENSION,
            "dimension_label": DIMENSION_LABEL,
            "item": item_key,
            "label": config["label"],
        },
        "audit_input": {
            "label": config["data_label"],
            **((audit_input.get("audit_inputs") or {}).get(item_key) or {}),
        },
        "meta_context": audit_input.get("meta_context") or {},
    }
    input_json = json.dumps(item_input, ensure_ascii=False, indent=2)
    extra_rules = str(config.get("extra_rules") or "").strip()
    extra_rules_block = f"\n{extra_rules}\n" if extra_rules else ""
    return f"""你是课程方案审核专家。请审核“{config["label"]}”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
audit_input 是本次审核的主体材料，只包含“{config["data_label"]}”相关结构化字段。
meta_context 只是辅助证据，只能在 content_layout 为 empty 或抽取明显不完整时参考。
禁止使用其他审核子项内容替代本子项证据。

{CONTENT_LAYOUT_RULES}

审核要求：
{config["requirement"]}

判断规则：
1. 符合要求时 result 写“是”，否则写“否”。
2. content_layout 为 empty，或主字段表述笼统、无法体现审核要求时，result 必须写“否”。
3. content_layout 为 goals_only 或 table_only 时，补充字段（mbgs/nrgs/apgs/khgs）为空不算缺失，不得因此判否。
4. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
5. 如果 meta_context 中有相关原文但 content_layout 为 empty，应写明“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
6. evidence_paths 必须引用输入 JSON 中实际存在的路径，例如：{config["evidence_examples"]}。
7. 不要因为出现少量政策关键词就直接判通过，要判断是否与课程专业内容有机融合。
8. suggestion 必须给出可执行修改建议。
9. reasons 和 checks.reason 面向甲方展示，不得输出字段 key、JSON 路径或内部代码名，例如 szmb、jxap、khfsb、kcyq、payload、audit_input；应改写为思政目标、教学安排、考核方式、课程要求、审核材料等中文业务名称。
{extra_rules_block}
输入 JSON：
{input_json}

请输出严格 JSON，不要输出 Markdown：
{{
  "key": "{item_key}",
  "label": "{config["label"]}",
  "result": "是或否",
  "reasons": [],
  "evidence_paths": [],
  "suggestion": ""
}}
"""


def _normalize_item_result(result: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item_result = result_value(result.get("result"))
    reasons = [clean_customer_reason(item) for item in string_list(result.get("reasons"))]
    if item_result == NO and not reasons:
        reasons = [f"模型未给出{label}不通过原因，需人工复核"]
    return {
        "key": key,
        "label": str(result.get("label") or label),
        "result": item_result,
        "reasons": reasons,
        "evidence_paths": string_list(result.get("evidence_paths")),
        "suggestion": str(result.get("suggestion") or ""),
        "llm_trace": as_dict(result.get("llm_trace")),
    }


def _aggregate_item_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    item_by_key = {str(item.get("key")): item for item in items if isinstance(item, dict)}
    normalized_items = [_normalize_item_result(item_by_key.get(key, {}), key, label) for key, label in ITEMS]
    overall = NO if any(item["result"] == NO for item in normalized_items) else YES
    reasons = _collect_item_reasons(normalized_items) if overall == NO else []
    return {
        "dimension": DIMENSION,
        "label": DIMENSION_LABEL,
        "result": overall,
        "reasons": reasons or ([FALLBACK_REASON] if overall == NO else []),
        "items": normalized_items,
    }


def _normalize_llm_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "dimension": DIMENSION,
        "label": DIMENSION_LABEL,
        "result": result_value(result.get("result")),
        "reasons": string_list(result.get("reasons")),
        "items": [],
    }
    item_by_key = {str(item.get("key")): item for item in result.get("items") or [] if isinstance(item, dict)}
    for key, label in ITEMS:
        raw = item_by_key.get(key, {})
        item_result = result_value(raw.get("result"))
        reasons = [clean_customer_reason(item) for item in string_list(raw.get("reasons"))]
        if item_result == NO and not reasons:
            reasons = [FALLBACK_REASON]
        normalized["items"].append(
            {
                "key": key,
                "label": str(raw.get("label") or label),
                "result": item_result,
                "reasons": reasons,
                "evidence_paths": string_list(raw.get("evidence_paths")),
                "suggestion": str(raw.get("suggestion") or ""),
                "llm_trace": as_dict(raw.get("llm_trace")),
            }
        )
    if any(item["result"] == NO for item in normalized["items"]):
        normalized["result"] = NO
    if normalized["result"] == NO:
        normalized["reasons"] = merge_reasons(normalized["reasons"], _collect_item_reasons(normalized["items"])) or [
            FALLBACK_REASON
        ]
    return normalized


def _build_findings(result: dict[str, Any], audit_input: dict[str, Any]) -> tuple[SectionFinding, list[FieldFinding]]:
    result = _normalize_llm_result(result)
    is_pass = result["result"] == YES
    status = PASS if is_pass else FAIL
    reasons = [clean_customer_reason(item) for item in string_list(result.get("reasons"))]
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
        [as_dict(item.get("llm_trace")) for item in result["items"]],
        dimension=DIMENSION,
        mode="direct_llm",
    )
    section = SectionFinding(
        wd=DIMENSION,
        status=status,
        message=result["result"],
        evidence=evidence,
        suggestion="查看 details.items 中各子项建议。" if not is_pass else "",
        details={"label": DIMENSION_LABEL, "result": result["result"], "reasons": reasons, "items": result["items"]},
        pdfs="direct_llm",
        llm_trace=llm_trace,
    )
    return section, [_item_to_field_finding(item) for item in result["items"]]


def _item_to_field_finding(item: dict[str, Any]) -> FieldFinding:
    is_pass = item["result"] == YES
    reasons = string_list(item.get("reasons"))
    reason = clean_customer_reason("；".join(reasons))
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
        llm_trace=as_dict(item.get("llm_trace")),
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
        "result": NO,
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
                    prompt=_build_item_prompt(audit_input, key) if audit_input else "",
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
        "result": NO,
        "reasons": [reason],
        "evidence_paths": [],
        "suggestion": MANUAL_REVIEW_SUGGESTION,
        "llm_trace": llm_trace or {},
    }


def _collect_item_reasons(items: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in items:
        if item.get("result") == NO:
            reasons.extend(string_list(item.get("reasons")))
    return merge_reasons(reasons)




