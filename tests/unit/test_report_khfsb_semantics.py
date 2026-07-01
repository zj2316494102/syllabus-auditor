"""考核方式表语义判定的单元测试。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from syllabus_auditor.application.report.quality import md_section_ok, mineru_section_ok, section_present
from syllabus_auditor.core.types import ExtractionRaw
def test_khfsb_section_present_rejects_basic_info_label() -> None:
    text = "\n".join(
        [
            "一、课程基本信息",
            "考核方式",
            "课程论文",
            "二、课程学时安排",
            "周学时3",
            "课程目标",
            "掌握基本理论　",
        ]
    )
    assert section_present(text, "khfsb") is False
def test_khfsb_section_present_accepts_real_section() -> None:
    text = "\n".join(
        [
            "课程目标",
            "掌握基本理论　",
            "教学安排",
            "按周授课　",
            "（八）考核方式及成绩构成",
            "课堂闭卷0%",
            "平时作业0%",
        ]
    )
    assert section_present(text, "khfsb") is True
def test_mineru_section_ok_rejects_basic_info_khfs_only() -> None:
    raw = ExtractionRaw(
        cn_data={"考核方式": "课程论文", "考核方式说明": ""},
        full_text="考核方式\n课程论文\n二、课程学时安排",
        raw_pages=[],
        page_count=1,
    )
    assert mineru_section_ok(raw, "khfsb") is False
def test_md_section_ok_uses_mineru_khfsb_semantics() -> None:
    root = Path(__file__).resolve().parents[2]
    base = root / ".pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        tmp_path = Path(tmp)
        basic = tmp_path / "basic.md"
        basic.write_text(
            "\n".join(
                [
                    "一、课程基本信息",
                    "考核方式",
                    "课程论文",
                    "二、课程学时安排",
                    "周学时3",
                ]
            ),
            encoding="utf-8",
        )
        real = tmp_path / "real.md"
        real.write_text(
            "\n".join(
                [
                    "课程目标",
                    "掌握基本理论　",
                    "（八）考核方式及成绩构成",
                    "课堂闭卷0%",
                    "平时作业0%",
                ]
            ),
            encoding="utf-8",
        )
        assert md_section_ok(basic, "khfsb") is False
        assert md_section_ok(real, "khfsb") is True
