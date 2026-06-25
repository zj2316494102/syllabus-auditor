from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath
from typing import Any


PASS = "pass"
FAIL = "fail"
WARNING = "warning"
ERROR = "error"
SKIPPED = "skipped"

KCJBXX_WD = "kcjbxxsfykckyz"
KCJBXX_LABEL = "课程基本信息是否与课程库一致"
JXNRXS_WD = "jxnrsfyxspp"
JXAPZC_WD = "jxapsfyzcpp"
JXAPZC_LABEL = "教学安排是否与周次匹配"
JXNRXS_LABEL = "教学内容是否与学时匹配"
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
    ("kcbh", "kcbh", "课程编号"),
    ("kkyx", "kkyx", "开课（院）系"),
    ("zwkcmc", "zwkcmc", "中文课程名称"),
    ("ywkcmc", "ywkcmc", "英文课程名称"),
    ("skyy", "skyy", "授课语言"),
    ("sfyxwxyxk", "yxwxyxk", "是否允许外学院选课"),
    ("khfs", "khfs", "考核方式"),
    ("kcxz", "kcxz", "课程性质"),
    ("kclb", "kclb", "课程类别"),
    ("zxs", "zxs", "周学时"),
    ("skzs", "skzs", "上课周数"),
    ("zongxs", "zongxs", "总学时"),
    ("jxxs", "jxxs", "教学学时"),
    ("kcxf", "kcxf", "课程学分"),
    ("rkjsxm", "zjjsxm", "任课教师姓名"),
)

INDEPENDENT_REQUIRED_JCXX_FIELDS = (
    ("jsgh", "教师工号"),
    ("email", "E-mail"),
    ("lxdh", "联系电话"),
)

TOP_LEVEL_REQUIRED = {
    "kczwjj": "课程中文简介",
    "kcywjj": "课程英文简介",
    "ybzsyq": "预备知识要求",
    "jcjydcl": "教材及阅读材料",
}

SECTION_REQUIRED = {
    "kcmb": {"szmb": "思政目标", "nlmb": "能力目标", "zsmb": "知识目标"},
    "jxnr": {"tm": "教学内容条目"},
    "jxap": {"tm": "教学安排条目"},
    "khfsb": {"tm": "考核方式条目"},
}

ROW_REQUIRED = {
    "jxnr": {"xh": "序号", "zt": "主题", "zsd": "知识点", "xs": "学时"},
    "jxap": {"zs": "周次/序号", "sknr": "授课内容", "skfs": "授课方式", "szyqjxx": "思政元素融入"},
    "khfsb": {"ksxs": "考试形式", "kcnr": "考察内容", "kcfs": "考察方式", "zb": "占比"},
}

