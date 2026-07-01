"""pdfplumber 抽取流程包入口：PDF 读取、文本增强、PyMuPDF 版面兜底。"""

from syllabus_auditor.core.extractors.pdfplumber.enhance import (
    ExtractionCandidate,
    build_text_candidates,
    enhance_raw_extraction,
    extract_section as extract_section_from_titles,
)
from syllabus_auditor.core.extractors.pdfplumber.extractor import (
    BASIC_PAIR_LABELS,
    EXTRACTOR_NAME,
    PdfPlumberExtractor,
    RAW_CN_FIELDS,
    TEACHER_LABELS,
    clean_text,
    extract_section,
    normalize_full_text,
    normalize_label,
    parse_pair_table,
    parse_sections_from_text,
    parse_two_column_sections,
    table_has_labels,
)
from syllabus_auditor.core.extractors.pdfplumber.pymupdf_layout import (
    PageLayout,
    PyMuPdfUnavailable,
    TextLine,
    extract_layout,
    layout_to_text,
)

__all__ = [
    "BASIC_PAIR_LABELS",
    "EXTRACTOR_NAME",
    "ExtractionCandidate",
    "PageLayout",
    "PdfPlumberExtractor",
    "PyMuPdfUnavailable",
    "RAW_CN_FIELDS",
    "TEACHER_LABELS",
    "TextLine",
    "build_text_candidates",
    "clean_text",
    "enhance_raw_extraction",
    "extract_layout",
    "extract_section",
    "extract_section_from_titles",
    "layout_to_text",
    "normalize_full_text",
    "normalize_label",
    "parse_pair_table",
    "parse_sections_from_text",
    "parse_two_column_sections",
    "table_has_labels",
]
