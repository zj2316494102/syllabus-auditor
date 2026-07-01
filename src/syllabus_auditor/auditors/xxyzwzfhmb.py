"""维度：信息要素完整、符合模板、是否有中英文简介（xxyzwzfhmb）。"""

from __future__ import annotations

import re
from typing import Any

from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.core.audit import FAIL, PASS, AuditSubject, FieldFinding, SectionFinding
from syllabus_auditor.utils import (
    as_dict,
    as_list,
    dedupe,
    is_empty,
    json_value,
    label_value,
    meta_text_sources,
    remove_section_titles,
    section_snippets,
)

DIMENSION = "xxyzwzfhmb"
DIMENSION_LABEL = "信息要素完整、符合模板、是否有中英文简介"
MBXXYZWZ = "mbxxyzwz"
ZYWJJ = "zywjj"


def _template_config() -> dict[str, Any]:
    audit_config = load_project_config().get("audit", {})
    value = audit_config.get("xxyzwzfhmb_template", {}) if isinstance(audit_config, dict) else {}
    return value if isinstance(value, dict) else {}


def _field_pairs(name: str) -> tuple[tuple[str, str], ...]:
    rows = _template_config().get(name, [])
    if not isinstance(rows, list):
        return ()
    result = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            result.append((str(row[0]), str(row[1])))
    return tuple(result)


NORMAL_BASIC_FIELDS = _field_pairs("normal_basic_fields")
SPECIAL_BASIC_FIELDS = _field_pairs("special_basic_fields")
TOP_LEVEL_FIELDS = _field_pairs("top_level_fields")
COURSE_GOAL_FIELDS = _field_pairs("course_goal_fields")
JXNR_ROW_FIELDS = _field_pairs("jxnr_row_fields")
JXAP_ROW_FIELDS = _field_pairs("jxap_row_fields")
SECTION_HINTS = {
    str(key): tuple(str(item) for item in value)
    for key, value in (_template_config().get("section_hints", {}) or {}).items()
    if isinstance(value, list)
}


def audit_xxyzwzfhmb(subject: AuditSubject) -> tuple[SectionFinding, list[FieldFinding]]:
    payload = subject.payload or {}
    meta = subject.meta or {}
    field_findings: list[FieldFinding] = []

    field_findings.extend(_basic_info_findings(payload, meta))
    field_findings.extend(_top_level_findings(payload, meta))
    field_findings.extend(_course_goal_findings(payload, meta))
    field_findings.extend(_teaching_content_findings(payload, meta))
    field_findings.extend(_teaching_arrangement_findings(payload, meta))
    field_findings.append(_course_requirement_finding(payload, meta))

    failed = [item for item in field_findings if item.status == FAIL]
    reasons = dedupe([item.reason for item in failed if item.reason])
    status = FAIL if failed else PASS
    result = "否" if failed else "是"

    intro_failures = [item for item in field_findings if item.status == FAIL and item.path in {"payload.kczwjj", "payload.kcywjj"}]
    checks = {
        MBXXYZWZ: {"result": result, "reason": "；".join(reasons), "fail_count": len(failed)},
        ZYWJJ: {
            "result": "否" if intro_failures else "是",
            "reason": "；".join(dedupe([item.reason for item in intro_failures])),
            "fail_count": len(intro_failures),
        },
    }
    evidence = {
        "failed_paths": [item.path for item in failed],
        "fallback_paths": [item.path for item in field_findings if item.evidence.get("fallback_used")],
        "checks": checks,
    }

    section = SectionFinding(
        wd=DIMENSION,
        status=status,
        message=result,
        evidence=evidence,
        suggestion="按字段级原因补齐模板字段、章节或表格列。" if failed else "",
        details={"label": DIMENSION_LABEL, "result": result, "reasons": reasons, "checks": checks},
        pdfs="rule",
    )
    summary_fields = [
        _summary_field(MBXXYZWZ, "模板信息要素是否完整", checks[MBXXYZWZ]),
        _summary_field(ZYWJJ, "是否有中英文简介", checks[ZYWJJ]),
    ]
    return section, summary_fields + field_findings


def _basic_info_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    jcxx = as_dict(payload.get("jcxx"))
    findings: list[FieldFinding] = []
    for field_name, label in NORMAL_BASIC_FIELDS:
        path = f"payload.jcxx.{field_name}"
        findings.append(
            _field_presence(
                section="jcxx_template",
                field_name=field_name,
                path=path,
                label=label,
                value=jcxx.get(field_name),
                meta=meta,
                section_key="jcxx",
                labels=(label,),
                require_value=True,
            )
        )
    for field_name, label in SPECIAL_BASIC_FIELDS:
        path = f"payload.jcxx.{field_name}"
        if field_name in jcxx:
            findings.append(
                FieldFinding(
                    section="jcxx_template",
                    field=field_name,
                    path=path,
                    status=PASS,
                    message=f"{label}字段存在，允许为空",
                    actual=json_value(jcxx.get(field_name)),
                )
            )
            continue
        fallback = _find_meta_label(meta, "jcxx", (label,), require_value=False)
        if fallback:
            findings.append(
                FieldFinding(
                    section="jcxx_template",
                    field=field_name,
                    path=path,
                    status=PASS,
                    message=f"{label}字段在原文辅助信息中存在，允许为空",
                    actual="",
                    evidence=fallback,
                )
            )
            continue
        findings.append(
            FieldFinding(
                section="jcxx_template",
                field=field_name,
                path=path,
                status=FAIL,
                reason=f"{label}字段缺失",
                message=f"{label}字段缺失",
                actual="",
                suggestion=f"检查 PDF 课程基本信息中是否包含{label}字段。",
            )
        )
    return findings


