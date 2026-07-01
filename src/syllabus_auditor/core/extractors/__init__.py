"""抽取器公共入口：通用模块 + pdfplumber / MinerU 两条流程。"""

from syllabus_auditor.core.extractors.base import BaseExtractor
from syllabus_auditor.core.extractors.mineru import (
    EXTRACTOR_NAME as MINERU_MD_EXTRACTOR,
    MineruMdExtractor,
    MineruMiddleExtractor,
    assess_ocr_quality,
    build_extraction_raw,
    downgrade_warnings_for_ocr,
    html_table_to_grid,
    normalize_mineru_tables,
    repair_md_html,
    resolve_middle_path,
)
from syllabus_auditor.core.extractors.pdfplumber import (
    PdfPlumberExtractor,
    build_text_candidates,
    enhance_raw_extraction,
    extract_section,
)
from syllabus_auditor.core.extractors.section_table_parser import normalize_assessment_rows

__all__ = [
    "BaseExtractor",
    "MINERU_MD_EXTRACTOR",
    "MineruMdExtractor",
    "MineruMiddleExtractor",
    "PdfPlumberExtractor",
    "assess_ocr_quality",
    "build_extraction_raw",
    "build_text_candidates",
    "downgrade_warnings_for_ocr",
    "enhance_raw_extraction",
    "extract_section",
    "html_table_to_grid",
    "normalize_assessment_rows",
    "normalize_mineru_tables",
    "repair_md_html",
    "resolve_middle_path",
]
