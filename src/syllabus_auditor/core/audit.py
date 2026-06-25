from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath
from typing import Any

from syllabus_auditor.core.audit_labels import audit_wd_label


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


BASIC_COMPARISON_FIELDS = (
    ("kcbh", "kcbh", "\u8bfe\u7a0b\u7f16\u53f7"),
    ("kkyx", "kkyx", "\u5f00\u8bfe\uff08\u9662\uff09\u7cfb"),
    ("zwkcmc", "zwkcmc", "\u4e2d\u6587\u8bfe\u7a0b\u540d\u79f0"),
    ("ywkcmc", "ywkcmc", "\u82f1\u6587\u8bfe\u7a0b\u540d\u79f0"),
    ("skyy", "skyy", "\u6388\u8bfe\u8bed\u8a00"),
    ("sfyxwxyxk", "yxwxyxk", "\u662f\u5426\u5141\u8bb8\u5916\u5b66\u9662\u9009\u8bfe"),
    ("khfs", "khfs", "\u8003\u6838\u65b9\u5f0f"),
    ("kcxz", "kcxz", "\u8bfe\u7a0b\u6027\u8d28"),
    ("kclb", "kclb", "\u8bfe\u7a0b\u7c7b\u522b"),
    ("zxs", "zxs", "\u5468\u5b66\u65f6"),
    ("skzs", "skzs", "\u4e0a\u8bfe\u5468\u6570"),
    ("zongxs", "zongxs", "\u603b\u5b66\u65f6"),
    ("jxxs", "jxxs", "\u6559\u5b66\u5b66\u65f6"),
    ("kcxf", "kcxf", "\u8bfe\u7a0b\u5b66\u5206"),
    ("rkjsxm", "zjjsxm", "\u4efb\u8bfe\u6559\u5e08\u59d3\u540d"),
)

INDEPENDENT_REQUIRED_JCXX_FIELDS = (
    ("jsgh", "\u6559\u5e08\u5de5\u53f7"),
    ("email", "E-mail"),
    ("lxdh", "\u8054\u7cfb\u7535\u8bdd"),
)

TOP_LEVEL_REQUIRED = {
    "kczwjj": "\u8bfe\u7a0b\u4e2d\u6587\u7b80\u4ecb",
    "kcywjj": "\u8bfe\u7a0b\u82f1\u6587\u7b80\u4ecb",
    "ybzsyq": "\u9884\u5907\u77e5\u8bc6\u8981\u6c42",
    "jcjydcl": "\u6559\u6750\u53ca\u9605\u8bfb\u6750\u6599",
}

SECTION_REQUIRED = {
    "kcmb": {"szmb": "\u601d\u653f\u76ee\u6807", "nlmb": "\u80fd\u529b\u76ee\u6807", "zsmb": "\u77e5\u8bc6\u76ee\u6807"},
    "jxnr": {"tm": "\u6559\u5b66\u5185\u5bb9\u6761\u76ee"},
    "jxap": {"tm": "\u6559\u5b66\u5b89\u6392\u6761\u76ee"},
    "khfsb": {"tm": "\u8003\u6838\u65b9\u5f0f\u6761\u76ee"},
}

ROW_REQUIRED = {
    "jxnr": {"xh": "\u5e8f\u53f7", "zt": "\u4e3b\u9898", "zsd": "\u77e5\u8bc6\u70b9", "xs": "\u5b66\u65f6"},
    "jxap": {"zs": "\u5468\u6b21/\u5e8f\u53f7", "sknr": "\u6388\u8bfe\u5185\u5bb9", "skfs": "\u6388\u8bfe\u65b9\u5f0f", "szyqjxx": "\u601d\u653f\u5143\u7d20\u878d\u5165"},
    "khfsb": {"ksxs": "\u8003\u8bd5\u5f62\u5f0f", "kcnr": "\u8003\u5bdf\u5185\u5bb9", "kcfs": "\u8003\u5bdf\u65b9\u5f0f", "zb": "\u5360\u6bd4"},
}

