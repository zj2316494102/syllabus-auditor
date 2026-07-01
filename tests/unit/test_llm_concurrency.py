"""LLM 并发调用行为的单元测试。"""""
from __future__ import annotations
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.auditors.jxmbnrfsfhyq import audit_jxmbnrfsfhyq
from syllabus_auditor.auditors.registry import AuditorSpec
from syllabus_auditor.auditors.runner import run_batch_audit
from syllabus_auditor.core.audit import AuditSubject, CourseMatch, FieldFinding, SectionFinding
class BlockingJsonLlm:
    def __init__(self, delay: float = 0.2) -> None:
        self.delay = delay
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.prompts: list[str] = []
    def complete_json(self, prompt: str) -> str:
        with self.lock:
            self.prompts.append(prompt)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        key = "jxfs"
        if '"item": "jxmb"' in prompt:
            key = "jxmb"
        elif '"item": "jxnr"' in prompt:
            key = "jxnr"
        return json.dumps(
            {
                "key": key,
                "label": key,
                "result": "\u662f",
                "reasons": [],
                "evidence_paths": [],
                "suggestion": "",
            },
            ensure_ascii=False,
        )
    def metadata(self) -> dict[str, str]:
        return {"provider": "fake", "model": "fake-model"}
def subject(index: int = 1) -> AuditSubject:
    return AuditSubject(
        extraction_id=index,
        course_code=f"C{index}",
        source_path=f"course-{index}.pdf",
        payload={"jcxx": {"kcbh": f"C{index}"}},
        meta={},
        extraction_status="success",
    )
class FakeStore:
    def __init__(self, count: int) -> None:
        self.subjects = [subject(index) for index in range(1, count + 1)]
        self.saved = []
        self.completed = None
        self.failed = None
        self.resumed = None
        self.completed_keys = set()
    def list_subjects(self, *, latest_only: bool = True):
        return list(self.subjects)
    def create_run(self, **kwargs):
        return 42
    def completed_subject_keys(self, *, run_id: int):
        return set(self.completed_keys)
    def resume_run(self, **kwargs):
        self.resumed = kwargs
    def match_course(self, audit_subject, duplicate_course_codes=None):
        return CourseMatch(status="not_found", method="not_found", reasons=["not found"], metadata={"duplicate_course_codes": sorted(duplicate_course_codes or [])})
    def save_subject_audit(self, *, run_id: int, audit):
        self.saved.append((run_id, audit))
        return len(self.saved)
    def complete_run(self, summary):
        self.completed = summary
    def fail_run(self, *, run_id: int, error_message: str):
        self.failed = (run_id, error_message)
class LlmConcurrencyTests(unittest.TestCase):
    def test_jxmbnrfsfhyq_items_call_llm_concurrently(self) -> None:
        llm = BlockingJsonLlm()
        audit_jxmbnrfsfhyq(subject(), llm)
        self.assertEqual(len(llm.prompts), 3)
        self.assertGreater(llm.max_active, 1)
    def test_batch_runner_audits_subjects_concurrently(self) -> None:
        llm = BlockingJsonLlm()
        store = FakeStore(count=4)
        def slow_auditor(audit_subject, llm_client):
            llm_client.complete_json(f'{{"subject": "{audit_subject.course_code}"}}')
            return SectionFinding(wd="slow", status="pass", message="ok", evidence={}, pdfs="direct_llm"), [
                FieldFinding(section="slow", field="x", path="x", status="pass")
            ]
        spec = AuditorSpec("slow", "slow", slow_auditor, True)
        with patch("syllabus_auditor.auditors.runner.validate_audit_config", return_value=[]), patch(
            "syllabus_auditor.auditors.runner._default_auditors", return_value=["slow"]
        ), patch("syllabus_auditor.auditors.runner._audit_config", return_value={"llm_subject_workers": 4}), patch(
            "syllabus_auditor.auditors.runner.load_llm_client", return_value=llm
        ), patch("syllabus_auditor.auditors.runner.AUDITORS", (spec,)):
            summary = run_batch_audit(store=store, limit=4)
        self.assertEqual(summary.total, 4)
        self.assertEqual(len(store.saved), 4)
        self.assertIsNone(store.failed)
        self.assertGreater(llm.max_active, 1)
    def test_batch_runner_resume_skips_completed_subjects(self) -> None:
        store = FakeStore(count=4)
        store.completed_keys = {"extraction:1", "extraction:2"}
        with patch("syllabus_auditor.auditors.runner.validate_audit_config", return_value=[]), patch(
            "syllabus_auditor.auditors.runner._default_auditors", return_value=[]
        ), patch("syllabus_auditor.auditors.runner.load_llm_client", return_value=None), patch(
            "syllabus_auditor.auditors.runner.AUDITORS", ()
        ):
            summary = run_batch_audit(store=store, limit=4, resume_run_id=42)
        saved_keys = [audit.subject.subject_key for _, audit in store.saved]
        self.assertEqual(saved_keys, ["extraction:3", "extraction:4"])
        self.assertEqual(summary.run_id, 42)
        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.skipped_count, 2)
        self.assertEqual(store.resumed["skipped_count"], 2)
        self.assertEqual(store.resumed["pending_count"], 2)
        self.assertIsNone(store.failed)
    def test_batch_runner_failure_marks_run_failed_and_keeps_saved_results(self) -> None:
        store = FakeStore(count=4)
        calls = []
        def flaky_auditor(audit_subject):
            calls.append(audit_subject.extraction_id)
            if audit_subject.extraction_id == 3:
                raise RuntimeError("boom")
            return SectionFinding(wd="flaky", status="pass", message="ok", evidence={}), [
                FieldFinding(section="flaky", field="x", path="x", status="pass")
            ]
        spec = AuditorSpec("flaky", "flaky", flaky_auditor, False)
        with patch("syllabus_auditor.auditors.runner.validate_audit_config", return_value=[]), patch(
            "syllabus_auditor.auditors.runner._default_auditors", return_value=["flaky"]
        ), patch("syllabus_auditor.auditors.runner._audit_config", return_value={"llm_subject_workers": 1}), patch(
            "syllabus_auditor.auditors.runner.load_llm_client", return_value=None
        ), patch("syllabus_auditor.auditors.runner.AUDITORS", (spec,)):
            with self.assertRaises(RuntimeError):
                run_batch_audit(store=store, limit=4)
        saved_keys = [audit.subject.subject_key for _, audit in store.saved]
        self.assertEqual(saved_keys, ["extraction:1", "extraction:2"])
        self.assertEqual(store.failed[0], 42)
        self.assertIn("RuntimeError: boom", store.failed[1])
        self.assertIn(3, calls)
if __name__ == "__main__":
    unittest.main()