FILENAME_NOISE_PATTERNS = (
    r"课程方案完整版",
    r"课程方案",
    r"课程实施方案",
    r"教学大纲",
    r"完整版",
    r"最终版",
    r"修订版",
    r"新版",
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
    section_findings.extend(_build_section_findings(findings))
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
                suggestion="请人工核对 PDF 文件名、课程编号、课程名称与课程库记录。",
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
            dimension_reasons.append(finding.message)

    hours_formula_finding = _basic_hours_formula_finding(jcxx)
    if hours_formula_finding:
        findings.append(hours_formula_finding)
        if hours_formula_finding.status != PASS:
            dimension_reasons.append(hours_formula_finding.message)

    for pdf_field, label in INDEPENDENT_REQUIRED_JCXX_FIELDS:
        value = _exact_value(jcxx.get(pdf_field))
        if value:
            findings.append(
                FieldFinding(
                    section="jcxx",
                    field=pdf_field,
                    path=f"payload.jcxx.{pdf_field}",
                    status=PASS,
                    message=f"{label}已填写。",
                    actual=value,
                )
            )
        else:
            message = f"{label}为空"
            findings.append(
                FieldFinding(
                    section="jcxx",
                    field=pdf_field,
                    path=f"payload.jcxx.{pdf_field}",
                    status=FAIL,
                    reason=message,
                    message=message,
                    actual="",
                    suggestion=f"请补充 PDF 中的{label}。",
                )
            )
            dimension_reasons.append(message)

    failed = [item for item in findings if item.status in {FAIL, ERROR}]
    status = FAIL if failed else PASS
    result = "否" if failed else "是"
    details = {
        "label": KCJBXX_LABEL,
        "result": result,
        "reasons": _dedupe([reason for reason in dimension_reasons if reason] if failed else []),
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
        suggestion="查看 audit_field_findings 中 section='jcxx' 的字段原因。" if failed else "",
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
        message = f"无法定位课程库记录，不能判断{label}是否一致"
        return FieldFinding(
            section="jcxx",
            field=pdf_field,
            path=path,
            status=FAIL,
            reason=message,
            message=message,
            expected="",
            actual=pdf_value,
            evidence={"course_field": course_field},
            suggestion="先确认该 PDF 对应的课程库记录。",
        )
    if not pdf_value and not course_value:
        message = f"PDF 和课程库中的{label}都为空"
    elif not pdf_value:
        message = f"{label}为空"
    elif not course_value:
        message = f"课程库中{label}为空"
    elif pdf_value != course_value:
        message = f"{label}与课程库不一致：课程库为 {course_value}，PDF 为 {pdf_value}"
    else:
        return FieldFinding(
            section="jcxx",
            field=pdf_field,
            path=path,
            status=PASS,
            message=f"{label}与课程库一致。",
            expected=course_value,
            actual=pdf_value,
            evidence={"course_field": course_field},
        )

    return FieldFinding(
        section="jcxx",
        field=pdf_field,
        path=path,
        status=FAIL,
        reason=message,
        message=message,
        expected=course_value,
        actual=pdf_value,
        evidence={"course_field": course_field},
        suggestion=f"请核对 PDF 和课程库中的{label}。",
    )


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
        message = f"总学时、周学时或上课周数不是可计算数字：总学时为 {zongxs_text}，周学时为 {zxs_text}，上课周数为 {skzs_text}"
        return FieldFinding(
            section="jcxx",
            field="zongxs",
            path="payload.jcxx.zongxs",
            status=FAIL,
            reason=message,
            message=message,
            expected={"formula": "总学时 = 周学时 × 上课周数"},
            actual={"zongxs": zongxs_text, "zxs": zxs_text, "skzs": skzs_text},
            suggestion="请核对 PDF 中总学时、周学时和上课周数的填写。",
        )

    expected = zxs * skzs
    if expected == zongxs:
        return FieldFinding(
            section="jcxx",
            field="zongxs",
            path="payload.jcxx.zongxs",
            status=PASS,
            message="总学时等于周学时乘以上课周数。",
            expected=expected,
            actual=zongxs,
            evidence={"formula": "zongxs = zxs * skzs", "zxs": zxs, "skzs": skzs},
        )

    message = f"总学时不等于周学时乘以上课周数：总学时为 {zongxs_text}，周学时 {zxs_text} × 上课周数 {skzs_text} = {_format_number(expected)}"
    return FieldFinding(
        section="jcxx",
        field="zongxs",
        path="payload.jcxx.zongxs",
        status=FAIL,
        reason=message,
        message=message,
        expected=_format_number(expected),
        actual=zongxs_text,
        evidence={"formula": "zongxs = zxs * skzs", "zxs": zxs_text, "skzs": skzs_text},
        suggestion="请核对 PDF 中总学时、周学时和上课周数是否一致。",
    )


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
        if fail_count:
            status = FAIL
            message = f"{section} 有 {fail_count} 个不通过字段。"
        elif warning_count:
            status = WARNING
            message = f"{section} 有 {warning_count} 个警告字段。"
        else:
            status = PASS
            message = f"{section} 通过。"
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
    jcxx_total = _resolve_semantic_number(
        payload_value=_as_dict(payload.get("jcxx")).get("zongxs"),
        payload_path="payload.jcxx.zongxs",
        semantic_field="jcxx.zongxs",
        meta=meta,
        section_hints=("课程基本信息", "基本信息", "课程信息"),
        value_keywords=("总学时", "课程总学时"),
    )
    jxnr_total = _resolve_semantic_number(
        payload_value=_as_dict(payload.get("jxnr")).get("zongxs"),
        payload_path="payload.jxnr.zongxs",
        semantic_field="jxnr.zongxs",
        meta=meta,
        section_hints=("教学内容", "课程内容"),
        value_keywords=("总学时", "合计", "合计学时", "小计"),
    )
    evidence = {
        "jcxx_zongxs": jcxx_total,
        "jxnr_zongxs": jxnr_total,
        "fallback_used": jcxx_total.get("source") == "meta" or jxnr_total.get("source") == "meta",
    }

    reasons: list[str] = []
    if jcxx_total.get("ambiguous") or jxnr_total.get("ambiguous"):
        reasons.append("meta 中总学时来源无法区分，需人工复核")
    if jcxx_total.get("number") is None:
        reasons.append("基础信息总学时为空" if not jcxx_total.get("raw_value") else "基础信息总学时不是可计算数字")
    if jxnr_total.get("number") is None:
        reasons.append("教学内容总学时为空" if not jxnr_total.get("raw_value") else "教学内容总学时不是可计算数字")
    if (
        jcxx_total.get("source") == "meta"
        and jxnr_total.get("source") == "meta"
        and jcxx_total.get("source_path") == jxnr_total.get("source_path")
        and jcxx_total.get("snippet") == jxnr_total.get("snippet")
    ):
        reasons.append("meta 中总学时来源无法区分，需人工复核")

    jcxx_number = jcxx_total.get("number")
    jxnr_number = jxnr_total.get("number")
    if not reasons and jcxx_number != jxnr_number:
        reasons.append(f"教学内容总学时与基础信息总学时不一致：基础信息为 {jcxx_number}，教学内容为 {jxnr_number}")

    reasons = _dedupe(reasons)
    if reasons:
        reason = reasons[0]
        field_finding = FieldFinding(
            section="jxnr",
            field="zongxs",
            path="payload.jxnr.zongxs",
            status=FAIL,
            reason=reason,
            message=reason,
            expected=jcxx_total,
            actual=jxnr_total,
            evidence=evidence,
            suggestion="请核对基础信息和教学内容中的总学时填写是否一致；结构化字段缺失时复核 PDF 原文对应章节。",
        )
        section_finding = SectionFinding(
            wd=JXNRXS_WD,
            status=FAIL,
            message="否",
            evidence=evidence,
            suggestion="查看 audit_field_findings 中 section='jxnr'、field='zongxs' 的字段原因。",
            details={"label": JXNRXS_LABEL, "result": "否", "reasons": reasons},
        )
        return field_finding, section_finding

    message = "教学内容总学时与基础信息总学时一致。"
    field_finding = FieldFinding(
        section="jxnr",
        field="zongxs",
        path="payload.jxnr.zongxs",
        status=PASS,
        message=message,
        expected=jcxx_total,
        actual=jxnr_total,
        evidence=evidence,
    )
    section_finding = SectionFinding(
        wd=JXNRXS_WD,
        status=PASS,
        message="是",
        evidence=evidence,
        details={"label": JXNRXS_LABEL, "result": "是", "reasons": []},
    )
    return field_finding, section_finding


def _audit_schedule_weeks(payload: dict[str, Any], meta: dict[str, Any]) -> tuple[FieldFinding, SectionFinding]:
    skzs = _resolve_semantic_number(
        payload_value=_as_dict(payload.get("jcxx")).get("skzs"),
        payload_path="payload.jcxx.skzs",
        semantic_field="jcxx.skzs",
        meta=meta,
        section_hints=("课程基本信息", "基本信息", "课程信息"),
        value_keywords=("上课周数", "授课周数", "教学周数"),
    )
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
        reasons.append("教学安排周次为空，无法判断周次是否连续")
    if schedule["errors"]:
        reasons.extend(schedule["errors"])
    if missing_weeks:
        reasons.append(f"教学安排周次不连续，缺少{_format_week_list(missing_weeks)}")
    if duplicate_weeks:
        reasons.append(f"教学安排周次重复，重复周次为{_format_week_list(duplicate_weeks)}")
    if expected_week is not None and max_week is not None and max_week != expected_week:
        reasons.append(f"教学安排最大周次为 {max_week}，基础信息上课周数为 {expected_week}")

    schedule_evidence = {
        **schedule,
        "weeks": parsed_weeks,
        "duplicates": duplicate_weeks,
    }
    evidence = {
        "jcxx_skzs": skzs,
        "schedule_weeks": schedule_evidence,
        "expected_skzs": expected_week,
        "parsed_weeks": parsed_weeks,
        "missing_weeks": missing_weeks,
        "duplicate_weeks": duplicate_weeks,
        "max_week": max_week,
        "fallback_used": skzs.get("source") == "meta" or schedule.get("source") == "meta",
    }

    reasons = _dedupe(reasons)
    if reasons:
        reason = reasons[0]
        field_finding = FieldFinding(
            section="jxap",
            field="zs",
            path="payload.jxap.tm[].zs",
            status=FAIL,
            reason=reason,
            message=reason,
            expected=skzs,
            actual=schedule_evidence,
            evidence=evidence,
            suggestion="请核对教学安排表的周次是否从第 1 周开始连续覆盖，并与基础信息上课周数一致。",
        )
        section_finding = SectionFinding(
            wd=JXAPZC_WD,
            status=FAIL,
            message="否",
            evidence=evidence,
            suggestion="查看 audit_field_findings 中 section='jxap'、field='zs' 的字段原因。",
            details={"label": JXAPZC_LABEL, "result": "否", "reasons": reasons},
        )
        return field_finding, section_finding

    message = "教学安排周次连续，且最大周次与基础信息上课周数一致。"
    field_finding = FieldFinding(
        section="jxap",
        field="zs",
        path="payload.jxap.tm[].zs",
        status=PASS,
        message=message,
        expected=skzs,
        actual=schedule_evidence,
        evidence=evidence,
    )
    section_finding = SectionFinding(
        wd=JXAPZC_WD,
        status=PASS,
        message="是",
        evidence=evidence,
        details={"label": JXAPZC_LABEL, "result": "是", "reasons": []},
    )
    return field_finding, section_finding


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
        for item in _section_snippets(source["text"], ("教学安排", "课程安排", "授课安排")):
            for match in re.finditer(r"(?:第?\d+\s*(?:周|週)?\s*(?:[-~—–至到]\s*\d+\s*(?:周|週)?)?)(?:\s*[,，、;；]\s*第?\d+\s*(?:周|週)?\s*(?:[-~—–至到]\s*\d+\s*(?:周|週)?)?)*", item["snippet"]):
                values.append(
                    {
                        "raw_value": match.group(0),
                        "source_path": source["source_path"],
                        "section_hint": item["section_hint"],
                        "snippet": item["snippet"][:500],
                    }
                )
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
    range_pattern = re.compile(r"第?\s*(\d+)\s*(?:周|週)?\s*[-~—–至到]\s*(\d+)\s*(?:周|週)?")
    for match in range_pattern.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2))
        if start > end:
            errors.append(f"教学安排周次区间不合法：{match.group(0)}")
        else:
            weeks.update(range(start, end + 1))
        masked = masked.replace(match.group(0), " ")
    for match in re.finditer(r"第?\s*(\d+)\s*(?:周|週)?", masked):
        weeks.add(int(match.group(1)))
    if not weeks and text:
        errors.append(f"教学安排周次无法解析：{text}")
    return {"weeks": weeks, "errors": errors}


def _format_week_list(weeks: list[int]) -> str:
    if not weeks:
        return ""
    labels = [f"第 {week} 周" for week in weeks[:10]]
    if len(weeks) > 10:
        labels.append("等")
    return "、".join(labels)