FILENAME_NOISE_PATTERNS = (
    r"\u8bfe\u7a0b\u65b9\u6848\u5b8c\u6574\u7248",
    r"\u8bfe\u7a0b\u65b9\u6848",
    r"\u8bfe\u7a0b\u5b9e\u65bd\u65b9\u6848",
    r"\u6559\u5b66\u5927\u7eb2",
    r"\u5b8c\u6574\u7248",
    r"\u6700\u7ec8\u7248",
    r"\u4fee\u8ba2\u7248",
    r"\u65b0\u7248",
)


def build_subject_key(*, extraction_id: int, course_code: str, source_path: str) -> str:
    if course_code.strip():
        return f"kcbh:{course_code.strip()}"
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
    for pattern in FILENAME_NOISE_PATTERNS:
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
    findings.extend(_extraction_warning_findings(subject.meta))
    findings.extend(_hour_consistency_findings(subject.payload))
    findings.extend(_extraction_status_finding(subject.extraction_status))

    section_findings = [kcjbxx_section, jxnrxs_section, jxapzc_section]
    fail_count = sum(1 for item in findings if item.status in {FAIL, ERROR, "manual_review"})
    warning_count = sum(1 for item in findings if item.status == WARNING)
    overall_status = _overall_status(fail_count, warning_count, subject.extraction_status)
    summary = _summary(findings, section_findings, match)
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

    for pdf_field, course_field, label in BASIC_COMPARISON_FIELDS:
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

    for pdf_field, label in INDEPENDENT_REQUIRED_JCXX_FIELDS:
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
    if not has_course:
        message = f"\u65e0\u6cd5\u5b9a\u4f4d\u8bfe\u7a0b\u5e93\u8bb0\u5f55\uff0c\u4e0d\u80fd\u5224\u65ad{label}\u662f\u5426\u4e00\u81f4"
        return FieldFinding(section="jcxx", field=pdf_field, path=path, status=FAIL, reason=message, message=message, expected="", actual=pdf_value, evidence={"course_field": course_field}, suggestion="\u5148\u786e\u8ba4\u8be5 PDF \u5bf9\u5e94\u7684\u8bfe\u7a0b\u5e93\u8bb0\u5f55\u3002")
    if not pdf_value and not course_value:
        message = f"PDF \u548c\u8bfe\u7a0b\u5e93\u4e2d\u7684{label}\u90fd\u4e3a\u7a7a"
    elif not pdf_value:
        message = f"{label}\u4e3a\u7a7a"
    elif not course_value:
        message = f"\u8bfe\u7a0b\u5e93\u4e2d{label}\u4e3a\u7a7a"
    elif pdf_value != course_value:
        message = f"{label}\u4e0e\u8bfe\u7a0b\u5e93\u4e0d\u4e00\u81f4\uff1a\u8bfe\u7a0b\u5e93\u4e3a {course_value}\uff0cPDF \u4e3a {pdf_value}"
    else:
        return FieldFinding(section="jcxx", field=pdf_field, path=path, status=PASS, message=f"{label}\u4e0e\u8bfe\u7a0b\u5e93\u4e00\u81f4\u3002", expected=course_value, actual=pdf_value, evidence={"course_field": course_field})

    return FieldFinding(section="jcxx", field=pdf_field, path=path, status=FAIL, reason=message, message=message, expected=course_value, actual=pdf_value, evidence={"course_field": course_field}, suggestion=f"\u8bf7\u6838\u5bf9 PDF \u548c\u8bfe\u7a0b\u5e93\u4e2d\u7684{label}\u3002")


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
    for field_name, label in TOP_LEVEL_REQUIRED.items():
        findings.append(_presence_finding("payload", field_name, f"payload.{field_name}", label, payload.get(field_name)))

    for section, fields in SECTION_REQUIRED.items():
        block = _as_dict(payload.get(section))
        for field_name, label in fields.items():
            findings.append(
                _presence_finding(section, field_name, f"payload.{section}.{field_name}", label, block.get(field_name))
            )

    _append_kcyq_findings(payload, findings)
    _append_row_findings(payload, findings)
    return findings


