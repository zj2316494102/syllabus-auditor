"""审核结果归一化逻辑的单元测试。"""
from syllabus_auditor.core.audit import (
    CourseMatch,
    AuditSubject,
    _parse_week_expression,
    _resolve_schedule_weeks,
    audit_subject,
    JXAPZC_WD,
)
from syllabus_auditor.shared.reason_text import clean_customer_reason
from syllabus_auditor.auditors.xxyzwzfhmb import _basic_info_findings


def test_course_name_normalized_match_passes_visual_differences():
    subject = AuditSubject(
        extraction_id=1,
        course_code="K1",
        source_path="demo.pdf",
        payload={"jcxx": {"kcbh": "K1", "zwkcmc": "高级微观经济学（II）", "ywkcmc": "Principles and Practice of Tort Law"}},
        meta={},
    )
    match = CourseMatch(
        status="matched",
        method="matched_by_kcbh",
        course_row={"kcbh": "K1", "zwkcmc": "高级微观经济学（II）", "ywkcmc": "Principles and practice of tort law"},
    )
    audit = audit_subject(subject, match)
    name_findings = {(item.field, item.path): item for item in audit.field_findings if item.field in {"zwkcmc", "ywkcmc"}}
    assert name_findings[("zwkcmc", "payload.jcxx.zwkcmc")].status == "pass"
    assert name_findings[("ywkcmc", "payload.jcxx.ywkcmc")].status == "pass"
    assert name_findings[("ywkcmc", "payload.jcxx.ywkcmc")].evidence["comparison"] == "normalized_course_name"


def test_course_name_substantive_difference_still_fails():
    subject = AuditSubject(
        extraction_id=1,
        course_code="K1",
        source_path="demo.pdf",
        payload={"jcxx": {"kcbh": "K1", "zwkcmc": "国际金融理论与政策研究", "ywkcmc": "Research on International Financial Theory and Policy"}},
        meta={},
    )
    match = CourseMatch(
        status="matched",
        method="matched_by_kcbh",
        course_row={"kcbh": "K1", "zwkcmc": "国际金融理论与政策研究", "ywkcmc": "Issues on Theories and Policies of International Finance"},
    )
    audit = audit_subject(subject, match)
    english = next(item for item in audit.field_findings if item.field == "ywkcmc" and item.path == "payload.jcxx.ywkcmc")
    assert english.status == "fail"
    assert "英文课程名称与课程库不一致" in english.reason


def test_week_parser_accepts_chinese_numbers_lists_and_ranges():
    assert _parse_week_expression("一", allow_bare=True)["weeks"] == {1}
    assert _parse_week_expression("十四", allow_bare=True)["weeks"] == {14}
    assert _parse_week_expression("第一周", allow_bare=True)["weeks"] == {1}
    assert _parse_week_expression("第十四周", allow_bare=True)["weeks"] == {14}
    assert _parse_week_expression("一至三", allow_bare=True)["weeks"] == {1, 2, 3}
    assert _parse_week_expression("1,14", allow_bare=True)["weeks"] == {1, 14}
    assert _parse_week_expression("一、十四", allow_bare=True)["weeks"] == {1, 14}
    assert _parse_week_expression("1, 3, 5-7", allow_bare=True)["weeks"] == {1, 3, 5, 6, 7}


def test_week_parser_filters_out_of_range_with_warning_source_payload():
    schedule = _resolve_schedule_weeks({"jxap": {"tm": [{"zs": "1,20,34,2025"}]}}, {})
    assert schedule["weeks"] == {1}
    assert schedule["out_of_range"] == [20, 34, 2025]
    assert "教学安排周次出现超过 19 的值" in schedule["warnings"][0]


def test_meta_week_fallback_requires_week_context_and_filters_noise():
    meta = {"full_text": "教学安排\n2025年政策说明，期末考试60分。周次：一至三。第十四周复习　"}
    schedule = _resolve_schedule_weeks({"jxap": {"tm": []}}, meta)
    assert schedule["weeks"] == {1, 2, 3, 14}
    assert 2025 not in schedule["out_of_range"]
    assert 60 not in schedule["out_of_range"]


def test_schedule_weeks_reads_jxap_apgs_when_rows_are_empty():
    payload = {
        "jcxx": {"skzs": "9"},
        "jxap": {
            "tm": [],
            "apgs": "周次 主要教学方法与主要知识点 1 导论 教学方法:讲授 2-3 第一章 教学方法:讲授 4 第二章 教学方法:讲授 5 第三章 教学方法:讲授 6 第四章 教学方法:讲授 7 第五章 教学方法:讲授 8 第六七章 教学方法:讲授 9 考试",
        },
    }
    schedule = _resolve_schedule_weeks(payload, {})
    assert schedule["source"] == "payload"
    assert schedule["weeks"] == set(range(1, 10))
    assert {item["source_path"] for item in schedule["sources"]} == {"payload.jxap.apgs"}


def test_schedule_week_audit_only_requires_max_week_match():
    subject = AuditSubject(
        extraction_id=1,
        course_code="K1",
        source_path="demo.pdf",
        payload={
            "jcxx": {"skzs": "9"},
            "jxap": {"tm": [{"zs": "1"}, {"zs": "9"}]},
        },
        meta={},
    )
    match = CourseMatch(status="not_found", method="not_found", course_row={})
    audit = audit_subject(subject, match)
    finding = next(item for item in audit.section_findings if item.wd == JXAPZC_WD)
    assert finding.status == "pass"
    assert finding.evidence["max_week"] == 9
    assert finding.evidence["missing_weeks"] == [2, 3, 4, 5, 6, 7, 8]


def test_reason_cleaner_replaces_internal_names():
    reason = clean_customer_reason("payload.kcmb.szmb为空，jxap未体现，khfsb缺失")
    assert "payload" not in reason
    assert "szmb" not in reason
    assert "jxap" not in reason
    assert "khfsb" not in reason
    assert "思政目标" in reason
    assert "教学安排" in reason
    assert "考核方式" in reason
    meta_reason = clean_customer_reason("meta 中仅发现章节标题")
    assert "meta" not in meta_reason
    assert "原文辅助信息" in meta_reason


def test_template_basic_info_uses_distinct_section():
    findings = _basic_info_findings({"jcxx": {"zwkcmc": "课程A", "ywkcmc": "Course A"}}, {})
    name_sections = {item.section for item in findings if item.field in {"zwkcmc", "ywkcmc"}}
    assert name_sections == {"jcxx_template"}
