"""MinerU Markdown 读取与后处理（OCR 修复、middle 补格、质量评估）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from syllabus_auditor.core.extractors.mineru.process import build_extraction_raw
from syllabus_auditor.core.extractors.mineru.tables import html_table_to_grid
from syllabus_auditor.core.extractors.pdfplumber.extractor import clean_text
from syllabus_auditor.core.types import ExtractionRaw
from syllabus_auditor.shared.config import load_project_config

EXTRACTOR_NAME = "mineru_md"


# ---------------------------------------------------------------------------
# OCR 修复：MD 内嵌 HTML 表格修复（抽表前）
# ---------------------------------------------------------------------------

_EN_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")
_EN_LETTER_DIGIT = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")

_HEADER_MERGE_PAIRS: tuple[tuple[str, str], ...] = (
    ("思政元素的融入和预期教学成", "效"),
    ("融入的思政元素和预期教学成", "效"),
    ("思政元素融入和预期教学成", "效"),
    ("预期教学成", "效"),
    ("知", "识目标"),
    ("知 识 目", "标"),
    ("思 政 目", "标"),
    ("英文课程名称", "Adv"),
    ("中文课程名称", ""),
)

_EN_LINE_FRAGMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bPresen\b", re.I), "Presentation"),
    (re.compile(r"\bsenta\b", re.I), "Presentation"),
    (re.compile(r"\btation\b", re.I), "Presentation"),
)


def _fix_english_spacing(text: str) -> str:
    if not text or not re.search(r"[A-Za-z]", text):
        return text
    if re.search(r"[\u4e00-\u9fa5]", text) and len(re.findall(r"[A-Za-z]", text)) < 8:
        return text
    updated = _EN_CAMEL_BOUNDARY.sub(" ", text)
    updated = _EN_LETTER_DIGIT.sub(" ", updated)
    for pattern, replacement in _EN_LINE_FRAGMENTS:
        updated = pattern.sub(replacement, updated)
    return re.sub(r" {2,}", " ", updated).strip()


def _set_cell_text(cell: Tag, text: str) -> None:
    cell.clear()
    cell.append(NavigableString(text))


def _merge_broken_header_cells(tr: Tag) -> None:
    cells = tr.find_all(["td", "th"], recursive=False)
    if len(cells) < 2:
        return
    i = 0
    while i < len(cells) - 1:
        left = cells[i].get_text(" ", strip=True)
        right = cells[i + 1].get_text(" ", strip=True)
        merged = False
        for prefix, suffix in _HEADER_MERGE_PAIRS:
            if not prefix:
                continue
            if left.rstrip().endswith(prefix.rstrip()) or prefix in left:
                if not suffix or right.startswith(suffix) or right == suffix:
                    combined = (left + right).replace("  ", " ").strip()
                    _set_cell_text(cells[i], combined)
                    cells[i + 1].decompose()
                    cells = tr.find_all(["td", "th"], recursive=False)
                    merged = True
                    break
            if left == prefix and right.startswith(suffix):
                _set_cell_text(cells[i], left + right)
                cells[i + 1].decompose()
                cells = tr.find_all(["td", "th"], recursive=False)
                merged = True
                break
        if not merged:
            i += 1


def _is_phantom_row(tr: Tag) -> bool:
    texts = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
    joined = " ".join(t for t in texts if t)
    if not joined:
        return True
    if re.search(r"[\u4e00-\u9fa5]", joined):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", joined.replace(" ", "")):
        return False
    if len(joined) >= 12 and re.search(r"[A-Za-z]{4,}", joined):
        return False
    compact = re.sub(r"\s+", "", joined)
    return len(compact) < 4


def _repair_table(table: Tag) -> None:
    rows = table.find_all("tr", recursive=False)
    if not rows:
        return
    _merge_broken_header_cells(rows[0])
    for tr in rows:
        for cell in tr.find_all(["td", "th"]):
            raw = cell.get_text(" ", strip=True)
            if not raw:
                continue
            fixed = _fix_english_spacing(raw)
            if fixed != raw:
                _set_cell_text(cell, fixed)
    for tr in list(rows):
        if tr is rows[0]:
            continue
        if _is_phantom_row(tr):
            tr.decompose()


def repair_md_html(md_text: str) -> str:
    """修复 MD 内嵌 HTML 表格后返回 MD 字符串（保留 ## 标题等非 table 内容）。"""
    if "<table" not in md_text:
        return md_text
    pattern = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)

    def _repl(match: re.Match[str]) -> str:
        soup = BeautifulSoup(match.group(0), "html.parser")
        table = soup.find("table")
        if table is None:
            return match.group(0)
        _repair_table(table)
        return str(table)

    return pattern.sub(_repl, md_text)


