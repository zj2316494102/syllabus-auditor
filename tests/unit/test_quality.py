"""入库前质量检查与告警生成的单元测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert
from syllabus_auditor.core.status import judge_extraction_status
from syllabus_auditor.core.types import ExtractionRaw


class QualityTests(unittest.TestCase):
    def test_nested_control_chars_are_removed_and_warned(self) -> None:
        payload = {
            "jcxx": {"kcbh": "A\x00B", "zwkcmc": "课程"},
            "kcmb": {"szmb": "x", "nlmb": "y", "zsmb": "z", "mbgs": ""},
            "jxnr": {"tm": [{"xh": "1", "zt": "a", "zsd": "b\x00c", "xs": "2"}], "nrgs": ""},
            "jxap": {"tm": [{"zs": "1", "sknr": "a", "skfs": "b", "szyqjxx": "c"}], "apgs": ""},
            "kcyq": "要求",
            "kcyqb": {"tm": [], "yqgs": "", "kzzd": []},
            "khfsb": {"tm": [{"ksxs": "a", "kcnr": "b", "kcfs": "c", "zb": "100%"}], "khgs": ""},
        }
        meta = {"extraction_warnings": [], "raw_pages": ["hello\x00world"]}
        cleaned_payload, cleaned_meta = prepare_payload_and_meta_for_insert(payload, meta)
        self.assertEqual(cleaned_payload["jcxx"]["kcbh"], "AB")
        self.assertEqual(cleaned_payload["jxnr"]["tm"][0]["zsd"], "bc")
        self.assertEqual(cleaned_meta["raw_pages"][0], "helloworld")
        reasons = [warning["reason"] for warning in cleaned_meta["extraction_warnings"]]
        self.assertIn("sanitized_control_chars", reasons)
        self.assertEqual(judge_extraction_status(cleaned_payload, cleaned_meta), "partial")

    def test_missing_course_code_is_partial_not_failed(self) -> None:
        payload = {
            "jcxx": {"kcbh": "", "zwkcmc": "课程"},
            "kcmb": {"szmb": "x", "nlmb": "y", "zsmb": "z", "mbgs": ""},
            "jxnr": {"tm": [{"xh": "1", "zt": "a", "zsd": "b", "xs": "2"}], "nrgs": ""},
            "jxap": {"tm": [{"zs": "1", "sknr": "a", "skfs": "b", "szyqjxx": "c"}], "apgs": ""},
            "kcyq": "要求",
            "kcyqb": {"tm": [], "yqgs": "", "kzzd": []},
            "khfsb": {"tm": [{"ksxs": "a", "kcnr": "b", "kcfs": "c", "zb": "100%"}], "khgs": ""},
        }
        payload, meta = prepare_payload_and_meta_for_insert(payload, {"extraction_warnings": []})
        self.assertEqual(payload["jcxx"]["kcbh"], "")
        self.assertEqual(judge_extraction_status(payload, meta), "partial")
        self.assertTrue(
            any(
                warning["section"] == "jcxx"
                and warning["field"] == "kcbh"
                and warning["reason"] == "missing_field"
                for warning in meta["extraction_warnings"]
            )
        )

    def test_placeholder_and_invalid_course_code_are_blank(self) -> None:
        for raw_code in ("不填", "运动技术专项（游泳", "2026 - 附件3课程实施方案"):
            payload = build_payload(
                ExtractionRaw(
                    cn_data={"课程编号": raw_code, "中文课程名称": "测试课"},
                    full_text="",
                    raw_pages=[],
                    page_count=1,
                )
            )
            self.assertNotIn("kcbh", payload["jcxx"])

    def test_missing_row_fields_are_warnings(self) -> None:
        payload = {
            "jcxx": {"kcbh": "X", "zwkcmc": "课程"},
            "kcmb": {"szmb": "x", "nlmb": "y", "zsmb": "z", "mbgs": ""},
            "jxnr": {"tm": [{"xh": "1", "zt": "a", "zsd": "b", "xs": "2"}], "nrgs": ""},
            "jxap": {"tm": [{"zs": "1", "sknr": "a", "skfs": "b", "szyqjxx": ""}], "apgs": ""},
            "kcyq": "要求",
            "kcyqb": {"tm": [], "yqgs": "", "kzzd": []},
            "khfsb": {"tm": [{"ksxs": "a", "kcnr": "b", "kcfs": "c", "zb": ""}], "khgs": ""},
        }
        payload, meta = prepare_payload_and_meta_for_insert(payload, {"extraction_warnings": []})
        missing = {(warning["section"], warning["field"]) for warning in meta["extraction_warnings"]}
        self.assertIn(("jxap", "szyqjxx"), missing)
        self.assertIn(("khfsb", "zb"), missing)
        self.assertEqual(judge_extraction_status(payload, meta), "partial")


if __name__ == "__main__":
    unittest.main()
