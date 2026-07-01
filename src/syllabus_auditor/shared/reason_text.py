"""将内部字段路径替换为客户可读的中文审核理由。"""

from __future__ import annotations

import re
from typing import Any


INTERNAL_LABELS: tuple[tuple[str, str], ...] = (
    ("payload.kcmb.szmb", "思政目标"),
    ("payload.kcmb.nlmb", "能力目标"),
    ("payload.kcmb.zsmb", "知识目标"),
    ("payload.kcmb.mbgs", "课程目标概述"),
    ("payload.jxap.tm[].szyqjxx", "教学安排中的思政元素融入"),
    ("payload.jxap.tm[].sknr", "教学安排中的授课内容"),
    ("payload.jxap.tm[].skfs", "教学安排中的授课方式"),
    ("payload.jxap.apgs", "教学安排概述"),
    ("payload.jxap", "教学安排"),
    ("payload.khfsb", "考核方式"),
    ("payload.kcyq", "课程要求"),
    ("payload.jxnr", "教学内容"),
    ("payload.kcmb", "课程目标"),
    ("payload_data.kcmb.data.szmb", "思政目标"),
    ("payload_data.kcmb.data.mbgs", "课程目标概述"),
    ("audit_input.data.primary.szmb", "思政目标"),
    ("audit_input.data.primary.nlmb", "能力目标"),
    ("audit_input.data.primary.zsmb", "知识目标"),
    ("audit_input.data.supplement.mbgs", "课程目标概述"),
    ("audit_input.data.jxap.primary.tm[0].skfs", "教学安排中的授课方式"),
    ("audit_input.data.khfsb.primary.tm[0].kcfs", "考核方式中的考察方式"),
    ("audit_input.data.kcyq", "课程要求"),
    ("primary.szmb", "思政目标"),
    ("supplement.mbgs", "课程目标概述"),
    ("khfsb", "考核方式"),
    ("jxap", "教学安排"),
    ("jxnr", "教学内容"),
    ("kcmb", "课程目标"),
    ("kcyq", "课程要求"),
    ("szmb", "思政目标"),
    ("nlmb", "能力目标"),
    ("zsmb", "知识目标"),
    ("szyqjxx", "思政元素融入"),
    ("mbgs", "课程目标概述"),
    ("nrgs", "教学内容概述"),
    ("apgs", "教学安排概述"),
    ("khgs", "考核方式说明"),
    ("tm", "表格条目"),
)


def clean_customer_reason(text: Any) -> str:
    result = str(text or "")
    if not result:
        return ""
    for internal, label in sorted(INTERNAL_LABELS, key=lambda item: len(item[0]), reverse=True):
        result = result.replace(internal, label)
    result = re.sub(r"\baudit_input\b", "审核材料", result)
    result = re.sub(r"\bmeta_context\b", "原文辅助信息", result)
    result = re.sub(r"\bmeta\b", "原文辅助信息", result)
    result = re.sub(r"\bpayload_data\b", "结构化抽取结果", result)
    result = re.sub(r"\bpayload\b", "结构化抽取结果", result)
    return result


def clean_customer_reasons(value: Any) -> Any:
    if isinstance(value, str):
        return clean_customer_reason(value)
    if isinstance(value, list):
        return [clean_customer_reasons(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_customer_reasons(item) for key, item in value.items()}
    return value
