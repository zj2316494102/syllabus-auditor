"""质量报告中教学安掀思政字段统计的单元测试。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from syllabus_auditor.application.report.quality import (  # noqa: E402
    payload_section_ok,
    section_present,
)
class JxapSzReportTests(unittest.TestCase):
    def test_loose_keyword_no_longer_counts_as_jxap_sz(self) -> None:
        text = "教学安排\n第一周内容\n思政：这是叙述体思政内容"
        self.assertTrue(section_present(text, "jxap"))
        self.assertFalse(section_present(text, "jxap_sz"))
    def test_payload_requires_structured_szyqjxx(self) -> None:
        narrative = {"jxap": {"tm": [], "apgs": "思政：叙述体内容"}}
        structured = {"jxap": {"tm": [{"zs": "1", "sknr": "a", "skfs": "b", "szyqjxx": "家国情怀"}], "apgs": ""}}
        self.assertFalse(payload_section_ok(narrative, "jxap_sz"))
        self.assertTrue(payload_section_ok(structured, "jxap_sz"))
if __name__ == "__main__":
    unittest.main()
