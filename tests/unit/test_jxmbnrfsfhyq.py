"""教学目标/内容/方式 LLM 审核维度的单元测试。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.auditors.jxmbnrfsfhyq import (
    DIMENSION,
    FALLBACK_REASON,
    _aggregate_item_results as aggregate_item_results,
    audit_jxmbnrfsfhyq,
    build_audit_input,
    _normalize_llm_result as normalize_llm_result,
    _build_item_prompt,
)
from syllabus_auditor.core.audit import AuditSubject
class FakeLlm:
    def __init__(self, texts: str | list[str]) -> None:
        self.texts = [texts] if isinstance(texts, str) else list(texts)
        self.prompts: list[str] = []
    def complete_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.texts:
            raise AssertionError("LLM called more times than expected")
        return self.texts.pop(0)
    def metadata(self) -> dict[str, str]:
        return {"provider": "fake", "model": "fake-model"}
def subject() -> AuditSubject:
    return AuditSubject(
        extraction_id=1,
        course_code="ABC123",
        source_path="data/test.pdf",
        payload={
            "jcxx": {"zwkcmc": "测试课程", "kcxz": "必修"},
            "kcmb": {"szmb": "思政目标", "nlmb": "能力目标", "zsmb": "知识目标", "mbgs": "", "kzzd": {"qtmb": "其他目标"}},
            "jxnr": {"tm": [{"xh": "1", "zt": "主题", "zsd": "知识点", "xs": "2"}], "zongxs": "2", "nrgs": ""},
            "jxap": {"tm": [{"zs": "1", "sknr": "授课内容", "skfs": "讲授", "szyqjxx": "思政融入"}], "apgs": ""},
            "khfsb": {"tm": [{"ksxs": "期末", "kcnr": "考试内容", "kcfs": "闭卷", "zb": "50%"}], "khgs": ""},
            "kcyq": "教材要求",
            "kcyqb": {"tm": [{"yqlx": "阅读", "yqnr": "其他要求"}], "yqgs": "", "kzzd": {"qtx": "其他要求"}},
        },
        meta={
            "extraction_warnings": [{"section": "kcmb", "field": "szmb", "reason": "missing_field"}],
            "unmapped_segments": [],
            "raw_pages": ["课程目标：知识能力价值观。教学安排：讲授。"],
        },
        extraction_status="partial",
    )
class JxmbnrfsfhyqTests(unittest.TestCase):
    def test_audit_input_uses_three_real_data_blocks(self) -> None:
        audit_input = build_audit_input(subject().payload, subject().meta)
        self.assertNotIn("audit_payload", audit_input)
        self.assertEqual(audit_input["audit_subject"]["dimension"], DIMENSION)
        self.assertEqual(audit_input["audit_inputs"]["jxmb"]["payload_paths"], ["payload.kcmb"])
        self.assertEqual(audit_input["audit_inputs"]["jxmb"]["data"]["szmb"], "思政目标")
        self.assertEqual(audit_input["audit_inputs"]["jxnr"]["data"]["tm"][0]["zsd"], "知识点")
        self.assertEqual(audit_input["audit_inputs"]["jxfs"]["data"]["jxap"]["tm"][0]["skfs"], "讲授")
        self.assertEqual(audit_input["audit_inputs"]["jxfs"]["data"]["khfsb"]["tm"][0]["zb"], "50%")
        self.assertEqual(audit_input["audit_inputs"]["jxfs"]["data"]["kcyq"], "教材要求")
    def test_item_prompts_only_include_their_own_main_data(self) -> None:
        def prompt_data_json(prompt: str) -> str:
            return prompt.split("输入 JSON：", 1)[1].split("请输出严格 JSON", 1)[0]

        audit_input = build_audit_input(subject().payload, subject().meta)
        jxmb_prompt = _build_item_prompt(audit_input, "jxmb")
        jxnr_prompt = _build_item_prompt(audit_input, "jxnr")
        jxfs_prompt = _build_item_prompt(audit_input, "jxfs")
        self.assertNotIn("audit_payload", jxmb_prompt)
        self.assertIn('"item": "jxmb"', jxmb_prompt)
        jxmb_json = prompt_data_json(jxmb_prompt)
        self.assertIn("思政目标", jxmb_json)
        self.assertNotIn("知识点", jxmb_json)
        self.assertNotIn("闭卷", jxmb_json)
        self.assertIn('"item": "jxnr"', jxnr_prompt)
        jxnr_json = prompt_data_json(jxnr_prompt)
        self.assertIn("知识点", jxnr_json)
        self.assertNotIn("能力目标", jxnr_json)
        self.assertNotIn("闭卷", jxnr_json)
        self.assertIn('"item": "jxfs"', jxfs_prompt)
        jxfs_json = prompt_data_json(jxfs_prompt)
        self.assertIn("讲授", jxfs_json)
        self.assertNotIn("能力目标", jxfs_json)
        self.assertNotIn("知识点", jxfs_json)
    def test_meta_raw_text_segments_are_included(self) -> None:
        audit_input = build_audit_input(subject().payload, subject().meta)
        segments = audit_input["meta_context"]["raw_text_segments"]
        self.assertTrue(segments)
        self.assertIn("课程目标", segments[0]["text"])
    def test_negative_item_without_reason_gets_fallback_reason(self) -> None:
        result = normalize_llm_result(
            {
                "dimension": DIMENSION,
                "result": "否",
                "reasons": [],
                "items": [
                    {"key": "jxmb", "result": "否", "reasons": [], "evidence_paths": [], "suggestion": ""},
                    {"key": "jxnr", "result": "否", "reasons": [], "evidence_paths": [], "suggestion": ""},
                    {"key": "jxfs", "result": "否", "reasons": [], "evidence_paths": [], "suggestion": ""},
                ],
            }
        )
        self.assertEqual(result["result"], "否")
        self.assertIn(FALLBACK_REASON, result["reasons"])
        self.assertIn(FALLBACK_REASON, result["items"][0]["reasons"])
    def test_negative_result_merges_top_and_all_item_reasons(self) -> None:
        result = normalize_llm_result(
            {
                "dimension": DIMENSION,
                "result": "否",
                "reasons": ["维度总原因"],
                "items": [
                    {"key": "jxmb", "result": "否", "reasons": ["教学目标原因"], "evidence_paths": [], "suggestion": ""},
                    {"key": "jxnr", "result": "否", "reasons": ["教学内容原因"], "evidence_paths": [], "suggestion": ""},
                    {"key": "jxfs", "result": "是", "reasons": [], "evidence_paths": [], "suggestion": ""},
                ],
            }
        )
        self.assertEqual(result["result"], "否")
        self.assertEqual(
            result["reasons"],
            ["维度总原因", "教学目标原因", "教学内容原因"],
        )
    def test_aggregate_item_results_requires_all_items_to_pass(self) -> None:
        result = aggregate_item_results(
            [
                {"key": "jxmb", "label": "教学目标是否符合要求", "result": "是", "reasons": [], "evidence_paths": [], "suggestion": ""},
                {"key": "jxnr", "label": "教学内容是否符合要求", "result": "否", "reasons": ["教学内容表述不够充实"], "evidence_paths": ["audit_input.data.tm[0].zsd"], "suggestion": "建议补充内容"},
                {"key": "jxfs", "label": "教学方式是否符合要求", "result": "是", "reasons": [], "evidence_paths": [], "suggestion": ""},
            ]
        )
        self.assertEqual(result["result"], "否")
        self.assertIn("教学内容表述不够充实", result["reasons"])
    def test_audit_calls_llm_three_times_and_outputs_field_reasons(self) -> None:
        llm = FakeLlm(
            [
                """
            {
              "key": "jxmb",
              "label": "教学目标是否符合要求",
              "result": "否",
              "reasons": ["课程目标缺少知识能力价值观维度"],
              "evidence_paths": ["audit_input.data.szmb"],
              "suggestion": "建议补充课程目标表述"
            }
                """,
                """
            {
              "key": "jxnr",
              "label": "教学内容是否符合要求",
              "result": "是",
              "reasons": [],
              "evidence_paths": ["meta_context.raw_text_segments[0].text"],
              "suggestion": ""
            }
                """,
                """
            {
              "key": "jxfs",
              "label": "教学方式是否符合要求",
              "result": "是",
              "reasons": [],
              "evidence_paths": ["audit_input.data.jxap.tm[0].skfs"],
              "suggestion": ""
            }
                """,
            ]
        )
        section, fields = audit_jxmbnrfsfhyq(subject(), llm)
        self.assertEqual(len(llm.prompts), 3)
        self.assertEqual(section.wd, DIMENSION)
        self.assertEqual(section.pdfs, "direct_llm")
        self.assertEqual(section.message, "否")
        self.assertIn("课程目标缺少知识能力价值观维度", section.details["reasons"])
        failed = [item for item in fields if item.status == "fail"]
        self.assertEqual(failed[0].section, DIMENSION)
        self.assertEqual(failed[0].field, "jxmb")
        self.assertTrue(failed[0].reason)
        self.assertEqual(len(section.llm_trace["calls"]), 3)
        self.assertEqual(section.llm_trace["calls"][0]["item"], "jxmb")
        self.assertIn("课程目标缺少", section.llm_trace["calls"][0]["raw_response"])
        self.assertEqual(failed[0].llm_trace["calls"][0]["raw_response"], section.llm_trace["calls"][0]["raw_response"])
        self.assertEqual(failed[0].llm_trace["calls"][0]["model"], "fake-model")
    def test_one_invalid_llm_json_only_fails_that_item(self) -> None:
        llm = FakeLlm(
            [
                "not json",
                '{"key": "jxnr", "label": "教学内容是否符合要求", "result": "是", "reasons": [], "evidence_paths": [], "suggestion": ""}',
                '{"key": "jxfs", "label": "教学方式是否符合要求", "result": "是", "reasons": [], "evidence_paths": [], "suggestion": ""}',
            ]
        )
        section, fields = audit_jxmbnrfsfhyq(subject(), llm)
        self.assertEqual(section.message, "否")
        self.assertTrue(section.details["reasons"])
        self.assertIn("教学目标是否符合要求", section.details["reasons"][0])
        failed = [item for item in fields if item.status == "fail"]
        passed = [item for item in fields if item.status == "pass"]
        self.assertEqual([item.field for item in failed], ["jxmb"])
        self.assertEqual({item.field for item in passed}, {"jxnr", "jxfs"})
        self.assertTrue(all(item.reason for item in failed))
        self.assertEqual(failed[0].llm_trace["calls"][0]["raw_response"], "not json")
        self.assertEqual(failed[0].llm_trace["calls"][0]["status"], "parse_error")
        self.assertIn("JSONDecodeError", failed[0].llm_trace["calls"][0]["parse_error"])
        self.assertEqual(len(section.llm_trace["calls"]), 3)
    def test_no_llm_trace_uses_appendable_calls_shape(self) -> None:
        section, fields = audit_jxmbnrfsfhyq(subject(), None)
        self.assertEqual(section.message, "否")
        self.assertEqual(len(section.llm_trace["calls"]), 3)
        self.assertTrue(all(call["status"] == "no_llm" for call in section.llm_trace["calls"]))
        self.assertTrue(all(field.llm_trace["calls"][0]["status"] == "no_llm" for field in fields))
if __name__ == "__main__":
    unittest.main()
