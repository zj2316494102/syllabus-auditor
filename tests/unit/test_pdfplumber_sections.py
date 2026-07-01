"""pdfplumber 章节抽取的单元测试。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.core.extractors.pdfplumber import parse_sections_from_text, parse_two_column_sections
class PdfPlumberSectionTests(unittest.TestCase):
    def test_assessment_section_ignores_inline_basic_info_label(self) -> None:
        data = {"课程要求": "", "阅读材料": "", "考核方式说明": ""}
        full_text = "\n".join(
            [
                "课程编号 001 考核方式 课程论文",
                "（六）课程要求",
                "按时提交作业　",
                "（七）阅读材料",
                "教材 A",
            ]
        )
        parse_sections_from_text(data, full_text)
        self.assertEqual(data["课程要求"], "按时提交作业")
        self.assertEqual(data["阅读材料"], "教材 A")
        self.assertEqual(data["考核方式说明"], "")
    def test_goal_label_can_appear_after_empty_leading_column(self) -> None:
        data = {"思政目标": "", "能力目标": "", "知识目标": ""}
        tables = [
            [
                ["", "思政目标", "价值塑造内容"],
                ["", "", "续写内容"],
            ]
        ]
        parse_two_column_sections(data, tables)
        self.assertEqual(data["思政目标"], "价值塑造内容\n续写内容")
if __name__ == "__main__":
    unittest.main()