def _append_kcyq_findings(payload: dict[str, Any], findings: list[FieldFinding]) -> None:
    kcyqb = _as_dict(payload.get("kcyqb"))
    has_text = not _is_empty(payload.get("kcyq"))
    has_table = not _is_empty(kcyqb.get("tm"))
    has_summary = not _is_empty(kcyqb.get("yqgs"))
    if has_text or has_table or has_summary:
        findings.append(
            FieldFinding(
                section="kcyq",
                field="content",
                path="payload.kcyq",
                status=PASS,
                message="课程要求已填写。",
                actual={"has_text": has_text, "has_table": has_table, "has_summary": has_summary},
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
                message="课程要求为空，未抽取到文本或结构化条目。",
                actual="",
                suggestion="补充课程要求，或检查 PDF 模板中课程要求章节是否可识别。",
            )
        )


def _append_row_findings(payload: dict[str, Any], findings: list[FieldFinding]) -> None:
    for section, fields in ROW_REQUIRED.items():
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


def _extraction_warning_findings(meta: dict[str, Any]) -> list[FieldFinding]:
    findings: list[FieldFinding] = []
    for index, warning in enumerate(_as_list(meta.get("extraction_warnings"))):
        warning_dict = _as_dict(warning)
        section = _text(warning_dict.get("section")) or "system"
        field_name = _text(warning_dict.get("field")) or "warning"
        raw_reason = _text(warning_dict.get("reason")) or "extraction_warning"
        path = _text(warning_dict.get("path")) or f"meta.extraction_warnings[{index}]"
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


def _summary(field_findings: list[FieldFinding], section_findings: list[SectionFinding], match: CourseMatch) -> dict[str, Any]:
    failed = [item for item in field_findings if item.status in {FAIL, ERROR, "manual_review"}]
    warnings = [item for item in field_findings if item.status == WARNING]
    return {
        "fail_count": len(failed),
        "warning_count": len(warnings),
        "main_reasons": _dedupe([item.reason for item in failed + warnings if item.reason])[:20],
        "messages": [item.message for item in failed[:5]],
        "sections": {item.wd: item.status for item in section_findings},
        "course_match": _course_match_summary(match, None),
    }


def _coerce_course_match(value: CourseMatch | dict[str, Any] | None) -> CourseMatch:
    if isinstance(value, CourseMatch):
        return value
    if isinstance(value, dict):
        return CourseMatch(status="matched", method="matched_by_kcbh", course_row=value)
    return CourseMatch(status="not_found", method="not_found", reasons=["无法定位课程库记录"])


def _course_match_summary(match: CourseMatch, subject: AuditSubject | None) -> dict[str, Any]:
    row = match.course_row or {}
    return {
        "status": match.status,
        "method": match.method,
        "query": match.query,
        "matched_kcbh": _exact_value(row.get("kcbh")),
        "matched_zwkcmc": _exact_value(row.get("zwkcmc")),
        "source_path": subject.source_path if subject else "",
        "candidate_count": len(match.candidates),
    }


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
    if jcxx_total.get("ambiguous") or jxnr_total.get("ambiguous"):
        reasons.append("meta \u4e2d\u603b\u5b66\u65f6\u6765\u6e90\u65e0\u6cd5\u533a\u5206\uff0c\u9700\u4eba\u5de5\u590d\u6838")
    if jcxx_total.get("number") is None:
        reasons.append("\u57fa\u7840\u4fe1\u606f\u603b\u5b66\u65f6\u4e3a\u7a7a" if not jcxx_total.get("raw_value") else "\u57fa\u7840\u4fe1\u606f\u603b\u5b66\u65f6\u4e0d\u662f\u53ef\u8ba1\u7b97\u6570\u5b57")
    if jxnr_total.get("number") is None:
        reasons.append("\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6\u4e3a\u7a7a" if not jxnr_total.get("raw_value") else "\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6\u4e0d\u662f\u53ef\u8ba1\u7b97\u6570\u5b57")
    if jcxx_total.get("source") == "meta" and jxnr_total.get("source") == "meta" and jcxx_total.get("source_path") == jxnr_total.get("source_path") and jcxx_total.get("snippet") == jxnr_total.get("snippet"):
        reasons.append("meta \u4e2d\u603b\u5b66\u65f6\u6765\u6e90\u65e0\u6cd5\u533a\u5206\uff0c\u9700\u4eba\u5de5\u590d\u6838")

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