def _top_level_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    return [
        _field_presence(
            section="payload",
            field_name=field_name,
            path=f"payload.{field_name}",
            label=label,
            value=payload.get(field_name),
            meta=meta,
            section_key=field_name,
            labels=(label,),
            require_value=True,
        )
        for field_name, label in TOP_LEVEL_FIELDS
    ]


def _course_goal_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    kcmb = as_dict(payload.get("kcmb"))
    return [
        _field_presence(
            section="kcmb",
            field_name=field_name,
            path=f"payload.kcmb.{field_name}",
            label=label,
            value=kcmb.get(field_name),
            meta=meta,
            section_key="kcmb",
            labels=(label,),
            require_value=True,
        )
        for field_name, label in COURSE_GOAL_FIELDS
    ]


def _teaching_content_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    jxnr = as_dict(payload.get("jxnr"))
    findings = [
        _field_presence(
            section="jxnr",
            field_name="zongxs",
            path="payload.jxnr.zongxs",
            label="教学内容总学时",
            value=jxnr.get("zongxs"),
            meta=meta,
            section_key="jxnr",
            labels=("总学时", "合计"),
            require_value=True,
        )
    ]
    rows = as_list(jxnr.get("tm"))
    if not rows:
        fallback = _find_meta_table(meta, "jxnr", tuple(label for _, label in JXNR_ROW_FIELDS), require_rows=True)
        if fallback:
            findings.append(
                FieldFinding(
                    section="jxnr",
                    field="tm",
                    path="payload.jxnr.tm",
                    status=PASS,
                    message="教学内容表在原文辅助信息中存在。",
                    evidence=fallback,
                )
            )
        else:
            findings.append(
                FieldFinding(
                    section="jxnr",
                    field="tm",
                    path="payload.jxnr.tm",
                    status=FAIL,
                    reason="教学内容表为空",
                    message="教学内容表为空",
                    suggestion="补齐教学内容表，至少包含序号、主题、知识点、学时。",
                )
            )
        return findings

    for index, row in enumerate(rows):
        row_dict = as_dict(row)
        for field_name, label in JXNR_ROW_FIELDS:
            findings.append(
                _row_presence(
                    section="jxnr",
                    field_name=field_name,
                    path=f"payload.jxnr.tm[{index}].{field_name}",
                    label=label,
                    value=row_dict.get(field_name),
                    row_index=index,
                )
            )
    return findings


def _teaching_arrangement_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    jxap = as_dict(payload.get("jxap"))
    rows = as_list(jxap.get("tm"))
    findings: list[FieldFinding] = []
    if not rows:
        fallback = _find_meta_table(meta, "jxap", tuple(label for _, label in JXAP_ROW_FIELDS), require_rows=True)
        if fallback:
            findings.append(
                FieldFinding(
                    section="jxap",
                    field="tm",
                    path="payload.jxap.tm",
                    status=PASS,
                    message="教学安排表在原文辅助信息中存在。",
                    evidence=fallback,
                )
            )
        else:
            findings.append(
                FieldFinding(
                    section="jxap",
                    field="tm",
                    path="payload.jxap.tm",
                    status=FAIL,
                    reason="教学安排表为空",
                    message="教学安排表为空",
                    suggestion="补齐教学安排表，至少包含序号、授课内容、授课方式、思政元素的融入和预期教学成效。",
                )
            )
        return findings

    for index, row in enumerate(rows):
        row_dict = as_dict(row)
        for field_name, label in JXAP_ROW_FIELDS:
            findings.append(
                _row_presence(
                    section="jxap",
                    field_name=field_name,
                    path=f"payload.jxap.tm[{index}].{field_name}",
                    label=label,
                    value=row_dict.get(field_name),
                    row_index=index,
                )
            )
    return findings


def _course_requirement_finding(payload: dict[str, Any], meta: dict[str, Any]) -> FieldFinding:
    if not is_empty(payload.get("kcyq")):
        return FieldFinding(
            section="kcyq",
            field="content",
            path="payload.kcyq",
            status=PASS,
            message="课程要求已填写",
            actual={"has_text": True},
        )
    fallback = _find_meta_section_content(meta, "kcyq")
    if fallback:
        return FieldFinding(
            section="kcyq",
            field="content",
            path="payload.kcyq",
            status=PASS,
            message="课程要求在原文辅助信息中存在。",
            evidence=fallback,
        )
    return FieldFinding(
        section="kcyq",
        field="content",
        path="payload.kcyq",
        status=FAIL,
        reason="课程要求为空",
        message="课程要求为空",
        actual="",
        suggestion="补齐课程要求文本。",
    )


