from __future__ import annotations

from pathlib import Path

from config import load_project_config
from syllabus_auditor.core.db.connection import get_project_root
from syllabus_auditor.core.db.extractions import ExtractionStore
from syllabus_auditor.core.extractors.pdfplumber import EXTRACTOR_NAME, PdfPlumberExtractor
from syllabus_auditor.core.meta_builder import build_meta, relative_source_path
from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert
from syllabus_auditor.core.status import judge_extraction_status
from syllabus_auditor.core.types import PrepareSummary

LOADER_CONFIG = load_project_config().get("loader", {})
EXCEL_SUFFIXES = set(LOADER_CONFIG.get("excel_suffixes", []))
PDF_SUFFIX = str(LOADER_CONFIG.get("pdf_suffix") or ".pdf")


def list_pdf_files(input_dir: Path) -> list[Path]:
    """Recursively list PDF files and skip Excel course-library files."""
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录: {input_dir}")

    seen: set[Path] = set()
    pdfs: list[Path] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in EXCEL_SUFFIXES:
            continue
        if suffix != PDF_SUFFIX:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        pdfs.append(path)
    return pdfs


def prepare_syllabus_pdfs(
    input_dir: Path,
    *,
    skip_existing: bool = False,
    store: ExtractionStore | None = None,
    extractor: PdfPlumberExtractor | None = None,
) -> PrepareSummary:
    project_root = get_project_root()
    store = store or ExtractionStore()
    extractor = extractor or PdfPlumberExtractor()
    summary = PrepareSummary()

    pdf_files = list_pdf_files(input_dir)
    summary.total = len(pdf_files)

    for pdf_path in pdf_files:
        rel_path = relative_source_path(pdf_path.resolve(), project_root)

        if skip_existing and store.has_successful_extraction(rel_path):
            summary.skipped += 1
            continue

        try:
            raw = extractor.extract(pdf_path)
            payload = build_payload(raw)
            meta = build_meta(raw, rel_path)
            payload, meta = prepare_payload_and_meta_for_insert(payload, meta)
            status = judge_extraction_status(payload, meta)
            course_code = (payload.get("jcxx") or {}).get("kcbh") or ""

            store.insert(
                course_code=course_code,
                source_path=rel_path,
                payload=payload,
                meta=meta,
                extractor=EXTRACTOR_NAME,
                extraction_status=status,
            )

            if status == "success":
                summary.success += 1
            elif status == "partial":
                summary.partial += 1
            else:
                summary.failed += 1
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"PDF 导入失败: {rel_path} | {message}")
            summary.failures.append({"source_path": rel_path, "error": message})
            summary.failed += 1

    return summary


def run_prepare_courses(input_dir: Path, *, skip_existing: bool = False, list_only: bool = False) -> PrepareSummary | None:
    pdf_files = list_pdf_files(input_dir)
    if list_only:
        print(f"将处理 {len(pdf_files)} 个 PDF")
        for path in pdf_files:
            print(f"  {path.name}")
        return None

    summary = prepare_syllabus_pdfs(input_dir, skip_existing=skip_existing)
    print(
        f"完成：共 {summary.total} 个 PDF，"
        f"成功 {summary.success}，部分 {summary.partial}，"
        f"失败 {summary.failed}，跳过 {summary.skipped}"
    )
    return summary

