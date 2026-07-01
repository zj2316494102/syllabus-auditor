"""MinerU 考核方式表抽取来源的单元测试。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.core.extractors.mineru.process import build_extraction_raw
class MineruKhfsbSourceTests(unittest.TestCase):
    def test_basic_info_khfs_does_not_pollute_khfsb_khgs(self) -> None:
        raw = build_extraction_raw(
            full_text="\n".join(
                [
                    "一、课程基本信息",
                    "课程编号 X1",
                    "考核方式",
                    "课程论文",
                    "二、课程学时安排",
                    "周学时3",
                    "三、任课教师信息",
                    "任课教师姓名 张三",
                    "四、课程教学信息",
                    "课程目标",
                    "掌握基本理论　",
                ]
            ),
            tables=[],
            source_path=Path("sample.pdf"),
            page_count=1,
            selected_source="mineru_md",
        )
        self.assertEqual(raw.cn_data["考核方式说明"], "")
        self.assertEqual(raw.section_extraction["khfsb_format"], "text")
    def test_real_assessment_section_remains_khgs_when_not_structured(self) -> None:
        raw = build_extraction_raw(
            full_text="\n".join(
                [
                    "课程目标",
                    "掌握基本理论　",
                    "教学安排",
                    "按周授课　",
                    "（八）考核方式及成绩构成",
                    "课堂闭卷0%",
                    "平时作业0%",
                    "阅读材料",
                    "教材 A",
                ]
            ),
            tables=[],
            source_path=Path("sample.pdf"),
            page_count=1,
            selected_source="mineru_md",
        )
        self.assertEqual(raw.cn_data["考核方式说明"], "课堂闭卷0%\n平时作业0%")
        self.assertEqual(raw.assessment_rows, [])
        self.assertEqual(raw.section_extraction["khfsb_format"], "text")
    def test_assessment_table_rows_clear_khgs(self) -> None:
        raw = build_extraction_raw(
            full_text="\n".join(
                [
                    "课程目标",
                    "掌握基本理论　",
                    "（八）考核方式",
                    "这段说明不应与表格同时进兀khgs　",
                ]
            ),
            tables=[
                [
                    ["考试形式", "考察内容", "考察方式", "占比"],
                    ["期末考试", "课程内容", "闭卷", "60%"],
                ]
            ],
            source_path=Path("sample.pdf"),
            page_count=1,
            selected_source="mineru_md",
        )
        self.assertEqual(raw.cn_data["考核方式说明"], "")
        self.assertEqual(len(raw.assessment_rows), 1)
        self.assertEqual(raw.section_extraction["khfsb_format"], "table")
if __name__ == "__main__":
    unittest.main()
