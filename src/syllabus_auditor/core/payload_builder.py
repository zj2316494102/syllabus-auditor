"""将 ExtractionRaw 映射为规范 payload JSON（章节字段结构化）。"""

from __future__ import annotations

import re
from typing import Any

from syllabus_auditor.shared.config import load_project_config
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
COURSE_CODE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{1,30}[A-Za-z0-9])$")
COURSE_CODE_LABEL_RE = re.compile(
    r"(?:课程编号|课程代码|编号|kcbh|course\s*code)\s*[:：]?\s*"
    r"([A-Za-z0-9](?:[A-Za-z0-9._-]{1,30}[A-Za-z0-9])?)",
    re.IGNORECASE,
)
COURSE_CODE_TITLE_KEYWORDS = (
    "附件",
    "课程实施方案",
    "课程方案",
    "教学大纲",
    "完整版",
    "修订版",
    "最终版",
    "新版",
)


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
    if any(keyword in compact for keyword in COURSE_CODE_TITLE_KEYWORDS):
        return ""
    if COURSE_CODE_RE.fullmatch(compact):
        return compact
    match = COURSE_CODE_LABEL_RE.search(text)
    if match and COURSE_CODE_RE.fullmatch(match.group(1)):
        return match.group(1)
    return ""


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


def _promote_schedule_homework_to_kzzd(row: dict[str, Any]) -> dict[str, Any]:
    """作业非模板标准列；旧抽取若带顶层「作业」则并入 kzzd。"""
    homework = _clean_value(row.pop("作业", ""))
    if not homework:
        return row
    kzzd = row.get("kzzd")
    if not isinstance(kzzd, dict):
        kzzd = {}
        row["kzzd"] = kzzd
    if "作业" not in kzzd:
        kzzd["作业"] = homework
    return row


def _finalize_schedule_item(mapped: dict[str, Any]) -> dict[str, Any]:
    """旧 payload 若仍含 zy，合并进 kzzd 后移除。"""
    zy = _clean_value(mapped.pop("zy", ""))
    if not zy:
        return mapped
    extras = mapped.setdefault("kzzd", [])
    if isinstance(extras, list):
        extras.append({"bt": "作业", "nr": zy})
    return mapped


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

def _sum_mapped_item_hours(items: list[dict[str, Any]]) -> str:
    total = 0.0
    found = False
    for item in items:
        value = _clean_value(item.get("xs"))
        if not re.fullmatch(r"\d+(?:\.\d+)?", value):
            continue
        total += float(value)
        found = True
    if not found:
        return ""
    return str(int(total)) if total.is_integer() else f"{total:g}"


_TEXT_TOTAL_HOURS_RE = re.compile(
    r"(?:"
    r"(?:教学内容|课程内容|上述内容|以上内容|本部分|本章节|本课程)?\s*(?:共计|共|合计|总计)"
    r"|(?:课时|学时)\s*总计"
    r"|总学时"
    r")"
    r"\s*(?:为|是|[:：])?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:学时|课时)"
)


def _extract_text_total_hours_fallback(*texts: str) -> str:
    candidates: list[str] = []
    for text in texts:
        cleaned = _clean_value(text)
        if not cleaned:
            continue
        candidates.extend(match.group(1) for match in _TEXT_TOTAL_HOURS_RE.finditer(cleaned))
    if not candidates:
        return ""
    value = candidates[-1]
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _join_supplement_parts(*parts: str) -> str:
    seen: list[str] = []
    for part in parts:
        cleaned = _clean_value(part)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return "\n".join(seen)


