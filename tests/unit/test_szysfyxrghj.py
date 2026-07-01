"""思政融入 LLM 审核维度的单元测试。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.auditors.szysfyxrghj import (
    DIMENSION,
    FIELD,
    audit_szysfyxrghj,
    build_audit_input,
    _build_prompt,
    _normalize_llm_result as normalize_llm_result,
)
from syllabus_auditor.core.audit import AuditSubject
class FakeLlm:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []
    def complete_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text
    def metadata(self) -> dict[str, str]:
        return {"provider": "fake", "model": "fake-model"}
def subject(payload: dict | None = None, meta: dict | None = None) -> AuditSubject:
    return AuditSubject(
        extraction_id=1,
        course_code="ABC123",
        source_path="data/test.pdf",
        payload=payload or complete_payload(),
        meta=meta or {},
        extraction_status="success",
    )
def complete_payload() -> dict:
    return {
        "kcmb": {
            "szmb": "引导学生理解专业知识背后的社会责任和职业伦理，增强服务国家发展的责任感　",
            "mbgs": "",
            "kzzd": {},
        },
        "jxap": {
            "tm": [
                {
                    "zs": "1-2",
                    "sknr": "行业发展案例分析",
                    "skfs": "案例讨论",
                    "szyqjxx": "结合行业诚信案例，引导学生理解职业伦理和社会责任　",
                }
            ],
            "apgs": "",
        },
    }
class SzysfyxrghjTests(unittest.TestCase):
    def test_build_audit_input_uses_payload_and_related_meta(self) -> None:
        payload = complete_payload()
        payload["kcmb"]["szmb"] = ""
        payload["jxap"]["tm"][0]["szyqjxx"] = ""
        meta = {
            "extraction_warnings": [{"section": "kcmb", "field": "szmb", "reason": "missing_field"}],
            "raw_pages": [
                {
                    "text": "课程目标：落实立德树人，强化价值引领和社会责任。教学安排：案例讨论中融入诚信和职业道德　",
                }
            ],
        }
        audit_input = build_audit_input(payload, meta)
        self.assertEqual(audit_input["audit_subject"]["dimension"], DIMENSION)
        self.assertTrue(audit_input["meta_context"]["fallback_flags"]["kcmb_needs_meta"])
        self.assertTrue(audit_input["meta_context"]["fallback_flags"]["jxap_needs_meta"])
        self.assertTrue(audit_input["meta_context"]["raw_text_segments"])
        self.assertIn("payload.kcmb.szmb", audit_input["payload_data"]["kcmb"]["payload_paths"])
    def test_prompt_is_single_dimension_prompt_without_expected_outcome(self) -> None:
        prompt = _build_prompt(build_audit_input(complete_payload(), {}))
        self.assertIn("是否将思政元素有效融入各环节", prompt)
        self.assertIn('"dimension": "szysfyxrghj"', prompt)
        self.assertIn("不审核预期教学成效", prompt)
        self.assertNotIn('"item": "yqcx"', prompt)
    def test_audit_calls_llm_once_and_passes(self) -> None:
        llm = FakeLlm(
            """
            {
              "dimension": "szysfyxrghj",
              "label": "是否将思政元素有效融入各环节",
              "result": "是",
              "reasons": [],
              "checks": {
                "has_ideological_goal": {"result": "是", "reason": "", "evidence_paths": ["payload_data.kcmb.data.szmb"]},
                "has_arrangement_integration": {"result": "是", "reason": "", "evidence_paths": ["payload_data.jxap.data.tm[0].szyqjxx"]},
                "is_effectively_integrated": {"result": "是", "reason": "", "evidence_paths": ["payload_data.kcmb.data.szmb", "payload_data.jxap.data.tm[0].szyqjxx"]}
              },
              "evidence_paths": ["payload_data.kcmb.data.szmb", "payload_data.jxap.data.tm[0].szyqjxx"],
              "suggestion": ""
            }
            """
        )
        section, fields = audit_szysfyxrghj(subject(), llm)
        self.assertEqual(len(llm.prompts), 1)
        self.assertEqual(section.wd, DIMENSION)
        self.assertEqual(section.message, "是")
        self.assertEqual(fields[0].field, FIELD)
        self.assertEqual(fields[0].status, "pass")
        self.assertEqual(section.llm_trace["calls"][0]["raw_response"], fields[0].llm_trace["calls"][0]["raw_response"])
        self.assertEqual(section.llm_trace["calls"][0]["model"], "fake-model")
    def test_negative_result_writes_chinese_reason(self) -> None:
        llm = FakeLlm(
            """
            {
              "dimension": "szysfyxrghj",
              "label": "是否将思政元素有效融入各环节",
              "result": "否",
              "reasons": ["课程目标中未体现明确思政目标"],
              "checks": {
                "has_ideological_goal": {"result": "否", "reason": "课程目标中未体现明确思政目标", "evidence_paths": ["payload_data.kcmb.data.szmb"]},
                "has_arrangement_integration": {"result": "是", "reason": "", "evidence_paths": ["payload_data.jxap.data.tm[0].szyqjxx"]},
                "is_effectively_integrated": {"result": "否", "reason": "课程目标与教学安排中的思政融入缺少呼应", "evidence_paths": []}
              },
              "evidence_paths": ["payload_data.kcmb.data.szmb"],
              "suggestion": "补充与课程内容对应的思政目标　"
            }
            """
        )
        section, fields = audit_szysfyxrghj(subject(), llm)
        self.assertEqual(section.message, "否")
        self.assertIn("课程目标中未体现明确思政目标", section.details["reasons"])
        self.assertEqual(fields[0].status, "fail")
        self.assertIn("课程目标中未体现明确思政目标", fields[0].reason)
    def test_negative_without_reason_gets_fallback_reason(self) -> None:
        result = normalize_llm_result(
            {
                "dimension": DIMENSION,
                "result": "否",
                "reasons": [],
                "checks": {
                    "has_ideological_goal": {"result": "否", "reason": "", "evidence_paths": []},
                    "has_arrangement_integration": {"result": "是", "reason": "", "evidence_paths": []},
                    "is_effectively_integrated": {"result": "否", "reason": "", "evidence_paths": []},
                },
                "evidence_paths": [],
                "suggestion": "",
            }
        )
        self.assertEqual(result["result"], "否")
        self.assertTrue(result["reasons"])
        self.assertIn("需人工复核", result["reasons"][0])
    def test_negative_result_merges_top_and_all_check_reasons(self) -> None:
        result = normalize_llm_result(
            {
                "dimension": DIMENSION,
                "result": "\u5426",
                "reasons": ["\u7ef4\u5ea6\u603b\u539f\u56e0"],
                "checks": {
                    "has_ideological_goal": {"result": "\u5426", "reason": "\u601d\u653f\u76ee\u6807\u7f3a\u5931", "evidence_paths": []},
                    "has_arrangement_integration": {"result": "\u5426", "reason": "\u6559\u5b66\u5b89\u6392\u672a\u4f53\u73b0\u601d\u653f\u878d\u5165", "evidence_paths": []},
                    "is_effectively_integrated": {"result": "\u662f", "reason": "", "evidence_paths": []},
                },
                "evidence_paths": [],
                "suggestion": "",
            }
        )
        self.assertEqual(result["result"], "\u5426")
        self.assertEqual(
            result["reasons"],
            ["\u7ef4\u5ea6\u603b\u539f\u56e0", "\u601d\u653f\u76ee\u6807\u7f3a\u5931", "\u6559\u5b66\u5b89\u6392\u672a\u4f53\u73b0\u601d\u653f\u878d\u5165"],
        )
    def test_invalid_json_preserves_raw_response(self) -> None:
        section, fields = audit_szysfyxrghj(subject(), FakeLlm("not json"))
        self.assertEqual(section.message, "否")
        self.assertEqual(fields[0].status, "fail")
        self.assertEqual(section.llm_trace["calls"][0]["raw_response"], "not json")
        self.assertEqual(section.llm_trace["calls"][0]["status"], "parse_error")
        self.assertIn("JSONDecodeError", section.llm_trace["calls"][0]["parse_error"])
    def test_no_llm_uses_no_llm_trace(self) -> None:
        section, fields = audit_szysfyxrghj(subject(), None)
        self.assertEqual(section.message, "否")
        self.assertEqual(section.llm_trace["calls"][0]["status"], "no_llm")
        self.assertEqual(fields[0].llm_trace["calls"][0]["status"], "no_llm")
if __name__ == "__main__":
    unittest.main()
