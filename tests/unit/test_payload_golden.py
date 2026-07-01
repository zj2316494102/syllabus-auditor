"""payload 构建与 schema 版本的单元测试。"""
from __future__ import annotations

from syllabus_auditor.core.meta_builder import build_meta
from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.core.types import ExtractionRaw
from syllabus_auditor.shared.config import PAYLOAD_SCHEMA_VERSION


def test_payload_schema_version_constant() -> None:
    assert PAYLOAD_SCHEMA_VERSION == "1.0"


def test_build_payload_golden_minimal() -> None:
    raw = ExtractionRaw(
        cn_data={
            "课程编号": "TEST101",
            "中文课程名称": "测试课程",
            "总学时": "32",
        },
        full_text="课程编号 TEST101",
        raw_pages=["课程编号 TEST101"],
        page_count=1,
        teaching_content=[{"序号": "1", "主题": "导论", "知识点": "简介", "学时": "2"}],
        course_schedule=[{"序号": "1", "授课内容": "导论", "授课方式": "讲授"}],
        assessment_rows=[{"考试形式": "平时", "占比": "100%"}],
    )
    payload = build_payload(raw)
    meta = build_meta(raw, "data_pdf/test.pdf")
    assert payload["jcxx"]["kcbh"] == "TEST101"
    assert payload["jcxx"]["zwkcmc"] == "测试课程"
    assert len(payload["jxnr"]["tm"]) == 1
    assert meta["payload_schema_version"] == PAYLOAD_SCHEMA_VERSION
