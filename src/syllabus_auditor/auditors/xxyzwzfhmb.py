from __future__ import annotations

import re
from typing import Any

from syllabus_auditor.core.audit import FAIL, PASS, AuditSubject, FieldFinding, SectionFinding
from config import load_project_config


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
    reasons = _dedupe([item.reason for item in failed if item.reason])
    status = FAIL if failed else PASS
    result = "否" if failed else "是"

    intro_failures = [
        item
        for item in field_findings
        if item.status == FAIL
        and item.path in {"payload.kczwjj", "payload.kcywjj"}
    ]
    checks = {
        MBXXYZWZ: {
            "result": result,
            "reason": "；".join(reasons),
            "fail_count": len(failed),
        },
        ZYWJJ: {
            "result": "否" if intro_failures else "是",
            "reason": "；".join(_dedupe([item.reason for item in intro_failures])), 
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
        details={
            "label": DIMENSION_LABEL,
            "result": result,
            "reasons": reasons,
            "checks": checks,
        },
        pdfs="rule",
    )
    summary_fields = [
        _summary_field(MBXXYZWZ, "模板信息要素是否完整", checks[MBXXYZWZ]),
        _summary_field(ZYWJJ, "是否有中英文简介", checks[ZYWJJ]),
    ]
    return section, summary_fields + field_findings


def _basic_info_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    jcxx = _as_dict(payload.get("jcxx"))
    findings: list[FieldFinding] = []
    for field_name, label in NORMAL_BASIC_FIELDS:
        path = f"payload.jcxx.{field_name}"
        findings.append(
            _field_presence(
                section="jcxx",
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
                    section="jcxx",
                    field=field_name,
                    path=path,
                    status=PASS,
                    message=f"{label}字段存在，允许为空",
                    actual=_json_value(jcxx.get(field_name)),
                )
            )
            continue
        fallback = _find_meta_label(meta, "jcxx", (label,), require_value=False)
        if fallback:
            findings.append(
                FieldFinding(
                    section="jcxx",
                    field=field_name,
                    path=path,
                    status=PASS,
                    message=f"{label}字段在 meta 中存在，允许为空",
                    actual="",
                    evidence=fallback,
                )
            )
            continue
        findings.append(
            FieldFinding(
                section="jcxx",
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
    findings = []
    for field_name, label in TOP_LEVEL_FIELDS:
        findings.append(
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
        )
    return findings


def _course_goal_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    kcmb = _as_dict(payload.get("kcmb"))
    findings = []
    for field_name, label in COURSE_GOAL_FIELDS:
        findings.append(
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
        )
    return findings


def _teaching_content_findings(payload: dict[str, Any], meta: dict[str, Any]) -> list[FieldFinding]:
    jxnr = _as_dict(payload.get("jxnr"))
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
    rows = _as_list(jxnr.get("tm"))
    if not rows:
        fallback = _find_meta_table(meta, "jxnr", tuple(label for _, label in JXNR_ROW_FIELDS), require_rows=True)
        if fallback:
            findings.append(
                FieldFinding(
                    section="jxnr",
                    field="tm",
                    path="payload.jxnr.tm",
                    status=PASS,
                    message="教学内容表在 meta 中存在。",
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
        row_dict = _as_dict(row)
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
    jxap = _as_dict(payload.get("jxap"))
    rows = _as_list(jxap.get("tm"))
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
                    message="教学安排表在 meta 中存在。",
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
        row_dict = _as_dict(row)
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
    kcyqb = _as_dict(payload.get("kcyqb"))
    has_content = not _is_empty(payload.get("kcyq")) or not _is_empty(kcyqb.get("tm")) or not _is_empty(kcyqb.get("yqgs"))
    if has_content:
        return FieldFinding(
            section="kcyq",
            field="content",
            path="payload.kcyq",
            status=PASS,
            message="课程要求已填写",
            actual={
                "has_text": not _is_empty(payload.get("kcyq")),
                "has_table": not _is_empty(kcyqb.get("tm")),
                "has_summary": not _is_empty(kcyqb.get("yqgs")),
            },
        )
    fallback = _find_meta_section_content(meta, "kcyq")
    if fallback:
        return FieldFinding(
            section="kcyq",
            field="content",
            path="payload.kcyq",
            status=PASS,
            message="课程要求在 meta 中存在。",
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
        suggestion="补齐课程要求文本或结构化课程要求表。",
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
    if not _is_empty(value):
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=PASS,
            message=f"{label}已填写",
            actual=_json_value(value),
        )
    fallback = _find_meta_label(meta, section_key, labels, require_value=require_value)
    if fallback:
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=PASS,
            message=f"{label}在 meta 中存在",
            actual=_json_value(value),
            evidence=fallback,
        )
    title_only = _find_meta_section_title(meta, section_key)
    evidence = title_only or {}
    reason = f"{label}为空"
    if title_only:
        reason = f"{label}为空，meta 中仅发现章节标题，未发现有效内容，需人工复核"
    return FieldFinding(
        section=section,
        field=field_name,
        path=path,
        status=FAIL,
        reason=reason,
        message=reason,
        actual=_json_value(value),
        evidence=evidence,
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
    if not _is_empty(value):
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=PASS,
            message=f"{label}已填写",
            actual=_json_value(value),
        )
    reason = f"{section}第 {row_index + 1} 行{label}为空"
    return FieldFinding(
        section=section,
        field=field_name,
        path=path,
        status=FAIL,
        reason=reason,
        message=reason,
        actual=_json_value(value),
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
    for source in _meta_text_sources(meta):
        for snippet in _section_snippets(source["text"], SECTION_HINTS.get(section_key, ())):
            for label in labels:
                value = _label_value(snippet["snippet"], label)
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
    for source in _meta_text_sources(meta):
        for snippet in _section_snippets(source["text"], SECTION_HINTS.get(section_key, ())):
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
    for source in _meta_text_sources(meta):
        for snippet in _section_snippets(source["text"], SECTION_HINTS.get(section_key, ())):
            body = _remove_section_titles(snippet["snippet"], SECTION_HINTS.get(section_key, ()))
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
    for source in _meta_text_sources(meta):
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


def _section_snippets(text: str, hints: tuple[str, ...], *, window: int = 800) -> list[dict[str, str]]:
    result = []
    for hint in hints:
        for match in re.finditer(re.escape(hint), text):
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + window)
            result.append({"section_hint": hint, "snippet": text[start:end]})
    return result


def _label_value(snippet: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s*[:：]?\s*([^\n\r；。]*)"
    match = re.search(pattern, snippet)
    if not match:
        return None
    return match.group(1).strip()


def _remove_section_titles(text: str, hints: tuple[str, ...]) -> str:
    result = text
    for hint in hints:
        result = result.replace(hint, "")
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_value(value: Any) -> Any:
    return "" if value is None else value


def _exact_value(value: Any) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()