def _field_presence(
    *,
    section: str,
    field_name: str,
    path: str,
    label: str,
    value: Any,
    meta: dict[str, Any],
    section_key: str,
    labels: tuple[str, ...],
    require_value: bool,
) -> FieldFinding:
    if not is_empty(value):
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=PASS,
            message=f"{label}已填写",
            actual=json_value(value),
        )
    fallback = _find_meta_label(meta, section_key, labels, require_value=require_value)
    if fallback:
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=PASS,
            message=f"{label}在原文辅助信息中存在",
            actual=json_value(value),
            evidence=fallback,
        )
    title_only = _find_meta_section_title(meta, section_key)
    reason = f"{label}为空"
    if title_only:
        reason = f"{label}为空；原文辅助信息中只有章节标题，没有该字段的填写内容"
    return FieldFinding(
        section=section,
        field=field_name,
        path=path,
        status=FAIL,
        reason=reason,
        message=reason,
        actual=json_value(value),
        evidence=title_only or {},
        suggestion=f"检查 PDF 中{label}是否填写，或调整抽取模板。",
    )


def _row_presence(
    *,
    section: str,
    field_name: str,
    path: str,
    label: str,
    value: Any,
    row_index: int,
) -> FieldFinding:
    if not is_empty(value):
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=PASS,
            message=f"{label}已填写",
            actual=json_value(value),
        )
    reason = f"{section}第 {row_index + 1} 行{label}为空"
    return FieldFinding(
        section=section,
        field=field_name,
        path=path,
        status=FAIL,
        reason=reason,
        message=reason,
        actual=json_value(value),
        suggestion=f"补齐{section}表第 {row_index + 1} 行的{label}。",
    )


def _summary_field(field_name: str, label: str, check: dict[str, Any]) -> FieldFinding:
    is_pass = check["result"] == "是"
    reason = check.get("reason") or ""
    return FieldFinding(
        section=DIMENSION,
        field=field_name,
        path=f"audit_findings.{DIMENSION}.details.checks.{field_name}",
        status=PASS if is_pass else FAIL,
        reason="" if is_pass else reason,
        message=check["result"] if is_pass else reason,
        expected={"requirement": label},
        actual=check,
    )


def _find_meta_label(
    meta: dict[str, Any],
    section_key: str,
    labels: tuple[str, ...],
    *,
    require_value: bool,
) -> dict[str, Any]:
    for source in meta_text_sources(meta):
        for snippet in section_snippets(source["text"], SECTION_HINTS.get(section_key, ())):
            for label in labels:
                value = label_value(snippet["snippet"], label)
                if value is None:
                    continue
                if require_value and not value.strip():
                    continue
                return {
                    "fallback_used": True,
                    "source_path": source["source_path"],
                    "section_hint": snippet["section_hint"],
                    "raw_value": value,
                    "snippet": snippet["snippet"][:500],
                    "reason": "payload_empty_meta_found" if require_value else "payload_key_missing_meta_label_found",
                }
    return {}


def _find_meta_table(
    meta: dict[str, Any],
    section_key: str,
    labels: tuple[str, ...],
    *,
    require_rows: bool,
) -> dict[str, Any]:
    for source in meta_text_sources(meta):
        for snippet in section_snippets(source["text"], SECTION_HINTS.get(section_key, ())):
            text = snippet["snippet"]
            found_labels = [label for label in labels if label in text]
            if len(found_labels) < max(2, min(len(labels), 3)):
                continue
            has_row = bool(re.search(r"\d+\s*[、.．\s]", text)) or any(keyword in text for keyword in ("第", "第一", "主题", "授课"))
            if require_rows and not has_row:
                continue
            return {
                "fallback_used": True,
                "source_path": source["source_path"],
                "section_hint": snippet["section_hint"],
                "snippet": text[:500],
                "found_labels": found_labels,
                "reason": "payload_empty_meta_found",
            }
    return {}


def _find_meta_section_content(meta: dict[str, Any], section_key: str) -> dict[str, Any]:
    for source in meta_text_sources(meta):
        for snippet in section_snippets(source["text"], SECTION_HINTS.get(section_key, ())):
            body = remove_section_titles(snippet["snippet"], SECTION_HINTS.get(section_key, ()))
            if len(body.strip()) < 8:
                continue
            return {
                "fallback_used": True,
                "source_path": source["source_path"],
                "section_hint": snippet["section_hint"],
                "snippet": snippet["snippet"][:500],
                "reason": "payload_empty_meta_found",
            }
    return {}


def _find_meta_section_title(meta: dict[str, Any], section_key: str) -> dict[str, Any]:
    for source in meta_text_sources(meta):
        for hint in SECTION_HINTS.get(section_key, ()):
            if hint in source["text"]:
                return {
                    "fallback_used": False,
                    "source_path": source["source_path"],
                    "section_hint": hint,
                    "snippet": hint,
                    "reason": "meta_title_only",
                }
    return {}

