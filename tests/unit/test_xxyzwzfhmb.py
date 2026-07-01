"""信息要素完整规则审核维度的单元测试。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.auditors.xxyzwzfhmb import DIMENSION, audit_xxyzwzfhmb
from syllabus_auditor.core.audit import AuditSubject
def complete_payload() -> dict:
    return {
        "jcxx": {
            "kcbh": "ABC123",
            "kkyx": "测试学院",
            "zwkcmc": "测试课程",
            "ywkcmc": "Test Course",
            "skyy": "中文",
            "sfyxwxyxk": "否",
            "khfs": "考试",
            "kcxz": "必修",
            "kclb": "专业课",
            "zxs": "2",
            "skzs": "19",
            "zongxs": "38",
            "jxxs": "38",
            "syxs": "",
            "sjxs": "",
            "qtxs": "",
            "zxxs": "",
            "kcxf": "2",
            "rkjsxm": "张三",
            "jsgh": "T001",
            "email": "teacher@example.com",
            "lxdh": "123456",
        },
        "kczwjj": "中文简介",
        "kcywjj": "English intro",
        "ybzsyq": "预备知识",
        "jcjydcl": "教材",
        "kcmb": {"szmb": "思政", "nlmb": "能力", "zsmb": "知识", "mbgs": ""},
        "jxnr": {
            "tm": [{"xh": "1", "zt": "主题一", "zsd": "知识点一", "xs": "20"}],
            "zongxs": "20",
            "nrgs": "",
        },
        "jxap": {
            "tm": [{"zs": "1-10", "sknr": "内容", "skfs": "讲授", "szyqjxx": "融入"}],
            "apgs": "",
        },
        "kcyq": "课程要求",
        "kcyqb": {"tm": [], "yqgs": "", "kzzd": []},
    }
def subject(payload: dict | None = None, meta: dict | None = None) -> AuditSubject:
    return AuditSubject(
        extraction_id=1,
        course_code="ABC123",
        source_path="data/test.pdf",
        payload=payload or complete_payload(),
        meta=meta or {},
        extraction_status="success",
    )
class XxyzwzfhmbTests(unittest.TestCase):
    def test_complete_payload_passes_and_special_empty_fields_are_allowed(self) -> None:
        section, fields = audit_xxyzwzfhmb(subject())
        self.assertEqual(section.wd, DIMENSION)
        self.assertEqual(section.message, "是")
        self.assertEqual(section.details["checks"]["mbxxyzwz"]["result"], "是")
        self.assertEqual(section.details["checks"]["zywjj"]["result"], "是")
        special = [item for item in fields if item.field in {"syxs", "sjxs", "qtxs", "zxxs"}]
        self.assertEqual({item.status for item in special}, {"pass"})
        self.assertTrue(all("允许为空" in item.message for item in special))
    def test_missing_special_key_fails_only_template_dimension(self) -> None:
        payload = complete_payload()
        del payload["jcxx"]["syxs"]
        section, fields = audit_xxyzwzfhmb(subject(payload))
        self.assertEqual(section.message, "否")
        target = [item for item in fields if item.field == "syxs"][0]
        self.assertEqual(target.status, "fail")
        self.assertEqual(target.reason, "实验学时字段缺失")
    def test_missing_chinese_intro_fails_zywjj(self) -> None:
        payload = complete_payload()
        payload["kczwjj"] = ""
        section, fields = audit_xxyzwzfhmb(subject(payload))
        self.assertEqual(section.message, "否")
        self.assertEqual(section.details["checks"]["zywjj"]["result"], "否")
        self.assertTrue(any(item.field == "kczwjj" and item.reason == "课程中文简介为空" for item in fields))
    def test_missing_english_intro_fails_zywjj(self) -> None:
        payload = complete_payload()
        payload["kcywjj"] = ""
        section, fields = audit_xxyzwzfhmb(subject(payload))
        self.assertEqual(section.message, "否")
        self.assertEqual(section.details["checks"]["zywjj"]["result"], "否")
        self.assertTrue(any(item.field == "kcywjj" and item.reason == "课程英文简介为空" for item in fields))
    def test_missing_teaching_content_row_field_fails_with_row_reason(self) -> None:
        payload = complete_payload()
        payload["jxnr"]["tm"][0]["zsd"] = ""
        section, fields = audit_xxyzwzfhmb(subject(payload))
        self.assertEqual(section.message, "否")
        self.assertTrue(any(item.path == "payload.jxnr.tm[0].zsd" and "第 1 行知识点为空" in item.reason for item in fields))
    def test_missing_teaching_arrangement_row_field_fails_with_row_reason(self) -> None:
        payload = complete_payload()
        payload["jxap"]["tm"][0]["szyqjxx"] = ""
        section, fields = audit_xxyzwzfhmb(subject(payload))
        self.assertEqual(section.message, "否")
        self.assertTrue(any(item.path == "payload.jxap.tm[0].szyqjxx" and "第 1 行思政元素" in item.reason for item in fields))
    def test_empty_course_requirement_fails(self) -> None:
        payload = complete_payload()
        payload["kcyq"] = ""
        payload["kcyqb"] = {"tm": [], "yqgs": "", "kzzd": []}
        section, fields = audit_xxyzwzfhmb(subject(payload))
        self.assertEqual(section.message, "否")
        self.assertTrue(any(item.section == "kcyq" and item.field == "content" and item.reason == "课程要求为空" for item in fields))
    def test_missing_special_key_can_use_meta_label_fallback(self) -> None:
        payload = complete_payload()
        del payload["jcxx"]["syxs"]
        meta = {"raw_pages": [{"text": "课程基本信息\n实验学时\n实践学时\n其他学时\n自学学时\n"}]}
        section, fields = audit_xxyzwzfhmb(subject(payload, meta))
        self.assertEqual(section.message, "是")
        target = [item for item in fields if item.field == "syxs"][0]
        self.assertEqual(target.status, "pass")
        self.assertTrue(target.evidence["fallback_used"])
        self.assertEqual(target.evidence["reason"], "payload_key_missing_meta_label_found")
    def test_meta_title_only_does_not_pass_empty_field(self) -> None:
        payload = complete_payload()
        payload["kczwjj"] = ""
        meta = {"raw_pages": [{"text": "课程中文简介\n"}]}
        section, fields = audit_xxyzwzfhmb(subject(payload, meta))
        self.assertEqual(section.message, "否")
        target = [item for item in fields if item.field == "kczwjj"][0]
        self.assertEqual(target.status, "fail")
        self.assertIn("原文辅助信息中只有章节标题", target.reason)
if __name__ == "__main__":
    unittest.main()
