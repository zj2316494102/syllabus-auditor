"""\u8bfe\u7a0b\u5e93\u6bd4\u5bf9\u3001\u5b66\u65f6\u4e0e\u5468\u6b21\u89c4\u5219\u5ba1\u6838\u5355\u5143\u6d4b\u8bd5\u3002"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from syllabus_auditor.core.audit import (
    KCJBXX_WD,
    JXAPZC_WD,
    JXNRXS_WD,
    NO,
    YES,
    AuditSubject,
    CourseMatch,
    audit_subject,
    build_subject_key,
    extract_course_name_from_source_path,
)
from syllabus_auditor.core.db.audit import AuditStore


def course_row() -> dict:
    return {
        "kcbh": "ABC123",
        "kkyx": "\u8ba1\u7b97\u673a\u5b66\u9662",
        "zwkcmc": "\u6d4b\u8bd5\u8bfe\u7a0b",
        "ywkcmc": "Test Course",
        "skyy": "\u4e2d\u6587",
        "yxwxyxk": "\u662f",
        "khfs": "\u8003\u8bd5",
        "kcxz": "\u5fc5\u4fee",
        "kclb": "\u4e13\u4e1a\u8bfe",
        "zxs": "2",
        "skzs": "19",
        "zongxs": "38",
        "jxxs": "38",
        "syxs": "0",
        "sjxs": "0",
        "qtxs": "0",
        "zxxs": "0",
        "kcxf": "2",
        "zjjsxm": "\u5f20\u4e09",
    }


def complete_payload() -> dict:
    return {
        "jcxx": {
            "kcbh": "ABC123",
            "kkyx": "\u8ba1\u7b97\u673a\u5b66\u9662",
            "zwkcmc": "\u6d4b\u8bd5\u8bfe\u7a0b",
            "ywkcmc": "Test Course",
            "skyy": "\u4e2d\u6587",
            "sfyxwxyxk": "\u662f",
            "khfs": "\u8003\u8bd5",
            "kcxz": "\u5fc5\u4fee",
            "kclb": "\u4e13\u4e1a\u8bfe",
            "zxs": "2",
            "skzs": "19",
            "zongxs": "38",
            "jxxs": "38",
            "syxs": "0",
            "sjxs": "0",
            "qtxs": "0",
            "zxxs": "0",
            "kcxf": "2",
            "rkjsxm": "\u5f20\u4e09",
            "jsgh": "T001",
            "email": "teacher@example.com",
            "lxdh": "123456",
        },
        "kczwjj": "\u4e2d\u6587\u7b80\u4ecb",
        "kcywjj": "English intro",
        "ybzsyq": "\u9884\u5907\u77e5\u8bc6",
        "jcjydcl": "\u6559\u6750",
        "kcmb": {"szmb": "\u601d\u653f", "nlmb": "\u80fd\u529b", "zsmb": "\u77e5\u8bc6", "mbgs": ""},
        "jxnr": {
            "tm": [
                {"xh": "1", "zt": "\u4e3b\u9898\u4e00", "zsd": "\u77e5\u8bc6\u70b9\u4e00", "xs": "20"},
                {"xh": "2", "zt": "\u4e3b\u9898\u4e8c", "zsd": "\u77e5\u8bc6\u70b9\u4e8c", "xs": "18"},
            ],
            "zongxs": "38",
            "nrgs": "",
        },
        "jxap": {
            "tm": [{"zs": "1-19", "sknr": "\u5185\u5bb9", "skfs": "\u6388\u8bb2", "szyqjxx": "\u601d\u653f"}],
            "apgs": "",
        },
        "kcyq": "\u8bfe\u7a0b\u8981\u6c42",
        "kcyqb": {"tm": [], "yqgs": "", "kzzd": []},
        "khfsb": {
            "tm": [{"ksxs": "\u8003\u8bd5", "kcnr": "\u5185\u5bb9", "kcfs": "\u95ed\u5377", "zb": "100%", "fz": "100"}],
            "khgs": "",
        },
    }


def subject(payload: dict | None = None) -> AuditSubject:
    return AuditSubject(
        extraction_id=1,
        course_code="ABC123",
        source_path="data/\u8bfe\u7a0b\u65b9\u6848/\u6d4b\u8bd5\u8bfe\u7a0b.pdf",
        payload=payload or complete_payload(),
        meta={},
        extraction_status="success",
    )


def matched_course(row: dict | None = None, method: str = "matched_by_kcbh") -> CourseMatch:
    return CourseMatch(status="matched", method=method, query="ABC123", course_row=row or course_row())


class AuditTests(unittest.TestCase):
    def test_subject_key_uses_extraction_when_course_code_missing(self) -> None:
        self.assertEqual(
            build_subject_key(extraction_id=12, course_code="", source_path="a/b.pdf"),
            "extraction:12",
        )

    def test_source_path_course_name_extraction(self) -> None:
        self.assertEqual(
            extract_course_name_from_source_path(
                "data/\u8bfe\u7a0b\u65b9\u6848\u5b8c\u6574\u7248/\u8ba1\u7b97\u673a\u7a0b\u5e8f\u8bbe\u8ba1\u57fa\u7840.pdf"
            ),
            "\u8ba1\u7b97\u673a\u7a0b\u5e8f\u8bbe\u8ba1\u57fa\u7840",
        )

    def test_complete_basic_info_dimension_passes_with_yes(self) -> None:
        result = audit_subject(subject(), matched_course())
        finding = [item for item in result.section_findings if item.wd == KCJBXX_WD][0]
        hours_finding = [item for item in result.section_findings if item.wd == JXNRXS_WD][0]
        self.assertEqual(finding.status, "pass")
        self.assertEqual(finding.message, YES)
        self.assertEqual(finding.details["result"], YES)
        self.assertEqual(hours_finding.status, "pass")
        self.assertEqual(hours_finding.message, YES)
        self.assertEqual(result.summary["sections"][JXNRXS_WD], "pass")
        self.assertEqual(result.overall_status, "pass")

    def test_basic_numeric_fields_compare_by_value(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["kcxf"] = "3"
        row = course_row()
        row["kcxf"] = "3.0"
        result = audit_subject(subject(payload), matched_course(row))
        finding = [item for item in result.section_findings if item.wd == KCJBXX_WD][0]
        failed_kcxf = [
            item
            for item in result.field_findings
            if item.section == "jcxx" and item.field == "kcxf" and item.status == "fail"
        ]
        self.assertEqual(finding.status, "pass")
        self.assertEqual(failed_kcxf, [])

    def test_basic_info_dimension_keeps_all_failure_reasons(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["kcbh"] = ""
        payload["jcxx"]["email"] = ""
        payload["jcxx"]["lxdh"] = ""
        result = audit_subject(subject(payload), matched_course())
        finding = [item for item in result.section_findings if item.wd == KCJBXX_WD][0]
        reasons = finding.details["reasons"]
        self.assertIn("\u8bfe\u7a0b\u7f16\u53f7\u4e3a\u7a7a", reasons)
        self.assertIn("E-mail\u4e3a\u7a7a", reasons)
        self.assertIn("\u8054\u7cfb\u7535\u8bdd\u4e3a\u7a7a", reasons)

    def test_teaching_content_hours_dimension_fails_when_total_mismatch(self) -> None:
        payload = complete_payload()
        payload["jxnr"]["zongxs"] = "21"
        result = audit_subject(subject(payload), matched_course())
        finding = [item for item in result.section_findings if item.wd == JXNRXS_WD][0]
        field = [
            item
            for item in result.field_findings
            if item.section == "jxnr" and item.field == "zongxs" and "\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6" in item.reason
        ][0]
        self.assertEqual(finding.message, NO)
        self.assertIn("\u57fa\u7840\u4fe1\u606f\u4e3a 38\uff0c\u6559\u5b66\u5185\u5bb9\u4e3a 21", field.reason)

    def test_teaching_content_hours_dimension_fails_when_basic_total_missing(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["zongxs"] = ""
        result = audit_subject(subject(payload), matched_course())
        finding = [item for item in result.section_findings if item.wd == JXNRXS_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertIn("\u57fa\u7840\u4fe1\u606f\u603b\u5b66\u65f6\u4e3a\u7a7a", finding.details["reasons"])

    def test_teaching_content_hours_dimension_fails_when_content_total_missing(self) -> None:
        payload = complete_payload()
        payload["jxnr"]["zongxs"] = ""
        result = audit_subject(subject(payload), matched_course())
        finding = [item for item in result.section_findings if item.wd == JXNRXS_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertIn("\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6\u4e3a\u7a7a", finding.details["reasons"])

    def test_teaching_content_hours_dimension_fails_when_total_not_number(self) -> None:
        payload = complete_payload()
        payload["jxnr"]["zongxs"] = "\u4e09\u5341\u516b"
        result = audit_subject(subject(payload), matched_course())
        finding = [item for item in result.section_findings if item.wd == JXNRXS_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertIn("\u6559\u5b66\u5185\u5bb9\u603b\u5b66\u65f6\u4e0d\u662f\u53ef\u8ba1\u7b97\u6570\u5b57", finding.details["reasons"][0])

    def test_teaching_content_hours_uses_basic_meta_fallback(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["zongxs"] = ""
        item = subject(payload)
        item.meta = {
            "raw_pages": [
                {"text": "\u8bfe\u7a0b\u57fa\u672c\u4fe1\u606f\n\u603b\u5b66\u65f638\n\u5176\u4ed6\u4fe1\u606f"}
            ]
        }
        result = audit_subject(item, matched_course())
        finding = [section for section in result.section_findings if section.wd == JXNRXS_WD][0]
        self.assertEqual(finding.message, YES)
        self.assertTrue(finding.evidence["fallback_used"])

    def test_teaching_content_hours_uses_content_meta_fallback(self) -> None:
        payload = complete_payload()
        payload["jxnr"]["zongxs"] = ""
        item = subject(payload)
        item.meta = {
            "raw_pages": [
                {
                    "text": "\u6559\u5b66\u5185\u5bb9\n\u4e3b\u9898 20 \u5b66\u65f6\n\u4e3b\u9898 18 \u5b66\u65f6\n\u5408\u8ba1 38 \u5b66\u65f6"
                }
            ]
        }
        result = audit_subject(item, matched_course())
        finding = [section for section in result.section_findings if section.wd == JXNRXS_WD][0]
        self.assertEqual(finding.message, YES)
        self.assertTrue(finding.evidence["fallback_used"])

    def test_teaching_content_hours_rejects_ambiguous_meta_total(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["zongxs"] = ""
        payload["jxnr"]["zongxs"] = ""
        item = subject(payload)
        item.meta = {"raw_pages": [{"text": "\u603b\u5b66\u65f638"}]}
        result = audit_subject(item, matched_course())
        finding = [section for section in result.section_findings if section.wd == JXNRXS_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertTrue(
            any(
                "\u603b\u5b66\u65f6" in reason and "\u4e0d\u80fd\u786e\u8ba4" in reason
                for reason in finding.details["reasons"]
            )
        )

    def test_schedule_weeks_dimension_passes_when_continuous(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = "9"
        payload["jxap"]["tm"] = [
            {"zs": "1", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
            {"zs": "2", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
            {"zs": "3-5", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
            {"zs": "6-9", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
        ]
        result = audit_subject(subject(payload), matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, YES)

    def test_schedule_weeks_dimension_passes_when_max_week_matches_even_if_missing_week(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = "9"
        payload["jxap"]["tm"] = [
            {"zs": "1-3", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
            {"zs": "5-9", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
        ]
        result = audit_subject(subject(payload), matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, YES)
        self.assertEqual(finding.evidence["max_week"], 9)
        self.assertEqual(finding.evidence["missing_weeks"], [4])

    def test_schedule_weeks_dimension_passes_when_max_week_matches_even_if_duplicate_week(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = "9"
        payload["jxap"]["tm"] = [
            {"zs": "1-5", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
            {"zs": "5-9", "sknr": "a", "skfs": "a", "szyqjxx": "a"},
        ]
        result = audit_subject(subject(payload), matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, YES)
        self.assertEqual(finding.evidence["max_week"], 9)
        self.assertEqual(finding.evidence["duplicate_weeks"], [5])

    def test_schedule_weeks_dimension_fails_when_max_week_mismatch(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = "9"
        payload["jxap"]["tm"] = [{"zs": "1-8", "sknr": "a", "skfs": "a", "szyqjxx": "a"}]
        result = audit_subject(subject(payload), matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertIn(
            "\u6559\u5b66\u5b89\u6392\u6700\u5927\u5468\u6b21\u4e3a 8\uff0c\u57fa\u7840\u4fe1\u606f\u4e0a\u8bfe\u5468\u6570\u4e3a 9",
            finding.details["reasons"],
        )

    def test_schedule_weeks_uses_basic_meta_fallback_for_class_weeks(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = ""
        payload["jxap"]["tm"] = [{"zs": "1-9", "sknr": "a", "skfs": "a", "szyqjxx": "a"}]
        item = subject(payload)
        item.meta = {
            "raw_pages": [
                {"text": "\u8bfe\u7a0b\u57fa\u672c\u4fe1\u606f\n\u4e0a\u8bfe\u5468\u6570 9\n\u5176\u4ed6\u4fe1\u606f"}
            ]
        }
        result = audit_subject(item, matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, YES)
        self.assertTrue(finding.evidence["fallback_used"])

    def test_schedule_weeks_uses_schedule_meta_fallback(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = "9"
        payload["jxap"]["tm"] = []
        item = subject(payload)
        item.meta = {"raw_pages": [{"text": "\u6559\u5b66\u5b89\u6392\n1\u5468-5\u5468-9\u5468"}]}
        result = audit_subject(item, matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, YES)
        self.assertTrue(finding.evidence["fallback_used"])

    def test_schedule_weeks_does_not_infer_schedule_from_basic_weeks(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["skzs"] = "9"
        payload["jxap"]["tm"] = []
        item = subject(payload)
        item.meta = {"raw_pages": [{"text": "\u8bfe\u7a0b\u57fa\u672c\u4fe1\u606f\n\u4e0a\u8bfe\u5468\u6570 9"}]}
        result = audit_subject(item, matched_course())
        finding = [section for section in result.section_findings if section.wd == JXAPZC_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertIn(
            "\u6559\u5b66\u5b89\u6392\u5468\u6b21\u4e3a\u7a7a\uff0c\u65e0\u6cd5\u5224\u65ad\u6700\u5927\u5468\u6b21\u662f\u5426\u5339\u914d",
            finding.details["reasons"],
        )

    def test_basic_info_mismatch_writes_chinese_reason(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["zongxs"] = "21"
        payload["jcxx"]["zxs"] = "3"
        payload["jcxx"]["skzs"] = "7"
        result = audit_subject(subject(payload), matched_course())
        finding = [item for item in result.section_findings if item.wd == KCJBXX_WD][0]
        target = [
            item
            for item in result.field_findings
            if item.section == "jcxx" and item.field == "zongxs" and item.status == "fail"
        ][0]
        self.assertEqual(finding.message, NO)
        self.assertIn("\u603b\u5b66\u65f6\u4e0e\u8bfe\u7a0b\u5e93\u4e0d\u4e00\u81f4\uff1a\u8bfe\u7a0b\u5e93\u4e3a", target.reason)
        self.assertIn("\u8bfe\u7a0b\u5e93\u4e3a 38", target.message)

    def test_total_hours_must_equal_week_hours_times_weeks(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["zongxs"] = "38"
        payload["jcxx"]["zxs"] = "3"
        payload["jcxx"]["skzs"] = "7"
        row = course_row()
        row["zxs"] = "3"
        row["skzs"] = "7"
        result = audit_subject(subject(payload), matched_course(row))
        target = [
            item
            for item in result.field_findings
            if item.section == "jcxx"
            and item.field == "zongxs"
            and item.status == "fail"
            and "\u603b\u5b66\u65f6\u4e0d\u7b49\u4e8e\u5468\u5b66\u65f6\u4e58\u4ee5\u4e0a\u8bfe\u5468\u6570" in item.reason
        ][0]
        self.assertIn("3", target.message)

    def test_experiment_practice_other_self_hours_are_not_audited(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["syxs"] = "PDF\u503c"
        payload["jcxx"]["sjxs"] = "PDF\u503c"
        payload["jcxx"]["qtxs"] = "PDF\u503c"
        payload["jcxx"]["zxxs"] = "PDF\u503c"
        row = course_row()
        row["syxs"] = "\u8bfe\u7a0b\u5e93\u503c"
        row["sjxs"] = "\u8bfe\u7a0b\u5e93\u503c"
        row["qtxs"] = "\u8bfe\u7a0b\u5e93\u503c"
        row["zxxs"] = "\u8bfe\u7a0b\u5e93\u503c"
        result = audit_subject(subject(payload), matched_course(row))
        audited_fields = {item.field for item in result.field_findings if item.section == "jcxx"}
        self.assertNotIn("syxs", audited_fields)
        self.assertNotIn("sjxs", audited_fields)
        self.assertNotIn("qtxs", audited_fields)
        self.assertNotIn("zxxs", audited_fields)

    def test_both_empty_does_not_pass(self) -> None:
        payload = complete_payload()
        row = course_row()
        payload["jcxx"]["ywkcmc"] = ""
        row["ywkcmc"] = ""
        result = audit_subject(subject(payload), matched_course(row))
        target = [
            item
            for item in result.field_findings
            if item.section == "jcxx" and item.field == "ywkcmc" and item.status == "fail"
        ][0]
        self.assertEqual(target.reason, "PDF \u548c\u8bfe\u7a0b\u5e93\u4e2d\u7684\u82f1\u6587\u8bfe\u7a0b\u540d\u79f0\u90fd\u4e3a\u7a7a")

    def test_required_teacher_contact_fields_are_pdf_only(self) -> None:
        payload = complete_payload()
        payload["jcxx"]["jsgh"] = ""
        result = audit_subject(subject(payload), matched_course())
        target = [
            item
            for item in result.field_findings
            if item.section == "jcxx" and item.field == "jsgh" and item.status == "fail"
        ][0]
        self.assertEqual(target.reason, "\u6559\u5e08\u5de5\u53f7\u4e3a\u7a7a")

    def test_missing_course_match_fails_dimension(self) -> None:
        match = CourseMatch(
            status="not_found",
            method="not_found",
            query="ABC123",
            reasons=["\u65e0\u6cd5\u5b9a\u4f4d\u8bfe\u7a0b\u5e93\u8bb0\u5f55"],
        )
        result = audit_subject(subject(), match)
        finding = [item for item in result.section_findings if item.wd == KCJBXX_WD][0]
        self.assertEqual(finding.message, NO)
        self.assertIn("\u65e0\u6cd5\u5b9a\u4f4d\u8bfe\u7a0b\u5e93\u8bb0\u5f55", finding.details["reasons"])

    def test_missing_field_extraction_warning_does_not_duplicate_required_failure(self) -> None:
        payload = complete_payload()
        payload["jcjydcl"] = ""
        item = subject(payload)
        item.meta = {
            "extraction_warnings": [
                {
                    "section": "payload",
                    "field": "jcjydcl",
                    "label": "\u6559\u6750\u53ca\u9605\u8bfb\u6750\u6599",
                    "reason": "missing_field",
                    "path": "payload.jcjydcl",
                },
                {"section": "ocr", "reason": "mineru_ocr_rerun_recommended"},
            ]
        }
        result = audit_subject(item, matched_course())
        jcjydcl_failures = [
            finding
            for finding in result.field_findings
            if finding.path == "payload.jcjydcl" and finding.status == "fail"
        ]
        warning_reasons = [
            finding.evidence.get("raw_reason")
            for finding in result.field_findings
            if finding.evidence.get("source") == "meta.extraction_warnings"
        ]
        self.assertEqual(len(jcjydcl_failures), 1)
        self.assertNotIn("missing_field", warning_reasons)
        self.assertIn("mineru_ocr_rerun_recommended", warning_reasons)

    def test_meta_warnings_are_chinese_auditable(self) -> None:
        item = subject()
        item.meta = {
            "extraction_warnings": [
                {
                    "section": "jxap",
                    "field": "sknr",
                    "reason": "unknown_columns",
                    "path": "payload.jxap.tm[0].kzzd",
                }
            ]
        }
        item.extraction_status = "partial"
        result = audit_subject(item, matched_course())
        self.assertEqual(result.overall_status, "partial")
        self.assertTrue(any("\u672a\u77e5\u5217" in finding.reason for finding in result.field_findings))


class InMemoryAuditStore(AuditStore):
    def __init__(self, *, by_kcbh: dict[str, dict], by_name: dict[str, list[dict]]) -> None:
        self.by_kcbh = by_kcbh
        self.by_name = by_name

    def get_course_by_kcbh(self, kcbh: str) -> dict | None:
        return self.by_kcbh.get(kcbh)

    def _match_course_by_name(self, name: str, *, method: str) -> CourseMatch:
        candidates = list(self.by_name.get(str(name or "").strip(), []))
        if len(candidates) == 1:
            return CourseMatch(status="matched", method=method, query=name, course_row=candidates[0], candidates=candidates)
        if len(candidates) > 1:
            return CourseMatch(status="ambiguous", method="ambiguous", query=name, candidates=candidates)
        return CourseMatch(status="not_found", method="not_found", query=name)


class CourseMatchingTests(unittest.TestCase):
    def test_subject_key_uses_extraction_even_when_course_code_exists(self) -> None:
        self.assertEqual(
            build_subject_key(extraction_id=12, course_code="ABC123", source_path="a/b.pdf"),
            "extraction:12",
        )

    def test_duplicate_kcbh_uses_pdf_name_for_course_row_but_keeps_original_kcbh(self) -> None:
        duplicate_row = course_row()
        duplicate_row["kcbh"] = "DUP"
        duplicate_row["zwkcmc"] = "Wrong Course"
        corrected_row = course_row()
        corrected_row["kcbh"] = "FIXED"
        corrected_row["zwkcmc"] = "Correct Course"
        store = InMemoryAuditStore(
            by_kcbh={"DUP": duplicate_row, "FIXED": corrected_row},
            by_name={"Correct Course": [corrected_row]},
        )
        payload = complete_payload()
        payload["jcxx"]["kcbh"] = "DUP"
        payload["jcxx"]["zwkcmc"] = "Correct Course"
        item = subject(payload)
        item.course_code = "DUP"
        match = store.match_course(item, duplicate_course_codes={"DUP"})
        result = audit_subject(item, match)
        self.assertEqual(match.method, "matched_by_pdf_name_for_duplicate_kcbh")
        self.assertEqual(result.summary["course_match"]["original_kcbh"], "DUP")
        self.assertEqual(result.summary["course_match"]["matched_kcbh"], "FIXED")
        self.assertTrue(result.summary["course_match"]["duplicate_kcbh_resolved"])
        kcbh_finding = [finding for finding in result.field_findings if finding.section == "jcxx" and finding.field == "kcbh"][0]
        name_finding = [finding for finding in result.field_findings if finding.section == "jcxx" and finding.field == "zwkcmc"][0]
        self.assertEqual(kcbh_finding.status, "fail")
        self.assertEqual(name_finding.status, "pass")

    def test_duplicate_kcbh_unresolved_falls_back_to_original_kcbh(self) -> None:
        duplicate_row = course_row()
        duplicate_row["kcbh"] = "DUP"
        store = InMemoryAuditStore(by_kcbh={"DUP": duplicate_row}, by_name={})
        payload = complete_payload()
        payload["jcxx"]["kcbh"] = "DUP"
        payload["jcxx"]["zwkcmc"] = "Unknown Course"
        item = subject(payload)
        item.course_code = "DUP"
        item.source_path = "Unknown File.pdf"
        match = store.match_course(item, duplicate_course_codes={"DUP"})
        self.assertEqual(match.method, "matched_by_kcbh_after_duplicate_unresolved")
        self.assertEqual(match.course_row["kcbh"], "DUP")
        self.assertFalse(match.metadata["duplicate_kcbh_resolved"])


if __name__ == "__main__":
    unittest.main()