def _audit_schedule_weeks(payload: dict[str, Any], meta: dict[str, Any]) -> tuple[FieldFinding, SectionFinding]:
    skzs = _resolve_semantic_number(payload_value=_as_dict(payload.get("jcxx")).get("skzs"), payload_path="payload.jcxx.skzs", semantic_field="jcxx.skzs", meta=meta, section_hints=("\u8bfe\u7a0b\u57fa\u672c\u4fe1\u606f", "\u57fa\u672c\u4fe1\u606f", "\u8bfe\u7a0b\u4fe1\u606f"), value_keywords=("\u4e0a\u8bfe\u5468\u6570", "\u6388\u8bfe\u5468\u6570", "\u6559\u5b66\u5468\u6570"))
    schedule = _resolve_schedule_weeks(payload, meta)
    expected_week = skzs.get("number")
    parsed_weeks = sorted(schedule["weeks"])
    max_week = max(parsed_weeks) if parsed_weeks else None
    missing_weeks = [week for week in range(1, (max_week or 0) + 1) if week not in schedule["weeks"]]
    duplicate_weeks = sorted(schedule["duplicates"])

    reasons: list[str] = []
    if expected_week is None:
        reasons.append("\u57fa\u7840\u4fe1\u606f\u4e0a\u8bfe\u5468\u6570\u4e3a\u7a7a" if not skzs.get("raw_value") else "\u57fa\u7840\u4fe1\u606f\u4e0a\u8bfe\u5468\u6570\u4e0d\u662f\u53ef\u8ba1\u7b97\u6570\u5b57")
    if not parsed_weeks:
        reasons.append("\u6559\u5b66\u5b89\u6392\u5468\u6b21\u4e3a\u7a7a\uff0c\u65e0\u6cd5\u5224\u65ad\u5468\u6b21\u662f\u5426\u8fde\u7eed")
    if schedule["errors"]:
        reasons.extend(schedule["errors"])
    if missing_weeks:
        reasons.append(f"\u6559\u5b66\u5b89\u6392\u5468\u6b21\u4e0d\u8fde\u7eed\uff0c\u7f3a\u5c11{_format_week_list(missing_weeks)}")
    if duplicate_weeks:
        reasons.append(f"\u6559\u5b66\u5b89\u6392\u5468\u6b21\u91cd\u590d\uff0c\u91cd\u590d\u5468\u6b21\u4e3a{_format_week_list(duplicate_weeks)}")
    if expected_week is not None and max_week is not None and max_week != expected_week:
        reasons.append(f"\u6559\u5b66\u5b89\u6392\u6700\u5927\u5468\u6b21\u4e3a {max_week}\uff0c\u57fa\u7840\u4fe1\u606f\u4e0a\u8bfe\u5468\u6570\u4e3a {expected_week}")

    schedule_evidence = {**schedule, "weeks": parsed_weeks, "duplicates": duplicate_weeks}
    evidence = {"jcxx_skzs": skzs, "schedule_weeks": schedule_evidence, "expected_skzs": expected_week, "parsed_weeks": parsed_weeks, "missing_weeks": missing_weeks, "duplicate_weeks": duplicate_weeks, "max_week": max_week, "fallback_used": skzs.get("source") == "meta" or schedule.get("source") == "meta"}

    reasons = _dedupe(reasons)
    if reasons:
        reason = "\uff1b".join(reasons)
        return FieldFinding(section="jxap", field="zs", path="payload.jxap.tm[].zs", status=FAIL, reason=reason, message=reason, expected=skzs, actual=schedule_evidence, evidence=evidence, suggestion="\u8bf7\u6838\u5bf9\u6559\u5b66\u5b89\u6392\u8868\u7684\u5468\u6b21\u662f\u5426\u4ece\u7b2c 1 \u5468\u5f00\u59cb\u8fde\u7eed\u8986\u76d6\uff0c\u5e76\u4e0e\u57fa\u7840\u4fe1\u606f\u4e0a\u8bfe\u5468\u6570\u4e00\u81f4\u3002"), SectionFinding(wd=JXAPZC_WD, status=FAIL, message=NO, evidence=evidence, suggestion="\u67e5\u770b audit_field_findings \u4e2d section='jxap'\u3001field='zs' \u7684\u5b57\u6bb5\u539f\u56e0\u3002", details={"label": JXAPZC_LABEL, "result": NO, "reasons": reasons})

    message = "\u6559\u5b66\u5b89\u6392\u5468\u6b21\u8fde\u7eed\uff0c\u4e14\u6700\u5927\u5468\u6b21\u4e0e\u57fa\u7840\u4fe1\u606f\u4e0a\u8bfe\u5468\u6570\u4e00\u81f4\u3002"
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
    rows = _as_list(_as_dict(payload.get("jxap")).get("tm"))
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
    if parsed["weeks"] or parsed["errors"]:
        return parsed

    meta_values = _schedule_week_values_from_meta(meta)
    fallback = _collect_week_values(meta_values, source="meta")
    if fallback["weeks"] or fallback["errors"]:
        return fallback
    return parsed