# ---------------------------------------------------------------------------
# middle 补格：middle.json 补全 MD 网格空单元格
# ---------------------------------------------------------------------------


def _walk_html_tables(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "table" and isinstance(node.get("html"), str):
            out.append(node["html"])
        for span in node.get("spans") or []:
            if isinstance(span, dict):
                if span.get("type") == "table" and isinstance(span.get("html"), str):
                    out.append(span["html"])
                elif span.get("type") == "text":
                    pass
        for key in ("lines", "blocks", "preproc_blocks", "discarded_blocks", "para_blocks"):
            for child in node.get(key) or []:
                _walk_html_tables(child, out)
    elif isinstance(node, list):
        for item in node:
            _walk_html_tables(item, out)


def load_middle_grids(middle_path: Path) -> list[list[list[str | None]]]:
    if not middle_path.exists():
        return []
    payload = json.loads(middle_path.read_text(encoding="utf-8"))
    pages = payload.get("pdf_info") or []
    if not isinstance(pages, list):
        return []
    html_tables: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        for key in ("preproc_blocks", "para_blocks", "discarded_blocks"):
            for block in page.get(key) or []:
                _walk_html_tables(block, html_tables)
    grids: list[list[list[str | None]]] = []
    for html in html_tables:
        grid = html_table_to_grid(html)
        if grid:
            grids.append(grid)
    return grids


def _table_fingerprint(grid: list[list[str | None]]) -> str:
    if not grid:
        return ""
    head = "|".join(clean_text(c) for c in grid[0] if clean_text(c))
    rows = sum(1 for row in grid[1:] if any(clean_text(c) for c in row))
    cols = max((len(row) for row in grid), default=0)
    return f"{head}#{rows}x{cols}"


def _shape_compatible(a: list[list[str | None]], b: list[list[str | None]]) -> bool:
    if not a or not b:
        return False
    cols_a = max(len(r) for r in a)
    cols_b = max(len(r) for r in b)
    if abs(cols_a - cols_b) > 2:
        return False
    rows_a = len(a)
    rows_b = len(b)
    return abs(rows_a - rows_b) <= max(3, rows_a // 3)


def _header_overlap(a: list[list[str | None]], b: list[list[str | None]]) -> bool:
    ha = {clean_text(c) for c in (a[0] if a else []) if clean_text(c)}
    hb = {clean_text(c) for c in (b[0] if b else []) if clean_text(c)}
    if not ha or not hb:
        return _shape_compatible(a, b)
    overlap = ha & hb
    if overlap:
        return True
    joined_a = "".join(ha)
    joined_b = "".join(hb)
    for token in ("序号", "主题", "授课内容", "课程编号", "Class", "Topic"):
        if token in joined_a and token in joined_b:
            return True
    return False


def _is_empty_cell(value: str | None) -> bool:
    text = clean_text(value)
    if not text:
        return True
    return text.lower() in {"none", "null", "n/a", "无", "不填"}


def _fill_grid(target: list[list[str | None]], donor: list[list[str | None]]) -> int:
    filled = 0
    height = max(len(target), len(donor))
    width = max(
        max((len(r) for r in target), default=0),
        max((len(r) for r in donor), default=0),
    )
    for r in range(height):
        while len(target) <= r:
            target.append([None] * width)
        while len(target[r]) < width:
            target[r].append(None)
        if r >= len(donor):
            continue
        donor_row = donor[r]
        for c in range(width):
            if c >= len(donor_row):
                continue
            if not _is_empty_cell(target[r][c]) or _is_empty_cell(donor_row[c]):
                continue
            donor_val = clean_text(donor_row[c])
            if len(donor_val) >= 2:
                target[r][c] = donor_val
                filled += 1
    return filled


def fill_grids_from_middle(
    md_grids: list[list[list[str | None]]],
    middle_grids: list[list[list[str | None]]],
) -> tuple[list[list[list[str | None]]], int]:
    """按表头/形状匹配，用 middle 非空单元格补 MD 空单元格。"""
    if not middle_grids:
        return md_grids, 0
    used_middle: set[int] = set()
    total_filled = 0
    result: list[list[list[str | None]]] = []
    for md_table in md_grids:
        table = [list(row) for row in md_table]
        best_idx = -1
        best_score = -1
        for mid_idx, mid_table in enumerate(middle_grids):
            if mid_idx in used_middle:
                continue
            if not _shape_compatible(table, mid_table):
                continue
            if not _header_overlap(table, mid_table):
                continue
            score = len(_table_fingerprint(table)) + len(_table_fingerprint(mid_table))
            if score > best_score:
                best_score = score
                best_idx = mid_idx
        if best_idx >= 0:
            used_middle.add(best_idx)
            total_filled += _fill_grid(table, middle_grids[best_idx])
        result.append(table)
    return result, total_filled


def resolve_middle_path(middle_rel: str | None, project_root: Path) -> Path | None:
    if not middle_rel:
        return None
    path = project_root / Path(middle_rel.replace("\\", "/"))
    return path if path.exists() else None


# ---------------------------------------------------------------------------
# OCR 质量：质量评估与告警降级
# ---------------------------------------------------------------------------

_COLUMN_TOKENS: dict[str, tuple[str, ...]] = {
    "学时": ("学时", "课时"),
    "授课方式": ("授课方式", "教学方式"),
    "思政元素的融入和预期教学成效": ("思政", "预期教学成效", "课程思政"),
    "知识点": ("知识点", "教学内容"),
    "主题": ("主题", "单元"),
    "授课内容": ("授课内容", "Topic", "topic"),
}

def _ocr_quality_cfg() -> dict[str, Any]:
    value = load_project_config().get("ocr_quality", {})
    return value if isinstance(value, dict) else {}


def _en_fragment_pattern() -> re.Pattern[str]:
    cfg = _ocr_quality_cfg()
    return re.compile(str(cfg.get("en_fragment_pattern") or r"\b[A-Za-z]{2,5}\b(?!\w)"))


def _header_col_map(header_row: list[str | None]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for idx, cell in enumerate(header_row):
        text = clean_text(cell)
        if not text:
            continue
        flat = re.sub(r"\s+", "", text)
        for field, tokens in _COLUMN_TOKENS.items():
            if any(token in text or token in flat for token in tokens):
                mapping[idx] = field
                break
    return mapping


def _column_fill_ratio(grid: list[list[str | None]], col: int, *, start_row: int = 1) -> float:
    values = 0
    non_empty = 0
    for row in grid[start_row:]:
        if col >= len(row):
            continue
        values += 1
        if clean_text(row[col]):
            non_empty += 1
    if not values:
        return 0.0
    return non_empty / values


def _english_fragment_ratio(md_text: str) -> float:
    cfg = _ocr_quality_cfg()
    words = _en_fragment_pattern().findall(md_text)
    if not words:
        return 0.0
    short_max = int(cfg.get("short_en_word_max_len", 4))
    short = sum(1 for w in words if len(w) <= short_max)
    return short / len(words)


def _glued_label_count(md_text: str) -> int:
    patterns = _ocr_quality_cfg().get("glued_label_patterns") or []
    return sum(len(re.findall(str(p), md_text)) for p in patterns)


def assess_ocr_quality(md_text: str, tables: list[list[list[str | None]]]) -> dict[str, Any]:
    """评估 MD OCR 质量，返回 score/issues/empty_columns 等。"""
    cfg = _ocr_quality_cfg()
    issues: list[str] = []
    empty_columns: list[dict[str, Any]] = []
    score = 100.0

    frag_ratio = _english_fragment_ratio(md_text)
    frag_threshold = float(cfg.get("english_fragment_threshold", 0.35))
    if frag_ratio > frag_threshold:
        issues.append("english_fragment_heavy")
        score -= min(
            float(cfg.get("english_fragment_penalty_cap", 25)),
            frag_ratio * float(cfg.get("english_fragment_penalty_factor", 40)),
        )

    glued = _glued_label_count(md_text)
    if glued:
        issues.append("glued_pair_labels")
        score -= min(
            float(cfg.get("glued_label_penalty_cap", 15)),
            glued * float(cfg.get("glued_label_penalty_per_hit", 3)),
        )

    empty_fields = {str(item) for item in (cfg.get("empty_column_fields") or [])}
    empty_penalty = float(cfg.get("empty_column_penalty", 8))
    for grid in tables:
        if len(grid) < 2:
            continue
        col_map = _header_col_map(grid[0])
        for col_idx, field in col_map.items():
            ratio = _column_fill_ratio(grid, col_idx)
            if ratio == 0 and field in empty_fields:
                empty_columns.append({"field": field, "col": col_idx, "fill_ratio": 0.0})
                issues.append(f"empty_column:{field}")
                score -= empty_penalty

    rerun_threshold = float(cfg.get("rerun_score_threshold", 65))
    rerun_recommended = score < rerun_threshold or "english_fragment_heavy" in issues
    return {
        "score": round(max(score, 0), 1),
        "issues": issues,
        "empty_columns": empty_columns,
        "english_fragment_ratio": round(frag_ratio, 3),
        "glued_label_count": glued,
        "rerun_recommended": rerun_recommended,
    }


def apply_ocr_quality_metadata(raw: ExtractionRaw, report: dict[str, Any]) -> None:
    raw.section_extraction["ocr_quality"] = report
    if report.get("rerun_recommended"):
        raw.extraction_warnings.append(
            {
                "section": "ocr",
                "reason": "mineru_ocr_rerun_recommended",
                "score": report.get("score"),
                "severity": "warn",
            }
        )
    for col in report.get("empty_columns") or []:
        raw.extraction_warnings.append(
            {
                "section": "ocr",
                "reason": "mineru_ocr_empty_column",
                "field": col.get("field"),
                "severity": "warn",
            }
        )


def downgrade_warnings_for_ocr(meta: dict[str, Any], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OCR 空列导致的 missing_field 降为 warn。"""
    ocr = (meta.get("section_extraction") or {}).get("ocr_quality") or {}
    empty_fields = {str(c.get("field")) for c in ocr.get("empty_columns") or [] if c.get("field")}
    if not empty_fields:
        return warnings

    field_to_label = {
        "学时": "学时",
        "知识点": "知识点",
        "主题": "主题",
        "授课方式": "授课方式",
        "思政元素的融入和预期教学成效": "思政元素的融入和预期教学成效",
        "授课内容": "授课内容",
    }
    downgrade_labels = {field_to_label.get(f, f) for f in empty_fields}

    adjusted: list[dict[str, Any]] = []
    for warning in warnings:
        item = dict(warning)
        if (
            item.get("reason") == "missing_field"
            and item.get("label") in downgrade_labels
            and item.get("severity") == "error"
        ):
            item["severity"] = "warn"
            item["reason"] = "mineru_ocr_empty_column"
            item["detail"] = "MD 表列存在但 OCR 单元格全空"
        adjusted.append(item)
    return adjusted


# ---------------------------------------------------------------------------
# MinerU MD 抽取器
# ---------------------------------------------------------------------------


def html_tables_from_md(md_text: str) -> list[list[list[str | None]]]:
    soup = BeautifulSoup(md_text, "html.parser")
    tables: list[list[list[str | None]]] = []
    for table in soup.find_all("table"):
        html = str(table)
        grid = html_table_to_grid(html)
        if grid:
            tables.append(grid)
    return tables


def _plain_text(md_text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", md_text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class MineruMdExtractor:
    def extract(
        self,
        md_path: Path,
        *,
        source_pdf: Path | None = None,
        middle_path: Path | None = None,
    ):
        md_text = repair_md_html(md_path.read_text(encoding="utf-8"))
        tables = html_tables_from_md(md_text)
        middle_filled = 0
        if middle_path and middle_path.exists():
            middle_grids = load_middle_grids(middle_path)
            tables, middle_filled = fill_grids_from_middle(tables, middle_grids)

        raw = build_extraction_raw(
            full_text=_plain_text(md_text),
            tables=tables,
            source_path=source_pdf or md_path,
            page_count=max(1, len(re.findall(r"^##\s+", md_text, flags=re.MULTILINE))),
            selected_source="mineru_md",
        )
        if middle_filled:
            raw.section_extraction["middle_cell_fill_count"] = middle_filled

        ocr_report = assess_ocr_quality(md_text, tables)
        apply_ocr_quality_metadata(raw, ocr_report)
        return raw
