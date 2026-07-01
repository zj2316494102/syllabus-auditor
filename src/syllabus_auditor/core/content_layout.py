"""章节主字段与概述/补充字段的内容布局判定（供 quality / LLM 审核共用）。"""

from __future__ import annotations

from typing import Any

KCMB_GOAL_KEYS = ("szmb", "nlmb", "zsmb")
TABLE_SECTIONS = ("jxnr", "jxap", "khfsb")
OVERVIEW_BY_SECTION = {
    "jxnr": "nrgs",
    "jxap": "apgs",
    "khfsb": "khgs",
    "kcmb": "mbgs",
}

LAYOUT_NOTES = {
    "empty": "主字段与补充字段均无实质内容。",
    "goals_only": "课程目标已分项填写（思政/能力/知识目标）；mbgs 为空表示无额外补充，属正常。",
    "goals_with_supplement": "课程目标分项与 mbgs 补充说明并存。",
    "overview_only": "无分项/表格，仅概述或补充文本。",
    "table_only": "表格/分项已有实质内容；概述字段为空表示无额外补充，属正常。",
    "table_with_supplement": "表格/分项与概述补充并存。",
}


def _is_substantive(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_is_substantive(item) for item in value)
    if isinstance(value, dict):
        return any(_is_substantive(v) for v in value.values())
    return bool(value)


def _has_substantive_rows(rows: Any) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if key == "kzzd":
                if _is_substantive(value):
                    return True
                continue
            if _is_substantive(value):
                return True
    return False


def _has_kcmb_goals(block: dict[str, Any]) -> bool:
    return any(_is_substantive(block.get(key)) for key in KCMB_GOAL_KEYS)


def _has_kcmb_kzzd(block: dict[str, Any]) -> bool:
    kzzd = block.get("kzzd")
    if isinstance(kzzd, list):
        return any(_is_substantive(item) for item in kzzd)
    return _is_substantive(kzzd)


def kcmb_content_layout(block: dict[str, Any] | None) -> str:
    data = block if isinstance(block, dict) else {}
    has_goals = _has_kcmb_goals(data)
    has_mbgs = _is_substantive(data.get("mbgs"))
    has_kzzd = _has_kcmb_kzzd(data)
    if has_goals or has_kzzd:
        if has_mbgs:
            return "goals_with_supplement"
        return "goals_only"
    if has_mbgs:
        return "overview_only"
    return "empty"


def section_content_layout(section: str, block: dict[str, Any] | None) -> str:
    if section == "kcmb":
        return kcmb_content_layout(block)
    data = block if isinstance(block, dict) else {}
    overview_key = OVERVIEW_BY_SECTION.get(section, "")
    has_table = _has_substantive_rows(data.get("tm"))
    has_overview = _is_substantive(data.get(overview_key)) if overview_key else False
    if section == "jxnr" and _is_substantive(data.get("zongxs")):
        has_table = True
    if has_table and has_overview:
        return "table_with_supplement"
    if has_table:
        return "table_only"
    if has_overview:
        return "overview_only"
    return "empty"


def section_has_content(section: str, payload: dict[str, Any]) -> bool:
    return section_content_layout(section, payload.get(section)) != "empty"


def layout_note(layout: str) -> str:
    return LAYOUT_NOTES.get(layout, "")


def build_layout_context(section: str, block: dict[str, Any] | None) -> dict[str, Any]:
    layout = section_content_layout(section, block)
    data = block if isinstance(block, dict) else {}
    ctx: dict[str, Any] = {
        "content_layout": layout,
        "layout_note": layout_note(layout),
    }
    if section in TABLE_SECTIONS:
        rows = data.get("tm") if isinstance(data.get("tm"), list) else []
        ctx["primary"] = {
            "tm": rows,
            "tm_row_count": len(rows),
        }
        if section == "jxnr" and _is_substantive(data.get("zongxs")):
            ctx["primary"]["zongxs"] = data.get("zongxs")
        overview_key = OVERVIEW_BY_SECTION[section]
        ctx["supplement"] = {overview_key: data.get(overview_key) or ""}
    elif section == "kcmb":
        ctx["primary"] = {
            "szmb": data.get("szmb") or "",
            "nlmb": data.get("nlmb") or "",
            "zsmb": data.get("zsmb") or "",
            "kzzd": data.get("kzzd") or [],
        }
        ctx["supplement"] = {"mbgs": data.get("mbgs") or ""}
    return ctx
