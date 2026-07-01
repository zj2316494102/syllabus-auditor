"""章节表格解析器的单元测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from syllabus_auditor.core.extractors.section_table_parser import parse_section_tables
from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.core.types import ExtractionRaw


class SectionTableParserTests(unittest.TestCase):
    def test_schedule_extra_homework_and_cross_page_rows(self) -> None:
        tables = [
            [
                ["课程", "讲授内容", "授课方式", "作业", "思政元素的融入和预期教学成效"],
                ["1", "UNIT 1\n1. 语言", "讲授\n课外阅读", "微信群", "思政一"],
            ],
            [
                ["", "2. 语形", "", "", ""],
                ["2", "UNIT 2", "讲授\n课外阅读", "微信群", "思政二"],
            ],
        ]
        parsed = parse_section_tables(tables)
        raw = ExtractionRaw(
            cn_data={"课程编号": "X1", "中文课程名称": "测试课"},
            full_text="",
            raw_pages=[],
            page_count=2,
            course_schedule=parsed["course_schedule"],
            extraction_warnings=parsed["warnings"],
        )
        payload = build_payload(raw)
        rows = payload["jxap"]["tm"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["zs"], "1")
        self.assertIn("2. 语形", rows[0]["sknr"])
        self.assertEqual(rows[0]["kzzd"], [{"bt": "作业", "nr": "微信群"}])
        self.assertNotIn("zy", rows[0])
        self.assertEqual(rows[0]["szyqjxx"], "思政一")
        self.assertEqual(rows[1]["zs"], "2")
        self.assertEqual(rows[1]["szyqjxx"], "思政二")

    def test_unknown_columns_are_not_chinese_payload_keys(self) -> None:
        tables = [
            [
                ["序号", "主题", "知识点", "学时", "重点难点"],
                ["1", "主题一", "知识点一", "2", "难点一"],
            ]
        ]
        parsed = parse_section_tables(tables)
        raw = ExtractionRaw(
            cn_data={"课程编号": "X1", "中文课程名称": "测试课"},
            full_text="",
            raw_pages=[],
            page_count=1,
            teaching_content=parsed["teaching_content"],
            extraction_warnings=parsed["warnings"],
        )
        payload = build_payload(raw)
        item = payload["jxnr"]["tm"][0]
        self.assertEqual(item["xh"], "1")
        self.assertEqual(item["zt"], "主题一")
        self.assertEqual(item["kzzd"], [{"bt": "重点难点", "nr": "难点一"}])
        self.assertNotIn("重点难点", item)

    def test_assessment_extra_column_is_preserved_as_list(self) -> None:
        tables = [
            [
                ["考试形式", "考察内容", "考察方式", "占比", "备注"],
                ["平时成绩", "课堂表现", "课堂参与", "20%", "含签到"],
            ]
        ]
        parsed = parse_section_tables(tables)
        raw = ExtractionRaw(
            cn_data={"课程编号": "X1", "中文课程名称": "测试课"},
            full_text="",
            raw_pages=[],
            page_count=1,
            assessment_rows=parsed["assessment_rows"],
        )
        payload = build_payload(raw)
        item = payload["khfsb"]["tm"][0]
        self.assertEqual(item["ksxs"], "平时成绩")
        self.assertEqual(item["kzzd"], [{"bt": "备注", "nr": "含签到"}])
        self.assertNotIn("备注", item)

    def test_content_summary_fragments_do_not_pollute_last_item(self) -> None:
        tables = [
            [
                ["序号", "主题", "知识点", "学时"],
                ["5\n课时总计8学时", "开卷考试", "命题逻辑理论\n38（课程教授与实践）", "3"],
            ]
        ]
        parsed = parse_section_tables(tables)
        raw = ExtractionRaw(
            cn_data={"课程编号": "X1", "中文课程名称": "测试课"},
            full_text="课时总计8学时",
            raw_pages=[],
            page_count=1,
            teaching_content=parsed["teaching_content"],
            section_extraction={"content_total_hours": parsed.get("content_total_hours", "")},
        )
        payload = build_payload(raw)
        item = payload["jxnr"]["tm"][0]
        self.assertEqual(item["xh"], "5")
        self.assertEqual(item["zsd"], "命题逻辑理论")
        self.assertEqual(item["xs"], "3")
        self.assertEqual(payload["jxnr"]["zongxs"], "38")
        self.assertNotIn("课时总计", item["xh"])
        self.assertNotIn("38（课程教授与实践）", item["zsd"])



    def test_content_summary_total_row_sets_jxnr_total_hours(self) -> None:
        tables = [
            [
                ["序号", "主题", "知识点", "学时"],
                ["1", "公司治理", "剩余控制权与剩余索取权", "6"],
                ["2", "公司资本结构", "MM 定理", "9"],
                ["课时总计：学时", "", "", "15"],
            ]
        ]
        parsed = parse_section_tables(tables)
        raw = ExtractionRaw(
            cn_data={"课程编号": "X1", "中文课程名称": "测试课"},
            full_text="",
            raw_pages=[],
            page_count=1,
            teaching_content=parsed["teaching_content"],
            section_extraction={"content_total_hours": parsed.get("content_total_hours", "")},
        )
        payload = build_payload(raw)
        self.assertEqual(payload["jxnr"]["zongxs"], "15")
        self.assertEqual(len(payload["jxnr"]["tm"]), 2)

    def test_content_total_hours_falls_back_to_item_hour_sum(self) -> None:
        raw = ExtractionRaw(
            cn_data={"课程编号": "X1", "中文课程名称": "测试课"},
            full_text="",
            raw_pages=[],
            page_count=1,
            teaching_content=[
                {"序号": "1", "主题": "公司治理", "知识点": "知识点一", "学时": "6"},
                {"序号": "2", "主题": "资本结构", "知识点": "知识点二", "学时": "9"},
            ],
        )
        payload = build_payload(raw)
        self.assertEqual(payload["jxnr"]["zongxs"], "15")

    def test_content_total_hours_falls_back_to_explicit_prose_total(self) -> None:
        raw = ExtractionRaw(
            cn_data={
                "课程编号": "X1",
                "中文课程名称": "测试课",
                "教学内容概述": "本课程包括公司治理、资本结构与案例分析，以上内容共 57 学时。",
            },
            full_text="",
            raw_pages=[],
            page_count=1,
        )
        payload = build_payload(raw)
        self.assertEqual(payload["jxnr"]["zongxs"], "57")

    def test_content_total_hours_does_not_use_isolated_prose_hours(self) -> None:
        raw = ExtractionRaw(
            cn_data={
                "课程编号": "X1",
                "中文课程名称": "测试课",
                "教学内容概述": "专题一安排 57 学时相关案例阅读。",
            },
            full_text="",
            raw_pages=[],
            page_count=1,
        )
        payload = build_payload(raw)
        self.assertEqual(payload["jxnr"]["zongxs"], "")
if __name__ == "__main__":
    unittest.main()

