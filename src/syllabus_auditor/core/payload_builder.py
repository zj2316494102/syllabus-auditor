from __future__ import annotations

import re
from typing import Any

from syllabus_auditor.core.types import ExtractionRaw

JCXX_FIELD_MAP = {
    "课程编号": "kcbh",
    "开课（院）系": "kkyx",
    "中文课程名称": "zwkcmc",
    "英文课程名称": "ywkcmc",
    "授课语言": "skyy",
    "是否允许外学院选课": "sfyxwxyxk",
    "考核方式": "khfs",
    "课程性质": "kcxz",
    "课程类别": "kclb",
    "周学时": "zxs",
    "上课周数": "skzs",
    "总学时": "zongxs",
    "教学学时": "jxxs",
    "实验学时": "syxs",
    "实践学时": "sjxs",
    "其他学时": "qtxs",
    "自学学时": "zxxs",
    "课程学分": "kcxf",
    "任课教师姓名": "rkjsxm",
    "教师工号": "jsgh",
    "E-mail": "email",
    "联系电话": "lxdh",
}

CONTENT_ITEM_MAP = {
    "序号": "xh",
    "主题": "zt",
    "知识点": "zsd",
    "学时": "xs",
}

SCHEDULE_ITEM_MAP = {
    "序号": "zs",
    "授课内容": "sknr",
    "授课方式": "skfs",
    "作业": "zy",
    "思政元素的融入和预期教学成效": "szyqjxx",
}

ASSESSMENT_ITEM_MAP = {
    "考试形式": "ksxs",
    "考察内容": "kcnr",
    "考察方式": "kcfs",
    "占比": "zb",
}

REQUIREMENT_ITEM_MAP = {
    "要求类型": "yqlx",
    "要求内容": "yqnr",
    "作业要求": "zyyq",
    "考勤要求": "kqyq",
    "阅读要求": "ydyq",
}

EMPTY_MARKERS = {
    "",
    "不填",
    "未填",
    "无",
    "暂无",
    "无特殊要求",
    "无特殊",
    "none",
    "null",
    "n/a",
    "na",
}

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


def _extract_total_hours(full_text: str, teaching_content: list[dict[str, Any]]) -> str:
    patterns = [
        r"课时总计[：:]\s*(\d+)\s*学时",
        r"学时总计[：:]\s*(\d+)\s*学时",
        r"课时总计[：:]\s*学时\s*(\d+)",
        r"总学时[：:]\s*(\d+)",
    ]
    for pattern in patterns:
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
    if not zongxs:
        zongxs = jcxx.get("zongxs", "")

    if content_items:
        jxnr: dict[str, Any] = {"tm": content_items, "zongxs": zongxs, "nrgs": ""}
    else:
        jxnr = {"tm": [], "zongxs": zongxs, "nrgs": _clean_value(cn.get("教学内容概述", ""))}

    schedule_items = [_map_row(row, SCHEDULE_ITEM_MAP) for row in raw.course_schedule]
    schedule_items = [item for item in schedule_items if item]
    if schedule_items:
        jxap: dict[str, Any] = {"tm": schedule_items, "apgs": ""}
    else:
        jxap = {"tm": [], "apgs": _clean_value(cn.get("课程安排概述", ""))}

    assessment_items = [_map_row(row, ASSESSMENT_ITEM_MAP) for row in raw.assessment_rows]
    assessment_items = [item for item in assessment_items if item]
    khgs = _clean_value(cn.get("考核方式说明", ""))
    if assessment_items:
        khfsb: dict[str, Any] = {"tm": assessment_items, "khgs": ""}
    else:
        khfsb = {"tm": [], "khgs": khgs}

    requirement_items = [_map_row(row, REQUIREMENT_ITEM_MAP) for row in raw.course_requirements]
    requirement_items = [item for item in requirement_items if item]
    course_requirement_text = _clean_value(cn.get("课程要求", ""))
    if requirement_items:
        kcyqb: dict[str, Any] = {"tm": requirement_items, "yqgs": "", "kzzd": []}
    else:
        kcyqb = {"tm": [], "yqgs": "", "kzzd": []}

    payload: dict[str, Any] = {
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
    return payload
