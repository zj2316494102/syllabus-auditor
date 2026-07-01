"""考核方式行归一化逻辑的单元测试。"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from syllabus_auditor.core.extractors.section_table_parser import normalize_assessment_rows
def test_percent_values_stay_in_ratio() -> None:
    rows = normalize_assessment_rows(
        [
            {"考试形式": "平时", "占比": "30%"},
            {"考试形式": "期末", "占比": "70%"},
        ]
    )
    assert rows[0]["占比"] == "30%"
    assert rows[1]["占比"] == "70%"
    assert "分数" not in rows[0]
def test_score_values_compute_ratio() -> None:
    rows = normalize_assessment_rows(
        [
            {"考试形式": "平时成绩", "考察内容": "作业", "分数": "10"},
            {"考试形式": "期末", "考察内容": "考试", "分数": "40"},
            {"考试形式": "论文", "考察内容": "报告", "分数": "50"},
        ]
    )
    assert rows[0]["分值"] == "10"
    assert rows[0]["占比"] == "10%"
    assert rows[2]["占比"] == "50%"
def test_ratio_column_without_percent_sign() -> None:
    rows = normalize_assessment_rows(
        [
            {"考试形式": "平时", "占比": "30"},
            {"考试形式": "期末", "占比": "70"},
        ]
    )
    assert rows[0]["占比"] == "30%"
    assert rows[1]["占比"] == "70%"
if __name__ == "__main__":
    test_percent_values_stay_in_ratio()
    test_score_values_compute_ratio()
    test_ratio_column_without_percent_sign()
    print("ok")
