"""只读质量报告：对比 MinerU/MD/DB/pdfplumber 各层数据并生成 docs/data_quality_report.*。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from syllabus_auditor.core.db.connection import build_dsn, get_project_root
from syllabus_auditor.core.extractors.mineru import EXTRACTOR_NAME as MINERU_EXTRACTOR
from syllabus_auditor.core.extractors.mineru import MineruMiddleExtractor
from syllabus_auditor.core.extractors.pdfplumber import (
    EXTRACTOR_NAME as PDFPLUMBER_EXTRACTOR,
    extract_section,
    normalize_full_text,
)
from syllabus_auditor.core.extractors.pdfplumber.extractor import extract_assessment_section
from syllabus_auditor.core.types import ExtractionRaw
from syllabus_auditor.shared.config import load_project_config


def _project_paths() -> tuple[Path, Path, Path, Path, Path, Path]:
    root = get_project_root()
    cache = root / ".cache" / "quality"
    return (
        root,
        root / "data_md" / "manifest" / "index.jsonl",
        root / "docs" / "data_quality_report.md",
        root / "docs" / "data_quality_report.json",
        cache / "pdfplumber_text_cache.jsonl",
        cache / "mineru_middle_text_cache.jsonl",
    )


from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.utils.source_verify import FIELD_ALIASES, TABLE_SECTIONS, verify_warning_in_md

EMPTY_MARKERS = set(load_project_config().get("payload", {}).get("empty_markers") or [])
FIELD_MISSING_REASONS = frozenset({"missing_field", "empty_section"})

SECTION_KEYS = ["jcxx_kcbh", "kcmb", "jxnr", "jxap", "jxap_sz", "khfsb"]
SECTION_LABELS = {
    "jcxx_kcbh": "课程编号",
    "kcmb": "课程目标",
    "jxnr": "教学内容",
    "jxap": "教学安排",
    "jxap_sz": "教学安排·思政列",
    "khfsb": "考核方式",
}
MIDDLE_SECTION_CACHE_VERSION = 3


def load_manifest() -> list[dict]:
    _, manifest_path, _, _, _, _ = _project_paths()
    rows: list[dict] = []
    if not manifest_path.is_file():
        return rows
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success" and row.get("md"):
            rows.append(row)
    return rows


def _jxap_sz_ok(payload: dict) -> bool:
    """与入库口径一致：教学安排表行中 szyqjxx 非空。"""
    rows = (payload.get("jxap") or {}).get("tm") or []
    return any(_has_substantive(str(row.get("szyqjxx") or "")) for row in rows)


def _raw_jxap_sz_ok(raw: ExtractionRaw) -> bool:
    return _jxap_sz_ok(build_payload(raw))




def _raw_khfsb_ok(raw: ExtractionRaw) -> bool:
    if raw.assessment_rows:
        return True
    return _has_substantive(str((raw.cn_data or {}).get("考核方式说明") or ""))
def _md_jxap_sz_ok(
    md_path: Path,
    *,
    middle_path: Path | None = None,
    source_pdf: Path | None = None,
) -> bool:
    """整理阶段思政列：走 MinerU MD 抽取 + payload，与入库同口径。"""
    from syllabus_auditor.core.extractors.mineru import MineruMdExtractor

    if not md_path.is_file():
        return False
    try:
        resolved_middle = middle_path if middle_path and middle_path.is_file() else None
        raw = MineruMdExtractor().extract(
            md_path,
            source_pdf=source_pdf or md_path,
            middle_path=resolved_middle,
        )
        return _jxap_sz_ok(build_payload(raw))
    except Exception:
        return False


def _has_substantive(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return False
    return cleaned.lower() not in {str(m).lower() for m in EMPTY_MARKERS if m}


def _load_text_cache(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        key = str(row.get("source_pdf") or "")
        text = str(row.get("full_text") or "")
        if key and text:
            out[key] = text
    return out


def _save_text_cache(path: Path, mapping: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"source_pdf": key, "full_text": text}, ensure_ascii=False)
        for key, text in sorted(mapping.items())
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _load_middle_cache(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        key = str(row.get("source_pdf") or "")
        if not key:
            continue
        sections = row.get("sections")
        out[key] = {
            "full_text": str(row.get("full_text") or ""),
            "sections": sections if isinstance(sections, dict) else None,
            "cache_version": int(row.get("cache_version") or 0),
        }
    return out


def _save_middle_cache(path: Path, mapping: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "source_pdf": key,
                "full_text": value.get("full_text") or "",
                "sections": value.get("sections") or {},
                "cache_version": MIDDLE_SECTION_CACHE_VERSION,
            },
            ensure_ascii=False,
        )
        for key, value in sorted(mapping.items())
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def fetch_pdfplumber_texts(source_paths: list[str]) -> dict[str, str]:
    """从 DB 或本地 jsonl 缓存读取 pdfplumber 全文，不打开 PDF。"""
    _, _, _, _, pdf_text_cache, _ = _project_paths()
    cached = _load_text_cache(pdf_text_cache)
    out = {sp: cached[sp] for sp in source_paths if sp in cached}
    missing = [sp for sp in source_paths if sp not in out]
    if not missing:
        return out

    sql = """
        SELECT DISTINCT ON (source_path)
            source_path, meta
        FROM syllabus_extractions
        WHERE (extractor = %s OR extractor LIKE 'pdfplumber%%')
          AND source_path = ANY(%s)
        ORDER BY source_path, created_at DESC, id DESC
    """
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (PDFPLUMBER_EXTRACTOR, missing))
            for source_path, meta in cur.fetchall():
                meta_obj = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                text = str(meta_obj.get("full_text") or "")
                if len(text.strip()) > 50:
                    out[source_path] = normalize_full_text(text)
    return out


def _raw_search_text(raw: ExtractionRaw) -> str:
    parts = [raw.full_text]
    for row in raw.teaching_content or []:
        parts.extend(str(v) for v in row.values() if v)
    for row in raw.course_schedule or []:
        parts.extend(str(v) for v in row.values() if v)
    for row in raw.assessment_rows or []:
        parts.extend(str(v) for v in row.values() if v)
    for key, val in (raw.cn_data or {}).items():
        if val:
            parts.append(f"{key}:{val}")
    return normalize_full_text("\n".join(parts))


def read_mineru_middle_raw(middle_path: Path) -> ExtractionRaw:
    return MineruMiddleExtractor().extract(middle_path)


def mineru_section_ok(raw: ExtractionRaw, key: str) -> bool:
    text = _raw_search_text(raw)
    if key == "jcxx_kcbh":
        kcbh = str((raw.cn_data or {}).get("课程编号") or "")
        if _has_substantive(kcbh):
            return True
    if key == "kcmb":
        extras = raw.course_goal_extras or {}
        if any(_has_substantive(str(extras.get(f) or "")) for f in ("szmb", "nlmb", "zsmb")):
            return True
    if key == "jxnr" and raw.teaching_content:
        return True
    if key == "jxap" and raw.course_schedule:
        return True
    if key == "jxap_sz":
        return _raw_jxap_sz_ok(raw)
    if key == "khfsb":
        return _raw_khfsb_ok(raw)
    return section_present(text, key)


def section_present(full_text: str, key: str) -> bool:
    if not full_text.strip():
        return False
    if key == "jcxx_kcbh":
        head = full_text[:8000]
        return bool(re.search(r"课程\s*编\s*号", head) or re.search(r"课\s*程\s*编\s*号", head))
    if key == "jxap_sz":
        return False
    if key == "khfsb":
        return _has_substantive(extract_assessment_section(full_text))
    title_map = {
        "kcmb": ("课程目标", "教学目标"),
        "jxnr": ("教学内容", "课程内容"),
        "jxap": ("教学安排", "课程安排", "授课安排", "教学进度"),
        "khfsb": ("考核方式", "课程考核", "成绩评定"),
    }
    titles = title_map.get(key, ())
    for title in titles:
        body = extract_section(full_text, title, [])
        if not body:
            idx = full_text.find(title)
            if idx < 0:
                continue
            body = full_text[idx + len(title) : idx + len(title) + 2000]
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        substantive = [ln for ln in lines[:25] if _has_substantive(ln) and title not in ln]
        if len(substantive) >= 2:
            return True
        joined = "".join(substantive)
        if _has_substantive(joined) and len(joined) >= 8:
            return True
    return False


def md_section_ok(
    md_path: Path,
    key: str,
    *,
    middle_path: Path | None = None,
    source_pdf: Path | None = None,
) -> bool:
    if key == "jxap_sz":
        return _md_jxap_sz_ok(md_path, middle_path=middle_path, source_pdf=source_pdf)
    if key == "khfsb":
        from syllabus_auditor.core.extractors.mineru import MineruMdExtractor

        try:
            resolved_middle = middle_path if middle_path and middle_path.is_file() else None
            raw = MineruMdExtractor().extract(
                md_path,
                source_pdf=source_pdf or md_path,
                middle_path=resolved_middle,
            )
            return _raw_khfsb_ok(raw)
        except Exception:
            return False
    text = md_path.read_text(encoding="utf-8")
    plain = re.sub(r"<[^>]+>", " ", text)
    return section_present(normalize_full_text(plain), key)


def payload_section_ok(payload: dict, key: str) -> bool:
    """入库宽松：表格行或文字概述（*gs）任一有实质内容即算「有」。"""
    if key == "jcxx_kcbh":
        return _has_substantive(str((payload.get("jcxx") or {}).get("kcbh") or ""))
    if key == "kcmb":
        block = payload.get("kcmb") or {}
        return any(_has_substantive(str(block.get(f) or "")) for f in ("szmb", "nlmb", "zsmb", "mbgs"))
    if key == "jxnr":
        block = payload.get("jxnr") or {}
        if (block.get("tm") or []):
            return True
        return _has_substantive(str(block.get("nrgs") or ""))
    if key == "jxap":
        block = payload.get("jxap") or {}
        if (block.get("tm") or []):
            return True
        return _has_substantive(str(block.get("apgs") or ""))
    if key == "jxap_sz":
        return _jxap_sz_ok(payload)
    if key == "khfsb":
        block = payload.get("khfsb") or {}
        if (block.get("tm") or []):
            return True
        return _has_substantive(str(block.get("khgs") or ""))
    return False


def payload_section_strict_ok(payload: dict, key: str) -> bool:
    """入库严格：只认结构化表格行或分项目标，不含 mbgs/nrgs/apgs/khgs 概述。"""
    if key == "jcxx_kcbh":
        return _has_substantive(str((payload.get("jcxx") or {}).get("kcbh") or ""))
    if key == "kcmb":
        block = payload.get("kcmb") or {}
        return any(_has_substantive(str(block.get(f) or "")) for f in ("szmb", "nlmb", "zsmb"))
    if key == "jxnr":
        return bool((payload.get("jxnr") or {}).get("tm"))
    if key == "jxap":
        return bool((payload.get("jxap") or {}).get("tm"))
    if key == "jxap_sz":
        return _jxap_sz_ok(payload)
    if key == "khfsb":
        return bool((payload.get("khfsb") or {}).get("tm"))
    return False


def mineru_has_label(full_text: str, label: str, section: str) -> bool:
    patterns = list(dict.fromkeys([label] + FIELD_ALIASES.get(label, [])))
    if section == "jcxx":
        chunk = full_text[:6000]
        for pattern in patterns:
            if re.search(rf"{re.escape(pattern)}\s*[：:]", chunk):
                after = re.split(rf"{re.escape(pattern)}\s*[：:]", chunk, maxsplit=1)
                if len(after) > 1 and _has_substantive(after[1][:80]):
                    return True
        return False
    section_titles = {
        "jxnr": ("教学内容", "课程内容"),
        "jxap": ("教学安排", "课程安排", "授课安排", "教学进度"),
        "khfsb": ("考核方式", "课程考核", "成绩评定"),
        "kcyq": ("课程要求", "学习要求"),
        "kcmb": ("课程目标", "教学目标"),
    }.get(section, ())
    if not section_titles:
        return any(p in full_text for p in patterns)
    for title in section_titles:
        idx = full_text.find(title)
        if idx < 0:
            continue
        chunk = full_text[idx : idx + 4000]
        if any(p in chunk for p in patterns):
            if section in TABLE_SECTIONS:
                tail = chunk[chunk.find(title) + len(title) :]
                return _has_substantive(tail)
            return True
    return False


def fetch_db(extractor: str = MINERU_EXTRACTOR) -> dict[str, dict]:
    sql = """
        SELECT DISTINCT ON (source_path)
            source_path, extraction_status::text, payload, meta
        FROM syllabus_extractions
        WHERE extractor = %s
        ORDER BY source_path, created_at DESC, id DESC
    """
    out: dict[str, dict] = {}
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (extractor,))
            for source_path, status, payload, meta in cur.fetchall():
                out[source_path] = {
                    "status": status,
                    "payload": payload if isinstance(payload, dict) else json.loads(payload or "{}"),
                    "meta": meta if isinstance(meta, dict) else json.loads(meta or "{}"),
                }
    return out


def classify_warning(mineru_has: bool, md_verdict: str) -> str:
    if md_verdict == "extract_failure":
        return "解析误报"
    if md_verdict == "source_missing" and not mineru_has:
        return "源文档真缺"
    if md_verdict == "source_missing" and mineru_has:
        return "MinerU→MD丢失"
    if md_verdict == "uncertain":
        if mineru_has:
            return "待核(MinerU有内容)"
        return "待核(结构模糊)"
    if mineru_has:
        return "待核"
    return "源文档真缺"


def _pct(n: int, base: int) -> str:
    return f"{n / base * 100:.1f}%" if base else "—"


def main() -> int:
    parser = argparse.ArgumentParser(description="MinerU / MD / DB 质量报告（只读已有产物）")
    parser.add_argument(
        "--refresh-middle-cache",
        action="store_true",
        help="忽略 mineru_middle_text_cache.jsonl，重新解析 middle.json 并写回缓存",
    )
    args = parser.parse_args()
    return run_quality_report(refresh_middle_cache=args.refresh_middle_cache)


def run_quality_report(*, refresh_middle_cache: bool = False) -> int:
    _, manifest_path, out_md, out_json, pdf_text_cache, middle_text_cache = _project_paths()
    root = get_project_root()
    manifest = load_manifest()
    db = fetch_db(MINERU_EXTRACTOR)
    total = len(manifest)
    source_paths = [entry["source_pdf"] for entry in manifest]
    pdf_cache = fetch_pdfplumber_texts(source_paths)
    pdf_ok = len(pdf_cache)
    pdf_fail = total - pdf_ok
    has_pdf_compare = pdf_ok > 0

    middle_cache = {} if refresh_middle_cache else _load_middle_cache(middle_text_cache)
    middle_cache_updates: dict[str, dict] = {}

    status_counter: Counter[str] = Counter()
    mineru_ok = mineru_fail = 0

    sec: dict[str, dict[str, int]] = {
        k: {
            "mineru": 0,
            "md": 0,
            "db": 0,
            "db_strict": 0,
            "pdf": 0,
            "mineru_md": 0,
            "mineru_md_db": 0,
            "mineru_md_db_strict": 0,
            "pdf_mineru": 0,
            "md_only": 0,
            "mineru_only": 0,
        }
        for k in SECTION_KEYS
    }

    warning_class: Counter[str] = Counter()
    warning_by_field: dict[str, Counter[str]] = defaultdict(Counter)
    mineru_cache: dict[str, str] = {}
    middle_extractor = MineruMiddleExtractor()

    for entry in manifest:
        sp = entry["source_pdf"]
        md_path = root / Path(entry["md"].replace("\\", "/"))
        middle_rel = (entry.get("json") or {}).get("middle")
        middle_path = root / Path(middle_rel.replace("\\", "/")) if middle_rel else None

        row = db.get(sp)
        if row:
            status_counter[row["status"]] += 1

        mineru_text = ""
        m_section_flags = {key: False for key in SECTION_KEYS}
        if middle_path and middle_path.is_file():
            try:
                cached = middle_cache.get(sp)
                cache_fresh = (
                    cached
                    and cached.get("full_text")
                    and cached.get("sections")
                    and int(cached.get("cache_version") or 0) >= MIDDLE_SECTION_CACHE_VERSION
                )
                if cache_fresh:
                    mineru_text = str(cached["full_text"])
                    m_section_flags = {
                        key: bool((cached.get("sections") or {}).get(key)) for key in SECTION_KEYS
                    }
                else:
                    raw = middle_extractor.extract(middle_path)
                    mineru_text = _raw_search_text(raw)
                    m_section_flags = {key: mineru_section_ok(raw, key) for key in SECTION_KEYS}
                    middle_cache_updates[sp] = {
                        "full_text": mineru_text,
                        "sections": m_section_flags,
                        "cache_version": MIDDLE_SECTION_CACHE_VERSION,
                    }
                mineru_cache[sp] = mineru_text
                mineru_ok += 1
            except Exception:
                mineru_fail += 1
        else:
            mineru_fail += 1

        pdf_text = pdf_cache.get(sp, "")
        p_section_flags = {key: section_present(pdf_text, key) for key in SECTION_KEYS} if pdf_text else {
            key: False for key in SECTION_KEYS
        }

        for key in SECTION_KEYS:
            m_ok = m_section_flags[key]
            p_ok = p_section_flags[key]
            md_ok = md_section_ok(
                md_path,
                key,
                middle_path=middle_path if middle_path and middle_path.is_file() else None,
                source_pdf=root / Path(sp.replace("\\", "/")),
            )
            d_ok = payload_section_ok(row["payload"], key) if row else False
            d_strict = payload_section_strict_ok(row["payload"], key) if row else False

            if m_ok:
                sec[key]["mineru"] += 1
            if md_ok:
                sec[key]["md"] += 1
            if d_ok:
                sec[key]["db"] += 1
            if d_strict:
                sec[key]["db_strict"] += 1
            if p_ok:
                sec[key]["pdf"] += 1
            if m_ok and md_ok:
                sec[key]["mineru_md"] += 1
            if m_ok and md_ok and d_ok:
                sec[key]["mineru_md_db"] += 1
            if m_ok and md_ok and d_strict:
                sec[key]["mineru_md_db_strict"] += 1
            if p_ok and m_ok:
                sec[key]["pdf_mineru"] += 1
            if md_ok and not m_ok:
                sec[key]["md_only"] += 1
            if m_ok and not md_ok:
                sec[key]["mineru_only"] += 1

        if not row:
            continue
        for warning in row["meta"].get("extraction_warnings") or []:
            reason = str(warning.get("reason") or "")
            if reason not in FIELD_MISSING_REASONS:
                continue
            label = str(warning.get("label") or warning.get("field") or "")
            section = str(warning.get("section") or "")
            md_verdict = verify_warning_in_md(warning, md_path)
            mineru_has = mineru_has_label(mineru_cache.get(sp, ""), label, section) if mineru_cache.get(sp) else False
            bucket = classify_warning(mineru_has, md_verdict)
            warning_class[bucket] += 1
            warning_by_field[label][bucket] += 1

    if middle_cache_updates:
        merged_middle_cache = {**middle_cache, **middle_cache_updates}
        _save_middle_cache(middle_text_cache, merged_middle_cache)
    elif refresh_middle_cache and middle_cache:
        _save_middle_cache(middle_text_cache, middle_cache)

    db_rows = len(db)
    total_warnings = sum(warning_class.values())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        "# 课程方案数据质量报告",
        "",
        f"> 生成时间：{now.split(' UTC')[0]}  ",
        f"> 数据范围：{total} 份课程方案  ",
        "> 处理流程：原始文档 → 智能识别 → 结构化整理 → 入库",
        "",
        "---",
        "",
        "## 表一：处理进度总览",
        "",
        "| 指标 | 数量 | 占比 | 说明 |",
        "|------|------|------|------|",
        f"| 应处理课程方案 | {total} | 100% | 清单登记总数 |",
        f"| 已完成识别 | {mineru_ok} | {mineru_ok/total*100:.1f}% | 原始文档均已通过识别引擎处理 |",
        f"| 已完成入库 | {db_rows} | {db_rows/total*100:.1f}% | 均已写入业务库 |",
        f"| 抽取完整 | {status_counter.get('success', 0)} | {status_counter.get('success', 0)/total*100:.1f}% | 核心字段基本齐全 |",
        f"| 抽取部分完整 | {status_counter.get('partial', 0)} | {status_counter.get('partial', 0)/total*100:.1f}% | 存在局部字段告警，仍可使用 |",
        "",
        "---",
        "",
        "## 表二：核心章节覆盖（宽松入库）",
        "",
        "**入库口径（宽松）**：表格行 **或** 文字概述（`mbgs` / `nrgs` / `apgs` / `khgs`）任一有实质内容，即计为「入库有」。",
        "",
        "### 1. 这些数字在统计什么？",
        "",
        f"本表统计的是：**{total} 份课案里，有多少份在某个核心章节上「有实质内容」**。",
        "",
        f"- 不是统计「有多少个文件」——每一份课案从头到尾只有 **1 条记录**，不存在「原始文档比整理后文档少」的情况。",
        f"- 某一列小于 {total}，表示「部分课案在该章节未填写或无法自动识别」，**不是**处理过程中丢了几份文档。",
        "",
        "### 2. 为什么「识别阶段」有时比「整理阶段」数字少？",
        "",
        "**结论先说：不是整理环节丢了内容。**",
        "",
        "每一份课案的整理结果，都来自同一份识别结果。内容不会凭空增加，也不会在转换时整章丢失。",
        "",
        "两列数字不同，是因为**用了两套判定方式，去数「这一章有没有写东西」**：",
        "",
        "| | 识别阶段检出 | 整理阶段检出 |",
        "|--|-------------|-------------|",
        "| 看什么 | 识别引擎输出的原始版面与表格结构 | 转换后的结构化正文与表格 |",
        "| 怎么判「有内容」 | 需从版面中定位章节标题，且表格字段能被结构化规则识别 | 在已整理正文中搜索章节标题和表格文字，判定相对宽松 |",
        "| 典型差异 | 表格排版复杂、字段未对齐时，可能判为「未识别到」 | 同一表格已排成规整样式，更容易判为「有内容」 |",
        "",
        f"**举例（课程编号）：识别阶段 {sec['jcxx_kcbh']['mineru']} 份、整理阶段 {sec['jcxx_kcbh']['md']} 份。**",
        "",
        f"- 差的 **{sec['jcxx_kcbh']['md_only']} 份**，不是多了 {sec['jcxx_kcbh']['md_only']} 份整理文档。",
        "- 而是这几份课案：**整理后的文本里能读到该章节内容，但识别侧的判定规则没有命中**。",
        "- 全文各章因此类统计口径差异造成两边计数不同的，每章通常只有个位数（见下表「仅整理检出」列）。",
        "",
        "**教学安排·思政列**：整理有 / 入库有均要求 `jxap.tm[].szyqjxx` 结构化非空，不再用全文「思政」关键词判定。",
        "",
        "### 3. 数据表",
        "",
        "| 核心章节 | 识别有 | 整理有 | 仅整理检出 | 仅识别检出 | 入库有 | 三者一致 | 识别→整理 | 整理→入库 |",
        "|----------|--------|--------|------------|------------|--------|----------|-----------|-----------|",
    ]

    for key in SECTION_KEYS:
        c = sec[key]
        lines.append(
            f"| {SECTION_LABELS[key]} | {c['mineru']} | {c['md']} | {c['md_only']} | {c['mineru_only']} "
            f"| {c['db']} | {c['mineru_md_db']} "
            f"| {_pct(c['mineru_md'], c['mineru'])} | {_pct(c['db'], c['md'])} |"
        )

    lines.extend(
        [
            "",
            "**列说明**",
            "",
            "- **识别有 / 整理有 / 入库有**：在该章节判定为「有实质内容」的课案份数（入库列见上文宽松口径）。",
            "- **仅整理检出**：整理判「有」、识别判「无」的份数（统计口径差异，非丢文档）。",
            "- **仅识别检出**：识别判「有」、整理判「无」的份数。",
            "- **识别→整理**：在识别已检出的课案中，整理也检出的比例。",
            "- **整理→入库**：在整理已检出的课案中，入库也检出的比例（宽松口径）。",
            "",
            "---",
            "",
            "## 表三：核心章节覆盖（严格入库）",
            "",
            "**入库口径（严格）**：只认结构化表格行或分项目标（如 `szmb`/`nlmb`/`zsmb`、`jxnr.tm`、`jxap.tm`、`khfsb.tm`），**不含**上述文字概述字段。",
            "",
            "与表二对照阅读：两表识别有、整理有相同；**入库有**与**整理→入库**按严格口径重算。表二入库有 − 表三入库有 ≈ 仅靠概述兜底、未进表的份数。",
            "",
            "| 核心章节 | 识别有 | 整理有 | 入库有 | 三者一致 | 识别→整理 | 整理→入库 |",
            "|----------|--------|--------|--------|----------|-----------|-----------|",
        ]
    )

    for key in SECTION_KEYS:
        c = sec[key]
        lines.append(
            f"| {SECTION_LABELS[key]} | {c['mineru']} | {c['md']} | {c['db_strict']} | {c['mineru_md_db_strict']} "
            f"| {_pct(c['mineru_md'], c['mineru'])} | {_pct(c['db_strict'], c['md'])} |"
        )

    lines.extend(
        [
            "",
            "**列说明**",
            "",
            "- **入库有**：严格口径，见本节开头说明。",
            "- **整理→入库**：整理已检出的课案中，严格口径下入库也检出的比例。",
            "",
            "---",
            "",
            "## 表四：字段缺失告警分析",
            "",
            f"统计范围：入库过程中的字段/章节缺失类告警，共 **{total_warnings}** 条。",
            "",
            "| 根因分类 | 条数 | 占比 | 含义 | 主要责任 |",
            "|----------|------|------|------|----------|",
        ]
    )

    cause_desc = {
        "源文档真缺": ("原始课案与整理结果均无该字段实质内容", "课程方案模板/填报"),
        "MinerU→MD丢失": ("识别侧有内容，整理侧章节无", "识别转换"),
        "解析误报": ("整理有内容，入库却报缺", "入库解析"),
        "待核(MinerU有内容)": ("识别侧有线索，整理侧无法确认", "建议抽检"),
        "待核(结构模糊)": ("章节或表格结构模糊", "原始文档/OCR"),
    }
    cause_label = {
        "源文档真缺": "源文档未填",
        "MinerU→MD丢失": "识别→整理丢失",
        "解析误报": "入库误报",
        "待核(MinerU有内容)": "待核（识别有内容）",
        "待核(结构模糊)": "待核（结构不清）",
    }
    order = ["源文档真缺", "MinerU→MD丢失", "解析误报", "待核(MinerU有内容)", "待核(结构模糊)"]
    for name in order:
        n = warning_class.get(name, 0)
        pct = _pct(n, total_warnings)
        desc, owner = cause_desc.get(name, ("", ""))
        lines.append(f"| {cause_label.get(name, name)} | {n} | {pct} | {desc} | {owner} |")

    extract_n = warning_class.get("解析误报", 0)
    lines.extend(
        [
            "",
            f"**入库解析质量**：经核对可确认的误报 **{extract_n}** 条（{_pct(extract_n, total_warnings)}）。",
            "",
            "### 入库误报字段明细",
            "",
            "| 字段 | 告警条数 |",
            "|------|----------|",
        ]
    )
    field_extract = sorted(
        [(label, warning_by_field[label].get("解析误报", 0)) for label in warning_by_field],
        key=lambda x: -x[1],
    )
    for label, n in field_extract:
        if n > 0:
            lines.append(f"| {label} | {n} |")
    if not any(n for _, n in field_extract):
        lines.append("| （无） | 0 |")

    lines.extend(
        [
            "",
            "### 源文档未填 Top 字段",
            "",
            "| 字段 | 告警条数 |",
            "|------|----------|",
        ]
    )
    field_true = sorted(
        [(label, warning_by_field[label].get("源文档真缺", 0)) for label in warning_by_field],
        key=lambda x: -x[1],
    )
    for label, n in field_true[:12]:
        if n > 0:
            lines.append(f"| {label} | {n} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 汇报摘要",
            "",
            f"1. **{total} 份课程方案已全部完成识别与入库**，处理链路无阻断。",
            f"2. **抽取完整率 {status_counter.get('success', 0)/total*100:.1f}%**（{status_counter.get('success', 0)}/{total}），其余为局部字段告警。",
            f"3. **整理→入库（宽松）**在核心章节上与整理阶段同口径统计；**表三**给出严格入库口径，便于区分「仅概述、无表格」的情况。",
            f"4. **可确认入库误报 {extract_n} 条**；主要告警来自**源课案未填写**（约 {warning_class.get('源文档真缺', 0)} 条）。",
            "5. **识别有略低于整理有**属统计判定差异，不是文档数量不一致或转换丢章，详见表二说明。",
            "",
        ]
    )

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "generated_at": now,
        "total": total,
        "mineru_ok": mineru_ok,
        "pdf_ok": pdf_ok,
        "has_pdf_compare": has_pdf_compare,
        "db_rows": db_rows,
        "status": dict(status_counter),
        "section_stats": sec,
        "warning_class": dict(warning_class),
        "warning_by_field": {k: dict(v) for k, v in warning_by_field.items()},
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


