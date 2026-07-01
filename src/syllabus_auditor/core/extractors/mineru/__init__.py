"""MinerU 抽取流程：MD/middle 读取、表格归一化、结构化处理。"""

from syllabus_auditor.core.extractors.mineru.md import (
    EXTRACTOR_NAME,
    MineruMdExtractor,
    apply_ocr_quality_metadata,
    assess_ocr_quality,
    downgrade_warnings_for_ocr,
    fill_grids_from_middle,
    html_tables_from_md,
    load_middle_grids,
    repair_md_html,
    resolve_middle_path,
)
from syllabus_auditor.core.extractors.mineru.middle import MineruMiddleExtractor
from syllabus_auditor.core.extractors.mineru.process import (
    _JCXX_REGEX,
    _fill_jcxx_from_text,
    apply_mineru_text_fallback,
    build_extraction_raw,
)
from syllabus_auditor.core.extractors.mineru.tables import (
    html_table_to_grid,
    normalize_mineru_tables,
    repair_pair_table,
    scan_row_label_pairs,
)

__all__ = [
    "EXTRACTOR_NAME",
    "MineruMdExtractor",
    "MineruMiddleExtractor",
    "_JCXX_REGEX",
    "_fill_jcxx_from_text",
    "apply_mineru_text_fallback",
    "apply_ocr_quality_metadata",
    "assess_ocr_quality",
    "build_extraction_raw",
    "downgrade_warnings_for_ocr",
    "fill_grids_from_middle",
    "html_table_to_grid",
    "html_tables_from_md",
    "load_middle_grids",
    "normalize_mineru_tables",
    "repair_md_html",
    "repair_pair_table",
    "resolve_middle_path",
    "scan_row_label_pairs",
]
