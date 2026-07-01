"""PDF 准备流程的单元测试。"""
from __future__ import annotations
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from syllabus_auditor.application.prepare.pdf import prepare_syllabus_pdfs
from syllabus_auditor.core.types import ExtractionRaw
class FailingExtractor:
    def extract(self, pdf_path: Path):  # noqa: ANN201
        raise RuntimeError(f"cannot read {pdf_path.name}")
class NoopStore:
    def __init__(self) -> None:
        self.rows = []
    def has_successful_extraction(self, source_path: str) -> bool:
        return False
    def insert(self, **kwargs) -> None:  # noqa: ANN003
        self.rows.append(kwargs)
        return None
class MissingCodeExtractor:
    def extract(self, pdf_path: Path) -> ExtractionRaw:
        return ExtractionRaw(
            cn_data={"课程编号": "", "中文课程名称": "测试课"},
            full_text="",
            raw_pages=[],
            page_count=1,
            source_path=pdf_path,
        )
class SyllabusPdfLoaderTests(unittest.TestCase):
    def test_failed_pdf_reports_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "broken.pdf"
            pdf_path.write_bytes(b"not a pdf")
            output = io.StringIO()
            with redirect_stdout(output):
                summary = prepare_syllabus_pdfs(
                    Path(tmp_dir),
                    store=NoopStore(),
                    extractor=FailingExtractor(),
                )
        self.assertEqual(summary.failed, 1)
        self.assertEqual(len(summary.failures), 1)
        self.assertIn("RuntimeError: cannot read broken.pdf", summary.failures[0]["error"])
        self.assertIn("PDF 导入失败", output.getvalue())
        self.assertIn("RuntimeError: cannot read broken.pdf", output.getvalue())
    def test_missing_course_code_is_not_replaced_by_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "课程名称.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            store = NoopStore()
            summary = prepare_syllabus_pdfs(
                Path(tmp_dir),
                store=store,
                extractor=MissingCodeExtractor(),
            )
        self.assertEqual(summary.partial, 1)
        self.assertEqual(store.rows[0]["course_code"], "")
if __name__ == "__main__":
    unittest.main()
