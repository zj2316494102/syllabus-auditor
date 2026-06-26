from __future__ import annotations

import re
from typing import Any

from config import load_project_config
from syllabus_auditor.core.types import ExtractionRaw


def _payload_config() -> dict[str, Any]:
    value = load_project_config().get("payload", {})
    return value if isinstance(value, dict) else {}


JCXX_FIELD_MAP = dict(_payload_config().get("jcxx_field_map") or {})
CONTENT_ITEM_MAP = dict(_payload_config().get("content_item_map") or {})
SCHEDULE_ITEM_MAP = dict(_payload_config().get("schedule_item_map") or {})
ASSESSMENT_ITEM_MAP = dict(_payload_config().get("assessment_item_map") or {})
EMPTY_MARKERS = {str(item).lower() for item in (_payload_config().get("empty_markers") or [])}
TOTAL_HOURS_PATTERNS = [str(item) for item in (_payload_config().get("total_hours_patterns") or [])]
COURSE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"\s+", "", text).lower()
    if normalized in EMPTY_MARKERS:
        return ""
    return text


def _clean_course_code(value: Any) -> str:
    text = _clean_value(value)
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    if not COURSE_CODE_RE.fullmatch(compact):
        return ""
    return compact


def _map_extras(extras: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(extras, dict):
        return []
    rows: list[dict[str, str]] = []
    for label, value in extras.items():
        cleaned = _clean_value(value)
        if cleaned:
            rows.append({"bt": str(label), "nr": cleaned})
    return rows


def _map_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for cn_key, py_key in mapping.items():
        value = _clean_value(row.get(cn_key, ""))
        if value:
            mapped[py_key] = value
    extras = _map_extras(row.get("kzzd"))
    if extras:
        mapped["kzzd"] = extras
    return mapped


_SZ_CN = "思政元素的融入和预期教学成效"
_SZ_PY = "szyqjxx"
_SZ_KZZD_KEYS = ("思政", "预期教学成效", "课程思政", "思政元素", "思政融入")


def _promote_schedule_sz_cn(row: dict[str, Any]) -> dict[str, Any]:
    if _clean_value(row.get(_SZ_CN)):
        return row

    kzzd = row.get("kzzd")
    if isinstance(kzzd, dict):
        for label, value in kzzd.items():
            if any(key in str(label) for key in _SZ_KZZD_KEYS):
                cleaned = _clean_value(value)
                if cleaned:
                    row[_SZ_CN] = cleaned
                    return row

    sknr = str(row.get("授课内容") or "")
    if "思政" in sknr:
        idx = sknr.find("思政")
        row[_SZ_CN] = _clean_value(sknr[idx:])
        row["授课内容"] = _clean_value(sknr[:idx])

    return row


def _extract_total_hours(full_text: str, teaching_content: list[dict[str, Any]]) -> str:
    for pattern in TOTAL_HOURS_PATTERNS:
        match = re.search(pattern, full_text)
        if match:
            return match.group(1)

    total = 0
    found = False
    for item in teaching_content:
        hours = item.get("学时", "")
        if re.fullmatch(r"\d+", hours or ""):
            total += int(hours)
            found = True
    return str(total) if found else ""


def build_payload(raw: ExtractionRaw) -> dict[str, Any]:
    cn = raw.cn_data

    jcxx: dict[str, str] = {}
    for cn_key, py_key in JCXX_FIELD_MAP.items():
        if py_key == "kcbh":
            value = _clean_course_code(cn.get(cn_key, ""))
        else:
            value = _clean_value(cn.get(cn_key, ""))
        if value:
            jcxx[py_key] = value

    szmb = _clean_value(cn.get("思政目标", ""))
    nlmb = _clean_value(cn.get("能力目标", ""))
    zsmb = _clean_value(cn.get("知识目标", ""))
    if szmb or nlmb or zsmb:
        kcmb = {"szmb": szmb, "nlmb": nlmb, "zsmb": zsmb, "mbgs": ""}
    else:
        overview = _clean_value(cn.get("课程目标概述", ""))
        kcmb = {"szmb": "", "nlmb": "", "zsmb": "", "mbgs": overview}
    if raw.course_goal_extras:
        kcmb["kzzd"] = _map_extras(raw.course_goal_extras)

    content_items = [_map_row(row, CONTENT_ITEM_MAP) for row in raw.teaching_content]
    content_items = [item for item in content_items if item]
    zongxs = _extract_total_hours(raw.full_text, raw.teaching_content)

    if content_items:
        jxnr: dict[str, Any] = {"tm": content_items, "zongxs": zongxs, "nrgs": ""}
    else:
        jxnr = {"tm": [], "zongxs": zongxs, "nrgs": _clean_value(cn.get("教学内容概述", ""))}

    schedule_items = [
        _map_row(_promote_schedule_sz_cn(dict(row)), SCHEDULE_ITEM_MAP)
        for row in raw.course_schedule
    ]
    schedule_items = [item for item in schedule_items if item]
    if schedule_items:
        jxap: dict[str, Any] = {"tm": schedule_items, "apgs": ""}
    else:
        jxap = {"tm": [], "apgs": _clean_value(cn.get("课程安排概述", ""))}

    # khfsb 互斥：parse 阶段已判别 table→tm / text→khgs（见 apply_khfsb_source）
    if raw.assessment_rows:
        assessment_items = [_map_row(row, ASSESSMENT_ITEM_MAP) for row in raw.assessment_rows]
        assessment_items = [item for item in assessment_items if item]
        khfsb: dict[str, Any] = {"tm": assessment_items, "khgs": ""}
    else:
        khfsb = {"tm": [], "khgs": _clean_value(cn.get("考核方式说明", ""))}

    course_requirement_text = _clean_value(cn.get("课程要求", ""))
    kcyqb: dict[str, Any] = {"tm": [], "yqgs": "", "kzzd": []}

    return {
        "jcxx": jcxx,
        "kczwjj": _clean_value(cn.get("课程中文简介", "")),
        "kcywjj": _clean_value(cn.get("课程英文简介", "")),
        "ybzsyq": _clean_value(cn.get("预备知识要求", "")),
        "jcjydcl": _clean_value(cn.get("阅读材料", "")),
        "kcmb": kcmb,
        "jxnr": jxnr,
        "jxap": jxap,
        "kcyq": course_requirement_text,
        "kcyqb": kcyqb,
        "khfsb": khfsb,
    }