def _schedule_week_values_from_meta(meta: dict[str, Any]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for source in _meta_text_sources(meta):
        for item in _section_snippets(source["text"], ("\u6559\u5b66\u5b89\u6392", "\u8bfe\u7a0b\u5b89\u6392", "\u6388\u8bfe\u5b89\u6392", "\u6559\u5b66\u8fdb\u5ea6")):
            for match in re.finditer(r"(?:\u7b2c?\s*\d+\s*(?:\u5468|\u5468\u6b21)?\s*(?:[-~\u2014\u2013\u81f3\u5230]\s*\d+\s*(?:\u5468|\u5468\u6b21)?)?)(?:\s*[,\uff0c\u3001\uff1b;]\s*\u7b2c?\s*\d+\s*(?:\u5468|\u5468\u6b21)?\s*(?:[-~\u2014\u2013\u81f3\u5230]\s*\d+\s*(?:\u5468|\u5468\u6b21)?)?)*", item["snippet"]):
                values.append({"raw_value": match.group(0), "source_path": source["source_path"], "section_hint": item["section_hint"], "snippet": item["snippet"][:500]})
    return values


def _collect_week_values(values: list[dict[str, str]], *, source: str) -> dict[str, Any]:
    weeks: set[int] = set()
    duplicates: set[int] = set()
    errors: list[str] = []
    sources: list[dict[str, Any]] = []
    for item in values:
        raw_value = _exact_value(item.get("raw_value"))
        if not raw_value:
            continue
        parsed = _parse_week_expression(raw_value)
        errors.extend(parsed["errors"])
        for week in parsed["weeks"]:
            if week in weeks:
                duplicates.add(week)
            weeks.add(week)
        sources.append({**item, "weeks": sorted(parsed["weeks"])})
    return {"source": source, "weeks": weeks, "duplicates": duplicates, "errors": _dedupe(errors), "sources": sources}


def _parse_week_expression(value: Any) -> dict[str, Any]:
    text = _exact_value(value)
    weeks: set[int] = set()
    errors: list[str] = []
    masked = text
    range_pattern = re.compile(r"\u7b2c?\s*(\d+)\s*(?:\u5468|\u5468\u6b21)?\s*[-~\u2014\u2013\u81f3\u5230]\s*(\d+)\s*(?:\u5468|\u5468\u6b21)?")
    for match in range_pattern.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2))
        if start > end:
            errors.append(f"\u6559\u5b66\u5b89\u6392\u5468\u6b21\u533a\u95f4\u4e0d\u5408\u6cd5\uff1a{match.group(0)}")
        else:
            weeks.update(range(start, end + 1))
        masked = masked.replace(match.group(0), " ")
    for match in re.finditer(r"\u7b2c?\s*(\d+)\s*(?:\u5468|\u5468\u6b21)?", masked):
        weeks.add(int(match.group(1)))
    if not weeks and text:
        errors.append(f"\u6559\u5b66\u5b89\u6392\u5468\u6b21\u65e0\u6cd5\u89e3\u6790\uff1a{text}")
    return {"weeks": weeks, "errors": errors}


def _format_week_list(weeks: list[int]) -> str:
    if not weeks:
        return ""
    labels = [f"第 {week} 周" for week in weeks[:10]]
    if len(weeks) > 10:
        labels.append("等")
    return "、".join(labels)
