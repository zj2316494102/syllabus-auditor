"""教学方式审核 prompt 规则的单元测试。"""""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.auditors.jxmbnrfsfhyq import _build_item_prompt, build_audit_input
class JxfsPromptRuleTests(unittest.TestCase):
    def test_jxfs_prompt_allows_single_clear_teaching_method(self) -> None:
        audit_input = build_audit_input(
            {
                "jxap": {"tm": [{"skfs": "讲授"}], "apgs": ""},
                "khfsb": {"tm": [], "khgs": ""},
                "kcyq": "",
            },
            {},
        )
        prompt = _build_item_prompt(audit_input, "jxfs")
        self.assertIn("不得仅因教学方式单一判否", prompt)
        self.assertIn("讲授", prompt)
        self.assertIn("不应直接判否", prompt)
    def test_single_method_rule_is_only_for_jxfs(self) -> None:
        audit_input = build_audit_input({}, {})
        prompt = _build_item_prompt(audit_input, "jxmb")
        self.assertNotIn("不得仅因教学方式单一判否", prompt)
if __name__ == "__main__":
    unittest.main()
