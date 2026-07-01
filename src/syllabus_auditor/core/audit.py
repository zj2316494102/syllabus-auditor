"""审核领域模型与规则引擎：课程库比对、学时/周次匹配、必填项检查等。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import PurePath
from typing import Any

from syllabus_auditor.core.audit_labels import audit_wd_label
from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.shared.reason_text import clean_customer_reason, clean_customer_reasons


PASS = "pass"
FAIL = "fail"
WARNING = "warning"
ERROR = "error"
SKIPPED = "skipped"

KCJBXX_WD = "kcjbxxsfykckyz"
KCJBXX_LABEL = "\u8bfe\u7a0b\u57fa\u672c\u4fe1\u606f\u662f\u5426\u4e0e\u8bfe\u7a0b\u5e93\u4e00\u81f4"
JXNRXS_WD = "jxnrsfyxspp"
JXAPZC_WD = "jxapsfyzcpp"
JXAPZC_LABEL = "\u6559\u5b66\u5b89\u6392\u662f\u5426\u4e0e\u5468\u6b21\u5339\u914d"
JXNRXS_LABEL = "\u6559\u5b66\u5185\u5bb9\u662f\u5426\u4e0e\u5b66\u65f6\u5339\u914d"
YES = "\u662f"
NO = "\u5426"
NON_PASS_STATUSES = {FAIL, WARNING, ERROR, "manual_review"}
MAX_SEMESTER_WEEK = 19


@dataclass(slots=True)
class FieldFinding:
    section: str
    field: str
    path: str
    status: str
    reason: str = ""
    message: str = ""
    expected: Any = field(default_factory=dict)
    actual: Any = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""
    llm_trace: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SectionFinding:
    wd: str
    status: str
    message: str
    evidence: dict[str, Any]
    suggestion: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    pdfs: str = "rule"
    llm_trace: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CourseMatch:
    status: str
    method: str
    query: str = ""
    course_row: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuditSubject:
    extraction_id: int
    course_code: str
    source_path: str
    payload: dict[str, Any]
    meta: dict[str, Any]
    extraction_status: str | None = None
    subject_key: str = ""


@dataclass(slots=True)
class SubjectAudit:
    subject: AuditSubject
    overall_status: str
    summary: dict[str, Any]
    field_findings: list[FieldFinding]
    section_findings: list[SectionFinding]
    fail_count: int
    warning_count: int


@dataclass(slots=True)
class AuditRunSummary:
    run_id: int
    total: int
    pass_count: int
    fail_count: int
    partial_count: int
    error_count: int
    skipped_count: int = 0
    llm_empty_count: int = 0
    llm_parse_error_count: int = 0
    llm_no_llm_count: int = 0


def refresh_subject_audit(audit: SubjectAudit) -> SubjectAudit:
    audit.fail_count = sum(1 for item in audit.field_findings if item.status in {FAIL, ERROR, "manual_review"})
    audit.warning_count = sum(1 for item in audit.field_findings if item.status == WARNING)
    audit.summary["fail_count"] = audit.fail_count
    audit.summary["warning_count"] = audit.warning_count
    audit.summary["sections"] = {item.wd: item.status for item in audit.section_findings}
    audit.summary["messages"] = [
        item.message
        for item in audit.field_findings
        if item.status in {FAIL, ERROR, "manual_review"}
    ][:5]
    audit.summary["main_reasons"] = [
        item.reason
        for item in audit.field_findings
        if item.status in {FAIL, ERROR, "manual_review", WARNING} and item.reason
    ][:20]
    if audit.subject.extraction_status == "failed":
        audit.overall_status = "error"
    elif audit.fail_count:
        audit.overall_status = "fail"
    elif audit.warning_count or audit.subject.extraction_status == "partial":
        audit.overall_status = "partial"
    else:
        audit.overall_status = "pass"
    return audit


@lru_cache(maxsize=1)
def _audit_rules() -> dict[str, Any]:
    audit = load_project_config().get("audit", {})
    rules = audit.get("rules") if isinstance(audit, dict) else {}
    return rules if isinstance(rules, dict) else {}


def _tuple_rows(key: str) -> tuple[tuple[str, ...], ...]:
    rows = _audit_rules().get(key) or []
    return tuple(tuple(str(cell) for cell in row) for row in rows if isinstance(row, (list, tuple)))


def _string_set(key: str) -> set[str]:
    values = _audit_rules().get(key) or []
    return {str(item) for item in values}


def _string_dict(key: str) -> dict[str, str]:
    value = _audit_rules().get(key) or {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _nested_dict(key: str) -> dict[str, dict[str, str]]:
    value = _audit_rules().get(key) or {}
    if not isinstance(value, dict):
        return {}
    return {str(section): {str(k): str(v) for k, v in fields.items()} for section, fields in value.items() if isinstance(fields, dict)}


def _pattern_list(key: str) -> tuple[str, ...]:
    values = _audit_rules().get(key) or []
    return tuple(str(item) for item in values)


def build_subject_key(*, extraction_id: int, course_code: str, source_path: str) -> str:
    if extraction_id:
        return f"extraction:{extraction_id}"
    digest = hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:16]
    return f"source:{digest}"


def build_run_name(prefix: str = "audit") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def extract_course_name_from_source_path(source_path: str) -> str:
    name = PurePath(str(source_path).replace("\\", "/")).name
    stem = re.sub(r"\.[Pp][Dd][Ff]$", "", name).strip()
    stem = re.sub(r"^[\s\d._-]+", "", stem)
    stem = re.sub(r"[（(][^）)]*[）)]", "", stem)
    stem = re.sub(r"【[^】]*】", "", stem)
    for pattern in _pattern_list("filename_noise_patterns"):
        stem = re.sub(pattern, "", stem)
    stem = re.sub(r"\s+", "", stem)
    stem = stem.strip("_-— ")
    return stem


def audit_subject(subject: AuditSubject, course_match: CourseMatch | dict[str, Any] | None = None) -> SubjectAudit:
    if not subject.subject_key:
        subject.subject_key = build_subject_key(
            extraction_id=subject.extraction_id,
            course_code=subject.course_code,
            source_path=subject.source_path,
        )

    match = _coerce_course_match(course_match)
    findings: list[FieldFinding] = []
    kcjbxx_fields, kcjbxx_section = _audit_basic_info(subject, match)
    jxnrxs_field, jxnrxs_section = _audit_teaching_content_hours(subject.payload, subject.meta)
    jxapzc_field, jxapzc_section = _audit_schedule_weeks(subject.payload, subject.meta)
    findings.extend(kcjbxx_fields)
    findings.append(jxnrxs_field)
    findings.append(jxapzc_field)
    findings.extend(_required_payload_findings(subject.payload))
    findings.extend(_extraction_warning_findings(subject.meta, existing_findings=findings))
    findings.extend(_hour_consistency_findings(subject.payload))
    findings.extend(_extraction_status_finding(subject.extraction_status))

    section_findings = [kcjbxx_section, jxnrxs_section, jxapzc_section]
    fail_count = sum(1 for item in findings if item.status in {FAIL, ERROR, "manual_review"})
    warning_count = sum(1 for item in findings if item.status == WARNING)
    overall_status = _overall_status(fail_count, warning_count, subject.extraction_status)
    summary = _summary(findings, section_findings, match, subject)
    return SubjectAudit(
        subject=subject,
        overall_status=overall_status,
        summary=summary,
        field_findings=findings,
        section_findings=section_findings,
        fail_count=fail_count,
        warning_count=warning_count,
    )


def _audit_basic_info(subject: AuditSubject, match: CourseMatch) -> tuple[list[FieldFinding], SectionFinding]:
    jcxx = _as_dict(subject.payload.get("jcxx"))
    course_row = match.course_row or {}
    findings: list[FieldFinding] = []
    dimension_reasons = list(match.reasons)

    if match.status != "matched":
        reason = _match_failure_reason(match)
        findings.append(
            FieldFinding(
                section="jcxx",
                field="course_match",
                path="courses",
                status=FAIL,
                reason=reason,
                message=reason,
                expected={"match_status": match.status},
                actual={"query": match.query, "source_path": subject.source_path},
                evidence=_course_match_evidence(match, subject),
                suggestion="\u8bf7\u4eba\u5de5\u6838\u5bf9 PDF \u6587\u4ef6\u540d\u3001\u8bfe\u7a0b\u7f16\u53f7\u3001\u8bfe\u7a0b\u540d\u79f0\u4e0e\u8bfe\u7a0b\u5e93\u8bb0\u5f55\u3002",
            )
        )
        dimension_reasons.append(reason)
    else:
        dimension_reasons.append(_match_success_message(match))

    for pdf_field, course_field, label in _tuple_rows("basic_comparison_fields"):
        pdf_value = _exact_value(jcxx.get(pdf_field))
        course_value = _exact_value(course_row.get(course_field))
        finding = _exact_match_finding(
            pdf_field=pdf_field,
            course_field=course_field,
            label=label,
            pdf_value=pdf_value,
            course_value=course_value,
            has_course=match.status == "matched",
        )
        findings.append(finding)
        if finding.status != PASS:
            dimension_reasons.append(finding.reason or finding.message)

    hours_formula_finding = _basic_hours_formula_finding(jcxx)
    if hours_formula_finding:
        findings.append(hours_formula_finding)
        if hours_formula_finding.status != PASS:
            dimension_reasons.append(hours_formula_finding.reason or hours_formula_finding.message)

    for pdf_field, label in _tuple_rows("independent_required_jcxx_fields"):
        value = _exact_value(jcxx.get(pdf_field))
        if value:
            findings.append(
                FieldFinding(
                    section="jcxx",
                    field=pdf_field,
                    path=f"payload.jcxx.{pdf_field}",
                    status=PASS,
                    message=f"{label}\u5df2\u586b\u5199\u3002",
                    actual=value,
                )
            )
        else:
            message = f"{label}\u4e3a\u7a7a"
            findings.append(
                FieldFinding(
                    section="jcxx",
                    field=pdf_field,
                    path=f"payload.jcxx.{pdf_field}",
                    status=FAIL,
                    reason=message,
                    message=message,
                    actual="",
                    suggestion=f"\u8bf7\u8865\u5145 PDF \u4e2d\u7684{label}\u3002",
                )
            )
            dimension_reasons.append(message)

    failed = [item for item in findings if item.status in {FAIL, ERROR}]
    status = FAIL if failed else PASS
    result = NO if failed else YES
    all_reasons = _dimension_reasons(dimension_reasons, failed) if failed else []
    details = {
        "label": KCJBXX_LABEL,
        "result": result,
        "reasons": all_reasons,
        "course_match": _course_match_summary(match, subject),
    }
    evidence = {
        "failed_fields": [
            {"field": item.field, "path": item.path, "reason": item.reason, "message": item.message}
            for item in failed
        ],
        "course_match": details["course_match"],
    }
    return findings, SectionFinding(
        wd=KCJBXX_WD,
        status=status,
        message=result,
        evidence=evidence,
        suggestion="\u67e5\u770b audit_field_findings \u4e2d section='jcxx' \u7684\u5b57\u6bb5\u539f\u56e0\u3002" if failed else "",
        details=details,
    )


def _exact_match_finding(
    *,
    pdf_field: str,
    course_field: str,
    label: str,
    pdf_value: str,
    course_value: str,
    has_course: bool,
) -> FieldFinding:
    path = f"payload.jcxx.{pdf_field}"
    evidence: dict[str, Any] = {"course_field": course_field}
    if not has_course:
        message = f"无法定位课程库记录，不能判断{label}是否一致"
        return FieldFinding(section="jcxx", field=pdf_field, path=path, status=FAIL, reason=message, message=message, expected="", actual=pdf_value, evidence=evidence, suggestion="先确认该 PDF 对应的课程库记录。")
    if not pdf_value and not course_value:
        message = f"PDF 和课程库中的{label}都为空"
    elif not pdf_value:
        message = f"{label}为空"
    elif not course_value:
        message = f"课程库中{label}为空"
    elif pdf_field in _string_set("numeric_basic_fields") and _numeric_values_equal(pdf_value, course_value):
        return FieldFinding(section="jcxx", field=pdf_field, path=path, status=PASS, message=f"{label}与课程库一致。", expected=course_value, actual=pdf_value, evidence=evidence)
    elif pdf_field in _string_set("course_name_fields") and _course_name_values_equal(pdf_field, pdf_value, course_value):
        evidence = {
            **evidence,
            "comparison": "normalized_course_name",
            "normalized_pdf": _normalize_course_name(pdf_field, pdf_value),
            "normalized_course": _normalize_course_name(pdf_field, course_value),
        }
        return FieldFinding(section="jcxx", field=pdf_field, path=path, status=PASS, message=f"{label}与课程库一致。", expected=course_value, actual=pdf_value, evidence=evidence)
    elif pdf_value != course_value:
        message = f"{label}与课程库不一致：课程库为 {course_value}，PDF 为 {pdf_value}"
    else:
        return FieldFinding(section="jcxx", field=pdf_field, path=path, status=PASS, message=f"{label}与课程库一致。", expected=course_value, actual=pdf_value, evidence=evidence)

    if pdf_field in _string_set("course_name_fields"):
        evidence = {
            **evidence,
            "comparison": "normalized_course_name",
            "normalized_pdf": _normalize_course_name(pdf_field, pdf_value),
            "normalized_course": _normalize_course_name(pdf_field, course_value),
        }
    return FieldFinding(section="jcxx", field=pdf_field, path=path, status=FAIL, reason=message, message=message, expected=course_value, actual=pdf_value, evidence=evidence, suggestion=f"请核对 PDF 和课程库中的{label}。")


def _course_name_values_equal(field_name: str, left: str, right: str) -> bool:
    left_value = _normalize_course_name(field_name, left)
    right_value = _normalize_course_name(field_name, right)
    return bool(left_value) and left_value == right_value


def _normalize_course_name(field_name: str, value: Any) -> str:
    text = unicodedata.normalize("NFKC", _exact_value(value))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = text.strip().strip("《》<> ")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("［", "[").replace("］", "]")
    text = text.replace("【", "[").replace("】", "]")
    text = text.replace("，", ",").replace("、", ",")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*([,;:()\[\]/&+\-])\s*", r"\1", text)
    if field_name == "ywkcmc":
        text = text.casefold()
    return text
def _numeric_values_equal(left: str, right: str) -> bool:
    left_number = _number_value(left)
    right_number = _number_value(right)
    return left_number is not None and right_number is not None and left_number == right_number


def _basic_hours_formula_finding(jcxx: dict[str, Any]) -> FieldFinding | None:
    zxs_text = _exact_value(jcxx.get("zxs"))
    skzs_text = _exact_value(jcxx.get("skzs"))
    zongxs_text = _exact_value(jcxx.get("zongxs"))
    if not zxs_text or not skzs_text or not zongxs_text:
        return None

    zxs = _number_value(zxs_text)
    skzs = _number_value(skzs_text)
    zongxs = _number_value(zongxs_text)
    if zxs is None or skzs is None or zongxs is None:
        message = f"\u603b\u5b66\u65f6\u3001\u5468\u5b66\u65f6\u6216\u4e0a\u8bfe\u5468\u6570\u4e0d\u662f\u53ef\u8ba1\u7b97\u6570\u5b57\uff1a\u603b\u5b66\u65f6\u4e3a {zongxs_text}\uff0c\u5468\u5b66\u65f6\u4e3a {zxs_text}\uff0c\u4e0a\u8bfe\u5468\u6570\u4e3a {skzs_text}"
        return FieldFinding(section="jcxx", field="zongxs", path="payload.jcxx.zongxs", status=FAIL, reason=message, message=message, expected={"formula": "\u603b\u5b66\u65f6 = \u5468\u5b66\u65f6 \u00d7 \u4e0a\u8bfe\u5468\u6570"}, actual={"zongxs": zongxs_text, "zxs": zxs_text, "skzs": skzs_text}, suggestion="\u8bf7\u6838\u5bf9 PDF \u4e2d\u603b\u5b66\u65f6\u3001\u5468\u5b66\u65f6\u548c\u4e0a\u8bfe\u5468\u6570\u7684\u586b\u5199\u3002")

    expected = zxs * skzs
    if expected == zongxs:
        return FieldFinding(section="jcxx", field="zongxs", path="payload.jcxx.zongxs", status=PASS, message="\u603b\u5b66\u65f6\u7b49\u4e8e\u5468\u5b66\u65f6\u4e58\u4ee5\u4e0a\u8bfe\u5468\u6570\u3002", expected=expected, actual=zongxs, evidence={"formula": "zongxs = zxs * skzs", "zxs": zxs, "skzs": skzs})

    message = f"\u603b\u5b66\u65f6\u4e0d\u7b49\u4e8e\u5468\u5b66\u65f6\u4e58\u4ee5\u4e0a\u8bfe\u5468\u6570\uff1a\u603b\u5b66\u65f6\u4e3a {zongxs_text}\uff0c\u5468\u5b66\u65f6 {zxs_text} \u00d7 \u4e0a\u8bfe\u5468\u6570 {skzs_text} = {_format_number(expected)}"
    return FieldFinding(section="jcxx", field="zongxs", path="payload.jcxx.zongxs", status=FAIL, reason=message, message=message, expected=_format_number(expected), actual=zongxs_text, evidence={"formula": "zongxs = zxs * skzs", "zxs": zxs_text, "skzs": skzs_text}, suggestion="\u8bf7\u6838\u5bf9 PDF \u4e2d\u603b\u5b66\u65f6\u3001\u5468\u5b66\u65f6\u548c\u4e0a\u8bfe\u5468\u6570\u662f\u5426\u4e00\u81f4\u3002")


def _required_payload_findings(payload: dict[str, Any]) -> list[FieldFinding]:
    findings: list[FieldFinding] = []
    for field_name, label in _string_dict("top_level_required").items():
        findings.append(_presence_finding("payload", field_name, f"payload.{field_name}", label, payload.get(field_name)))

    for section, fields in _nested_dict("section_required").items():
        block = _as_dict(payload.get(section))
        for field_name, label in fields.items():
            findings.append(
                _presence_finding(section, field_name, f"payload.{section}.{field_name}", label, block.get(field_name))
            )

    _append_kcyq_findings(payload, findings)
    _append_row_findings(payload, findings)
    return findings


def _append_kcyq_findings(payload: dict[str, Any], findings: list[FieldFinding]) -> None:
    has_text = not _is_empty(payload.get("kcyq"))
    if has_text:
        findings.append(
            FieldFinding(
                section="kcyq",
                field="content",
                path="payload.kcyq",
                status=PASS,
                message="课程要求已填写。",
                actual={"has_text": has_text},
            )
        )
    else:
        findings.append(
            FieldFinding(
                section="kcyq",
                field="content",
                path="payload.kcyq",
                status=FAIL,
                reason="课程要求为空",
                message="课程要求为空，未抽取到文本。",
                actual="",
                suggestion="补充课程要求，或检查 PDF 模板中课程要求章节是否可识别。",
            )
        )


def _append_row_findings(payload: dict[str, Any], findings: list[FieldFinding]) -> None:
    for section, fields in _nested_dict("row_required").items():
        rows = _as_list(_as_dict(payload.get(section)).get("tm"))
        for index, row in enumerate(rows):
            row_dict = _as_dict(row)
            for field_name, label in fields.items():
                path = f"payload.{section}.tm[{index}].{field_name}"
                findings.append(_presence_finding(section, field_name, path, label, row_dict.get(field_name)))


def _presence_finding(section: str, field_name: str, path: str, label: str, value: Any) -> FieldFinding:
    if _is_empty(value):
        message = f"{label}为空"
        return FieldFinding(
            section=section,
            field=field_name,
            path=path,
            status=FAIL,
            reason=message,
            message=message,
            actual=_json_value(value),
            suggestion=f"检查 PDF 中{label}是否填写，或调整抽取模板。",
        )
    return FieldFinding(
        section=section,
        field=field_name,
        path=path,
        status=PASS,
        message=f"{label}已填写。",
        actual=_json_value(value),
    )


def _extraction_warning_findings(
    meta: dict[str, Any],
    *,
    existing_findings: list[FieldFinding] | None = None,
) -> list[FieldFinding]:
    findings: list[FieldFinding] = []
    duplicate_keys = _duplicate_warning_keys(existing_findings or [])
    for index, warning in enumerate(_as_list(meta.get("extraction_warnings"))):
        warning_dict = _as_dict(warning)
        section = _text(warning_dict.get("section")) or "system"
        field_name = _text(warning_dict.get("field")) or "warning"
        raw_reason = _text(warning_dict.get("reason")) or "extraction_warning"
        path = _text(warning_dict.get("path")) or f"meta.extraction_warnings[{index}]"
        if raw_reason in {"missing_field", "empty_section"} and _is_duplicate_extraction_warning(
            path=path,
            section=section,
            field_name=field_name,
            duplicate_keys=duplicate_keys,
        ):
            continue
        label = _text(warning_dict.get("label")) or field_name
        status = FAIL if raw_reason in {"missing_field", "empty_section"} else WARNING
        detail = _text(warning_dict.get("detail"))
        message = detail or f"{label}存在抽取问题：{_warning_reason_cn(raw_reason)}。"
        findings.append(
            FieldFinding(
                section=section,
                field=field_name,
                path=path,
                status=status,
                reason=message,
                message=message,
                actual=warning_dict,
                evidence={"source": "meta.extraction_warnings", "index": index, "raw_reason": raw_reason},
                suggestion="复核 PDF 原文和抽取结果。",
            )
        )
    return findings


def _duplicate_warning_keys(findings: list[FieldFinding]) -> dict[str, set[tuple[str, str] | str]]:
    keys: dict[str, set[tuple[str, str] | str]] = {"paths": set(), "section_fields": set()}
    for finding in findings:
        if finding.status not in {FAIL, ERROR, "manual_review"}:
            continue
        if finding.path:
            keys["paths"].add(finding.path)
        keys["section_fields"].add((finding.section, finding.field))
    return keys


def _is_duplicate_extraction_warning(
    *,
    path: str,
    section: str,
    field_name: str,
    duplicate_keys: dict[str, set[tuple[str, str] | str]],
) -> bool:
    if path in duplicate_keys["paths"]:
        return True
    return (section, field_name) in duplicate_keys["section_fields"]


def _hour_consistency_findings(payload: dict[str, Any]) -> list[FieldFinding]:
    findings: list[FieldFinding] = []
    jcxx_total = _first_number(_as_dict(payload.get("jcxx")).get("zongxs"))
    jxnr = _as_dict(payload.get("jxnr"))
    jxnr_total = _first_number(jxnr.get("zongxs"))
    row_total = 0
    row_found = False
    for row in _as_list(jxnr.get("tm")):
        number = _first_number(_as_dict(row).get("xs"))
        if number is not None:
            row_total += number
            row_found = True

    if jcxx_total is not None and jxnr_total is not None and jcxx_total != jxnr_total:
        message = f"教学内容总学时与基础信息不一致：基础信息为 {jcxx_total}，教学内容为 {jxnr_total}"
        findings.append(
            FieldFinding(
                section="jxnr",
                field="zongxs",
                path="payload.jxnr.zongxs",
                status=FAIL,
                reason=message,
                message=message,
                expected=jcxx_total,
                actual=jxnr_total,
                suggestion="核对课程总学时和教学内容章节的课时总计。",
            )
        )

    if jxnr_total is not None and row_found and row_total != jxnr_total:
        message = f"教学内容条目学时合计与总学时不一致：条目合计为 {row_total}，总学时为 {jxnr_total}"
        findings.append(
            FieldFinding(
                section="jxnr",
                field="tm.xs",
                path="payload.jxnr.tm[].xs",
                status=FAIL,
                reason=message,
                message=message,
                expected=jxnr_total,
                actual=row_total,
                suggestion="检查教学内容表是否有跨页漏录、合计行错位或学时填写错误。",
            )
        )
    return findings


def _extraction_status_finding(extraction_status: str | None) -> list[FieldFinding]:
    if extraction_status in {None, "", "success"}:
        return []
    status = WARNING if extraction_status == "partial" else ERROR
    message = f"PDF 抽取状态为 {extraction_status}"
    return [
        FieldFinding(
            section="system",
            field="extraction_status",
            path="syllabus_extractions.extraction_status",
            status=status,
            reason=message,
            message=message,
            actual=extraction_status,
            suggestion="查看 meta.extraction_warnings 获取具体抽取问题。",
        )
    ]


def _build_section_findings(field_findings: list[FieldFinding]) -> list[SectionFinding]:
    sections = ["kcmb", "jxnr", "jxap", "kcyq", "khfsb", "payload", "system"]
    result: list[SectionFinding] = []
    for section in sections:
        items = [item for item in field_findings if item.section == section]
        if not items:
            continue
        fail_count = sum(1 for item in items if item.status in {FAIL, ERROR, "manual_review"})
        warning_count = sum(1 for item in items if item.status == WARNING)
        section_label = audit_wd_label(section)
        if fail_count:
            status = FAIL
            message = f"{section_label}有 {fail_count} 个不通过字段。"
        elif warning_count:
            status = WARNING
            message = f"{section_label}有 {warning_count} 个警告字段。"
        else:
            status = PASS
            message = f"{section_label}通过。"
        result.append(
            SectionFinding(
                wd=section,
                status=status,
                message=message,
                evidence={"failed_paths": [item.path for item in items if item.status in NON_PASS_STATUSES][:20]},
                suggestion="查看 audit_field_findings 获取字段级原因。" if status != PASS else "",
                details={
                    "fail_count": fail_count,
                    "warning_count": warning_count,
                    "reasons": _dedupe([item.reason for item in items if item.status in NON_PASS_STATUSES and item.reason]),
                },
            )
        )
    return result


def _overall_status(fail_count: int, warning_count: int, extraction_status: str | None) -> str:
    if extraction_status == "failed":
        return "error"
    if fail_count:
        return "fail"
    if warning_count or extraction_status == "partial":
        return "partial"
    return "pass"


def _summary(
    field_findings: list[FieldFinding],
    section_findings: list[SectionFinding],
    match: CourseMatch,
    subject: AuditSubject,
) -> dict[str, Any]:
    failed = [item for item in field_findings if item.status in {FAIL, ERROR, "manual_review"}]
    warnings = [item for item in field_findings if item.status == WARNING]
    return {
        "fail_count": len(failed),
        "warning_count": len(warnings),
        "main_reasons": _dedupe([item.reason for item in failed + warnings if item.reason])[:20],
        "messages": [item.message for item in failed[:5]],
        "sections": {item.wd: item.status for item in section_findings},
        "course_match": _course_match_summary(match, subject),
    }


def _coerce_course_match(value: CourseMatch | dict[str, Any] | None) -> CourseMatch:
    if isinstance(value, CourseMatch):
        return value
    if isinstance(value, dict):
        return CourseMatch(status="matched", method="matched_by_kcbh", course_row=value)
    return CourseMatch(status="not_found", method="not_found", reasons=["无法定位课程库记录"])


def _course_match_summary(match: CourseMatch, subject: AuditSubject | None) -> dict[str, Any]:
    row = match.course_row or {}
    summary = {
        "status": match.status,
        "method": match.method,
        "query": match.query,
        "matched_kcbh": _exact_value(row.get("kcbh")),
        "matched_zwkcmc": _exact_value(row.get("zwkcmc")),
        "source_path": subject.source_path if subject else "",
        "candidate_count": len(match.candidates),
    }
    if subject:
        jcxx = _as_dict(subject.payload.get("jcxx"))
        summary["original_kcbh"] = _exact_value(jcxx.get("kcbh") or subject.course_code)
    summary.update(match.metadata)
    return summary

def _course_match_evidence(match: CourseMatch, subject: AuditSubject) -> dict[str, Any]:
    return {
        "course_match": _course_match_summary(match, subject),
        "candidates": [
            {"kcbh": item.get("kcbh"), "zwkcmc": item.get("zwkcmc"), "kkyx": item.get("kkyx")}
            for item in match.candidates[:10]
        ],
    }


def _match_success_message(match: CourseMatch) -> str:
    row = match.course_row or {}
    name = _exact_value(row.get("zwkcmc")) or _exact_value(row.get("kcbh"))
    if match.method == "matched_by_pdf_name_for_duplicate_kcbh":
        return f"本轮审核中存在多个 PDF 填写同一课程编号，已根据 PDF 中的课程名称定位审核对照课程：{name}"
    if match.method == "matched_by_source_path_for_duplicate_kcbh":
        return f"本轮审核中存在多个 PDF 填写同一课程编号，已根据文件名定位审核对照课程：{name}"
    if match.method == "matched_by_kcbh_after_duplicate_unresolved":
        return f"本轮审核中存在多个 PDF 填写同一课程编号，未能通过课程名称或文件名唯一定位其它课程，已按原课程编号定位审核对照课程：{name}"
    if match.method == "matched_by_source_path":
        return f"通过文件路径匹配到课程库课程：{name}"
    if match.method == "matched_by_pdf_name":
        return f"通过 PDF 中的课程名称匹配到课程库课程：{name}"
    return f"通过课程编号匹配到课程库课程：{name}"


def _match_failure_reason(match: CourseMatch) -> str:
    if match.status == "ambiguous":
        return "文件路径或课程名称匹配到多条课程库记录，需人工复核"
    return "无法定位课程库记录"


def _warning_reason_cn(reason: str) -> str:
    mapping = {
        "missing_field": "字段为空",
        "empty_section": "章节为空",
        "sanitized_control_chars": "已清理非法控制字符",
        "unknown_columns": "存在未知列",
        "fallback_used": "使用了兜底抽取",
    }
    return mapping.get(reason, reason)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dimension_reasons(existing: list[str], failed: list[FieldFinding]) -> list[str]:
    reasons = list(existing)
    for item in failed:
        reasons.append(item.reason or item.message)
    return _dedupe([reason for reason in reasons if reason])


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


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def _exact_value(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


def _first_number(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    return int(match.group(0))


def _number_value(value: Any) -> float | None:
    text = _exact_value(value)
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    return float(text)


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _audit_teaching_content_hours(payload: dict[str, Any], meta: dict[str, Any]) -> tuple[FieldFinding, SectionFinding]:
    jcxx_total = _resolve_semantic_number(payload_value=_as_dict(payload.get("jcxx")).get("zongxs"), payload_path="payload.jcxx.zongxs", semantic_field="jcxx.zongxs", meta=meta, section_hints=("\u8bfe\u7a0b\u57fa\u672c\u4fe1\u606f", "\u57fa\u672c\u4fe1\u606f", "\u8bfe\u7a0b\u4fe1\u606f"), value_keywords=("\u603b\u5b66\u65f6", "\u8bfe\u7a0b\u603b\u5b66\u65f6"))
    jxnr_total = _resolve_semantic_number(payload_value=_as_dict(payload.get("jxnr")).get("zongxs"), payload_path="payload.jxnr.zongxs", semantic_field="jxnr.zongxs", meta=meta, section_hints=("\u6559\u5b66\u5185\u5bb9", "\u8bfe\u7a0b\u5185\u5bb9"), value_keywords=("\u603b\u5b66\u65f6", "\u5408\u8ba1", "\u5408\u8ba1\u5b66\u65f6", "\u5c0f\u8ba1"))
    evidence = {"jcxx_zongxs": jcxx_total, "jxnr_zongxs": jxnr_total, "fallback_used": jcxx_total.get("source") == "meta" or jxnr_total.get("source") == "meta"}

    reasons: list[str] = []
    reasons.extend(_semantic_number_issue_reasons(jcxx_total, jxnr_total))

    jcxx_number = jcxx_total.get("number")
    jxnr_number = jxnr_total.get("number")
    if not reasons and jcxx_number != jxnr_number:
        reasons.append(f"\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6\u4e0e\u57fa\u7840\u4fe1\u606f\u603b\u5b66\u65f6\u4e0d\u4e00\u81f4\uff1a\u57fa\u7840\u4fe1\u606f\u4e3a {jcxx_number}\uff0c\u6559\u5b66\u5185\u5bb9\u4e3a {jxnr_number}")

    reasons = _dedupe(reasons)
    if reasons:
        reason = "\uff1b".join(reasons)
        return FieldFinding(section="jxnr", field="zongxs", path="payload.jxnr.zongxs", status=FAIL, reason=reason, message=reason, expected=jcxx_total, actual=jxnr_total, evidence=evidence, suggestion="\u8bf7\u6838\u5bf9\u57fa\u7840\u4fe1\u606f\u548c\u6559\u5b66\u5185\u5bb9\u4e2d\u7684\u603b\u5b66\u65f6\u586b\u5199\u662f\u5426\u4e00\u81f4\u3002"), SectionFinding(wd=JXNRXS_WD, status=FAIL, message=NO, evidence=evidence, suggestion="\u67e5\u770b audit_field_findings \u4e2d section='jxnr'\u3001field='zongxs' \u7684\u5b57\u6bb5\u539f\u56e0\u3002", details={"label": JXNRXS_LABEL, "result": NO, "reasons": reasons})

    message = "\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6\u4e0e\u57fa\u7840\u4fe1\u606f\u603b\u5b66\u65f6\u4e00\u81f4\u3002"
    return FieldFinding(section="jxnr", field="zongxs", path="payload.jxnr.zongxs", status=PASS, message=message, expected=jcxx_total, actual=jxnr_total, evidence=evidence), SectionFinding(wd=JXNRXS_WD, status=PASS, message=YES, evidence=evidence, details={"label": JXNRXS_LABEL, "result": YES, "reasons": []})


def _semantic_number_issue_reasons(jcxx_total: dict[str, Any], jxnr_total: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if jcxx_total.get("ambiguous"):
        reasons.append(_ambiguous_total_reason("基础信息总学时", jcxx_total))
    if jxnr_total.get("ambiguous"):
        reasons.append(_ambiguous_total_reason("教学内容总学时", jxnr_total))
    if jcxx_total.get("number") is None and not jcxx_total.get("ambiguous"):
        reasons.append("基础信息总学时为空" if not jcxx_total.get("raw_value") else "基础信息总学时不是可计算数字")
    if jxnr_total.get("number") is None and not jxnr_total.get("ambiguous"):
        reasons.append("教学内容总学时为空" if not jxnr_total.get("raw_value") else "教学内容总学时不是可计算数字")
    if (
        jcxx_total.get("source") == "meta"
        and jxnr_total.get("source") == "meta"
        and jcxx_total.get("source_path") == jxnr_total.get("source_path")
        and jcxx_total.get("snippet") == jxnr_total.get("snippet")
    ):
        reasons.append("基础信息总学时和教学内容总学时引用了同一处原文数值，无法确认该数值同时代表教学内容课时总计，需人工复核。")
    return reasons


def _ambiguous_total_reason(label: str, item: dict[str, Any]) -> str:
    source = item.get("ambiguous_source") if isinstance(item.get("ambiguous_source"), dict) else {}
    raw_value = _exact_value(source.get("raw_value")) or "总学时"
    snippet = _exact_value(source.get("snippet"))
    if "课程学时安排" in snippet or "周学时" in snippet or "上课周数" in snippet:
        if label == "教学内容总学时":
            return f"教学内容总学时为空；原文中的“{raw_value}”属于课程学时安排或基础信息，不是教学内容课时总计，因此不能判定学时匹配。"
        return f"{label}为空；原文中的“{raw_value}”属于课程学时安排或基础信息，不能确认该字段已填写。"
    if source.get("section_hint"):
        return f"{label}为空；原文中的“{raw_value}”出现在{source.get('section_hint')}附近，不能确认是{label}。"
    return f"{label}为空；原文中的“{raw_value}”没有明确归属，不能确认是{label}。"


def _audit_schedule_weeks(payload: dict[str, Any], meta: dict[str, Any]) -> tuple[FieldFinding, SectionFinding]:
    skzs = _resolve_semantic_number(payload_value=_as_dict(payload.get("jcxx")).get("skzs"), payload_path="payload.jcxx.skzs", semantic_field="jcxx.skzs", meta=meta, section_hints=("课程基本信息", "基本信息", "课程信息"), value_keywords=("上课周数", "授课周数", "教学周数"))
    schedule = _resolve_schedule_weeks(payload, meta)
    expected_week = skzs.get("number")
    parsed_weeks = sorted(schedule["weeks"])
    max_week = max(parsed_weeks) if parsed_weeks else None
    missing_weeks = [week for week in range(1, (max_week or 0) + 1) if week not in schedule["weeks"]]
    duplicate_weeks = sorted(schedule["duplicates"])

    reasons: list[str] = []
    if expected_week is None:
        reasons.append("基础信息上课周数为空" if not skzs.get("raw_value") else "基础信息上课周数不是可计算数字")
    if not parsed_weeks:
        reasons.append("教学安排周次为空，无法判断最大周次是否匹配")
    reasons.extend(schedule.get("errors") or [])
    if expected_week is not None and max_week is not None and max_week != expected_week:
        reasons.append(f"教学安排最大周次为 {max_week}，基础信息上课周数为 {expected_week}")

    schedule_evidence = {**schedule, "weeks": parsed_weeks, "duplicates": duplicate_weeks}
    evidence = {"jcxx_skzs": skzs, "schedule_weeks": schedule_evidence, "expected_skzs": expected_week, "parsed_weeks": parsed_weeks, "missing_weeks": missing_weeks, "duplicate_weeks": duplicate_weeks, "max_week": max_week, "fallback_used": skzs.get("source") == "meta" or schedule.get("source") == "meta"}

    reasons = _dedupe(reasons)
    if reasons:
        reason = "；".join(reasons)
        return FieldFinding(section="jxap", field="zs", path="payload.jxap.tm[].zs", status=FAIL, reason=reason, message=reason, expected=skzs, actual=schedule_evidence, evidence=evidence, suggestion="请核对教学安排中的最大周次是否与基础信息上课周数一致。"), SectionFinding(wd=JXAPZC_WD, status=FAIL, message=NO, evidence=evidence, suggestion="查看 audit_field_findings 中 section='jxap'、field='zs' 的字段原因。", details={"label": JXAPZC_LABEL, "result": NO, "reasons": reasons})

    message = "教学安排最大周次与基础信息上课周数一致。"
    return FieldFinding(section="jxap", field="zs", path="payload.jxap.tm[].zs", status=PASS, message=message, expected=skzs, actual=schedule_evidence, evidence=evidence), SectionFinding(wd=JXAPZC_WD, status=PASS, message=YES, evidence=evidence, details={"label": JXAPZC_LABEL, "result": YES, "reasons": []})

def _resolve_semantic_number(
    *,
    payload_value: Any,
    payload_path: str,
    semantic_field: str,
    meta: dict[str, Any],
    section_hints: tuple[str, ...],
    value_keywords: tuple[str, ...],
) -> dict[str, Any]:
    payload_text = _exact_value(payload_value)
    payload_number = _first_number(payload_text)
    if payload_number is not None:
        return {
            "semantic_field": semantic_field,
            "source": "payload",
            "path": payload_path,
            "raw_value": payload_text,
            "number": payload_number,
        }

    fallback = _find_meta_number(meta, semantic_field, section_hints, value_keywords)
    if fallback:
        fallback["payload_path"] = payload_path
        fallback["payload_value"] = payload_text
        return fallback

    ambiguous = _find_meta_number(meta, semantic_field, tuple(), value_keywords)
    result = {
        "semantic_field": semantic_field,
        "source": "payload",
        "path": payload_path,
        "raw_value": payload_text,
        "number": None,
    }
    if ambiguous:
        result["ambiguous"] = True
        result["ambiguous_source"] = ambiguous
    return result


def _find_meta_number(
    meta: dict[str, Any],
    semantic_field: str,
    section_hints: tuple[str, ...],
    value_keywords: tuple[str, ...],
) -> dict[str, Any] | None:
    for source in _meta_text_sources(meta):
        text = source["text"]
        snippets = _section_snippets(text, section_hints) if section_hints else [{"section_hint": "", "snippet": text[:500]}]
        for item in snippets:
            number_item = _number_from_snippet(item["snippet"], value_keywords)
            if not number_item:
                continue
            return {
                "semantic_field": semantic_field,
                "source": "meta",
                "source_path": source["source_path"],
                "section_hint": item["section_hint"],
                "raw_value": number_item["raw_value"],
                "number": number_item["number"],
                "snippet": item["snippet"][:500],
            }
    return None


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


def _section_snippets(text: str, section_hints: tuple[str, ...]) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    for hint in section_hints:
        for match in re.finditer(re.escape(hint), text):
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 800)
            snippets.append({"section_hint": hint, "snippet": text[start:end]})
    return snippets


def _number_from_snippet(snippet: str, value_keywords: tuple[str, ...]) -> dict[str, Any] | None:
    for keyword in value_keywords:
        pattern = rf"{re.escape(keyword)}\s*[:：]?\s*(\d+)"
        match = re.search(pattern, snippet)
        if match:
            return {"raw_value": match.group(0), "number": int(match.group(1))}
    return None


def _resolve_schedule_weeks(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    jxap = _as_dict(payload.get("jxap"))
    rows = _as_list(jxap.get("tm"))
    parsed = _collect_week_values(
        [
            {
                "raw_value": _exact_value(_as_dict(row).get("zs")),
                "source_path": f"payload.jxap.tm[{index}].zs",
            }
            for index, row in enumerate(rows)
        ],
        source="payload",
    )
    if parsed["weeks"] or parsed["errors"] or parsed["warnings"]:
        return parsed

    apgs_values = _schedule_week_values_from_apgs(jxap.get("apgs"))
    apgs = _collect_week_values(apgs_values, source="payload")
    if apgs["weeks"] or apgs["errors"] or apgs["warnings"]:
        return apgs

    meta_values = _schedule_week_values_from_meta(meta)
    fallback = _collect_week_values(meta_values, source="meta")
    if fallback["weeks"] or fallback["errors"] or fallback["warnings"]:
        return fallback
    return parsed


def _schedule_week_values_from_apgs(value: Any) -> list[dict[str, str]]:
    text = _normalize_week_text(value)
    if not text or not any(keyword in text for keyword in ("周", "周次", "教学周", "授课周")):
        return []

    week_number = r"第?\s*[零〇一二两三四五六七八九十\d]+"
    week_range = rf"{week_number}\s*(?:[-~—–至到]\s*[零〇一二两三四五六七八九十\d]+)?"
    row_marker = r"(?:导论|绪论|考试|复习|实践|实验|研讨|讨论|汇报|第?\s*[零〇一二两三四五六七八九十\d]+\s*[章节讲篇部分单元])"
    pattern = re.compile(rf"(?<![\dA-Za-z])({week_range})(?=\s*{row_marker})")

    values: list[dict[str, str]] = []
    for match in pattern.finditer(text):
        values.append(
            {
                "raw_value": match.group(1),
                "source_path": "payload.jxap.apgs",
                "section_hint": "教学安排概述",
                "snippet": text[max(0, match.start() - 80) : match.end() + 160],
                "week_context": True,
            }
        )
    return values


def _schedule_week_values_from_meta(meta: dict[str, Any]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    week_number = r"第?\s*[零〇一二两三四五六七八九十\d]+"
    week_range = rf"{week_number}\s*(?:[-~—–至到]\s*[零〇一二两三四五六七八九十\d]+)?"
    trailing_week_list = re.compile(rf"{week_range}(?:\s*[,，、;；]\s*{week_range})+\s*(?:周|周次)")
    explicit_week = re.compile(rf"{week_range}\s*(?:周|周次)")
    week_column = re.compile(r"(?:周次|授课周次|教学周次|教学周|授课周)\s*[:：]?\s*([第零〇一二两三四五六七八九十\d\s,，、;；~\-—–至到周次]+)")
    for source in _meta_text_sources(meta):
        for item in _section_snippets(source["text"], ("教学安排", "课程安排", "授课安排", "教学进度")):
            snippet = item["snippet"]
            covered_spans: list[tuple[int, int]] = []
            for match in week_column.finditer(snippet):
                raw = match.group(1).strip()
                if raw:
                    covered_spans.append(match.span())
                    values.append({"raw_value": raw, "source_path": source["source_path"], "section_hint": item["section_hint"], "snippet": snippet[:500], "week_context": True})
            for match in trailing_week_list.finditer(snippet):
                covered_spans.append(match.span())
                values.append({"raw_value": match.group(0), "source_path": source["source_path"], "section_hint": item["section_hint"], "snippet": snippet[:500], "week_context": True})
            for match in explicit_week.finditer(snippet):
                if any(start <= match.start() and match.end() <= end for start, end in covered_spans):
                    continue
                values.append({"raw_value": match.group(0), "source_path": source["source_path"], "section_hint": item["section_hint"], "snippet": snippet[:500]})
    return values


def _collect_week_values(values: list[dict[str, str]], *, source: str) -> dict[str, Any]:
    weeks: set[int] = set()
    duplicates: set[int] = set()
    errors: list[str] = []
    warnings: list[str] = []
    out_of_range_values: set[int] = set()
    sources: list[dict[str, Any]] = []
    for item in values:
        raw_value = _exact_value(item.get("raw_value"))
        if not raw_value:
            continue
        parsed = _parse_week_expression(raw_value, allow_bare=source == "payload" or bool(item.get("week_context")))
        errors.extend(parsed["errors"])
        out_of_range_values.update(parsed["out_of_range"])
        for week in parsed["weeks"]:
            if week in weeks:
                duplicates.add(week)
            weeks.add(week)
        sources.append({**item, "weeks": sorted(parsed["weeks"]), "out_of_range": sorted(parsed["out_of_range"])})
    if out_of_range_values:
        if source == "meta":
            warnings.append("原文中存在疑似非周次数字，已过滤超过 19 的候选值，需人工复核。")
        else:
            warnings.append("教学安排周次出现超过 19 的值，已按一学期最大 19 周处理，需人工复核原文周次。")
    return {"source": source, "weeks": weeks, "duplicates": duplicates, "errors": _dedupe(errors), "warnings": _dedupe(warnings), "out_of_range": sorted(out_of_range_values), "sources": sources}


def _parse_week_expression(value: Any, *, allow_bare: bool) -> dict[str, Any]:
    text = _normalize_week_text(value)
    weeks: set[int] = set()
    out_of_range: set[int] = set()
    errors: list[str] = []
    if not text:
        return {"weeks": weeks, "errors": errors, "out_of_range": out_of_range}

    explicit_tokens = _explicit_week_tokens(text)
    if explicit_tokens:
        for token in explicit_tokens:
            token_weeks, token_out, token_errors = _parse_week_token(token, allow_bare=True)
            weeks.update(token_weeks)
            out_of_range.update(token_out)
            errors.extend(token_errors)
        if not allow_bare:
            return {"weeks": weeks, "errors": errors, "out_of_range": out_of_range}

    tokens = [token.strip() for token in re.split(r"[,，、;；\s]+", text) if token.strip()]
    if not tokens:
        tokens = [text]

    for token in tokens:
        if token in {"周", "周次"}:
            continue
        if not allow_bare and not _has_week_context(token):
            continue
        token_weeks, token_out, token_errors = _parse_week_token(token, allow_bare=allow_bare)
        weeks.update(token_weeks)
        out_of_range.update(token_out)
        errors.extend(token_errors)

    if not weeks and not out_of_range and text:
        errors.append(f"教学安排周次无法解析：{_exact_value(value)}")
    return {"weeks": weeks, "errors": errors, "out_of_range": out_of_range}


def _explicit_week_tokens(text: str) -> list[str]:
    token_pattern = re.compile(
        r"第?\s*[零〇一二两三四五六七八九十\d]+\s*"
        r"(?:[-~—–至到]\s*[零〇一二两三四五六七八九十\d]+)?\s*"
        r"(?:周次|周)"
    )
    return [match.group(0) for match in token_pattern.finditer(text)]


def _parse_week_token(token: str, *, allow_bare: bool) -> tuple[set[int], set[int], list[str]]:
    weeks: set[int] = set()
    out_of_range: set[int] = set()
    errors: list[str] = []
    cleaned = token.strip()
    cleaned = re.sub(r"^(?:周次|授课周次|教学周次|教学周|授课周)[:：]?", "", cleaned)
    cleaned = cleaned.removeprefix("第")
    cleaned = re.sub(r"(?:周次|周)$", "", cleaned)
    cleaned = cleaned.strip()

    range_parts = re.split(r"[-~—–至到]", cleaned, maxsplit=1)
    if len(range_parts) == 2:
        start = _week_number_value(range_parts[0])
        end = _week_number_value(range_parts[1])
        if start is None or end is None:
            errors.append(f"教学安排周次无法解析：{token}")
            return weeks, out_of_range, errors
        if start > end:
            errors.append(f"教学安排周次区间不合法：{token}")
            return weeks, out_of_range, errors
        for week in range(start, end + 1):
            _add_week_value(week, weeks, out_of_range)
        return weeks, out_of_range, errors

    if not allow_bare and not _has_week_context(token):
        return weeks, out_of_range, errors
    week = _week_number_value(cleaned)
    if week is None:
        errors.append(f"教学安排周次无法解析：{token}")
    else:
        _add_week_value(week, weeks, out_of_range)
    return weeks, out_of_range, errors


def _normalize_week_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _exact_value(value))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    return text.strip()


def _has_week_context(text: str) -> bool:
    return any(keyword in text for keyword in ("周", "周次", "教学周", "授课周"))


def _week_number_value(value: str) -> int | None:
    text = value.strip().removeprefix("第")
    text = re.sub(r"(?:周次|周)$", "", text).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    return _chinese_number_value(text)


def _chinese_number_value(text: str) -> int | None:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if not text:
        return None
    if text in digits:
        return digits[text]
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return None


def _add_week_value(value: int, weeks: set[int], out_of_range: set[int]) -> None:
    if 1 <= value <= MAX_SEMESTER_WEEK:
        weeks.add(value)
    else:
        out_of_range.add(value)
def _format_week_list(weeks: list[int]) -> str:
    if not weeks:
        return ""
    labels = [f"第 {week} 周" for week in weeks[:10]]
    if len(weeks) > 10:
        labels.append("等")
    return "、".join(labels)