def _collect_unmapped_from_cn_rows(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        kzzd = row.get("kzzd")
        if not isinstance(kzzd, dict):
            continue
        for label, value in kzzd.items():
            cleaned = _clean_value(value)
            if not cleaned:
                continue
            label_text = _clean_value(label)
            parts.append(f"{label_text}：{cleaned}" if label_text else cleaned)
    return _join_supplement_parts(*parts)


def _collect_unmapped_from_mapped_rows(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        extras = row.get("kzzd")
        if not isinstance(extras, list):
            continue
        for extra in extras:
            if not isinstance(extra, dict):
                continue
            label = _clean_value(extra.get("bt"))
            content = _clean_value(extra.get("nr"))
            if not content:
                continue
            parts.append(f"{label}：{content}" if label else content)
    return _join_supplement_parts(*parts)


def _extras_dict_to_text(extras: dict[str, Any] | None) -> str:
    if not isinstance(extras, dict):
        return ""
    parts: list[str] = []
    for label, value in extras.items():
        cleaned = _clean_value(value)
        if not cleaned:
            continue
        label_text = _clean_value(label)
        parts.append(f"{label_text}：{cleaned}" if label_text else cleaned)
    return _join_supplement_parts(*parts)


def _section_supplement(
    cn_overview: str,
    *,
    cn_rows: list[dict[str, Any]] | None = None,
    mapped_rows: list[dict[str, Any]] | None = None,
    extra_dict: dict[str, Any] | None = None,
) -> str:
    unmapped_text = _collect_unmapped_from_mapped_rows(mapped_rows or [])
    if not unmapped_text:
        unmapped_text = _collect_unmapped_from_cn_rows(cn_rows or [])
    return _join_supplement_parts(
        cn_overview,
        unmapped_text,
        _extras_dict_to_text(extra_dict),
    )


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
    mbgs = _section_supplement(
        cn.get("课程目标概述", ""),
        extra_dict=raw.course_goal_extras,
    )
    kcmb: dict[str, Any] = {"szmb": szmb, "nlmb": nlmb, "zsmb": zsmb, "mbgs": mbgs}
    if raw.course_goal_extras:
        kcmb["kzzd"] = _map_extras(raw.course_goal_extras)

    content_items = [_map_row(row, CONTENT_ITEM_MAP) for row in raw.teaching_content]
    content_items = [item for item in content_items if item]
    section_meta = raw.section_extraction if isinstance(raw.section_extraction, dict) else {}
    nrgs = _section_supplement(
        cn.get("教学内容概述", ""),
        cn_rows=raw.teaching_content,
        mapped_rows=content_items,
    )
    zongxs = _extract_total_hours(raw.full_text, raw.teaching_content)
    practice_total = _clean_value(section_meta.get("content_total_hours"))
    if practice_total:
        zongxs = practice_total
    if not zongxs:
        zongxs = _sum_mapped_item_hours(content_items)
    if not zongxs:
        zongxs = _extract_text_total_hours_fallback(nrgs, cn.get("教学内容概述", ""))
    jxnr: dict[str, Any] = {"tm": content_items, "zongxs": zongxs, "nrgs": nrgs}

    schedule_items = [
        _finalize_schedule_item(
            _map_row(
                _promote_schedule_sz_cn(_promote_schedule_homework_to_kzzd(dict(row))),
                SCHEDULE_ITEM_MAP,
            )
        )
        for row in raw.course_schedule
    ]
    schedule_items = [item for item in schedule_items if item]
    apgs = _section_supplement(
        cn.get("课程安排概述", ""),
        cn_rows=raw.course_schedule,
        mapped_rows=schedule_items,
    )
    jxap: dict[str, Any] = {"tm": schedule_items, "apgs": apgs}

    assessment_items = [_map_row(row, ASSESSMENT_ITEM_MAP) for row in raw.assessment_rows]
    assessment_items = [item for item in assessment_items if item]
    khgs = _section_supplement(
        cn.get("考核方式说明", ""),
        cn_rows=raw.assessment_rows,
        mapped_rows=assessment_items,
    )
    khfsb: dict[str, Any] = {"tm": assessment_items, "khgs": khgs}

    course_requirement_text = _clean_value(cn.get("课程要求", ""))

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
        "khfsb": khfsb,
    }



