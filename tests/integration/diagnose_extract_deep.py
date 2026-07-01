"""深度诊断：对比 MD 表格与抽取结果。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.extractors.mineru import MineruMdExtractor
from syllabus_auditor.core.extractors.section_table_parser import _detect_header, PROFILES
from syllabus_auditor.core.extractors.mineru import html_table_to_grid

MANIFEST = PROJECT_ROOT / "data_md" / "manifest" / "index.jsonl"
OUT = PROJECT_ROOT / "docs" / "diagnose" / "extract_failure_deep.json"

SAMPLE_DOCS = [
    "2025-2026-2会计与审计理论研究课程方案",
    "吉利陈磊-高级管理会计理论与实务1",
    "课程方案-实证会计研究",
    "2025-2026-2《美育教育课程》博士层次课程实施方案",
    "2025-2026-2《现代逻辑》课程实施方案_朱敏",
    "课程方案模板（研究生沙盘）-20260413",
    "唐雪松教授-财务决策与控制v2",
    "2026《内部控制与风险管理》课程方案（全日制）",
    "财务理论2026教学实施方案-科硕",
    "李贺教授-数智审计原理与方法1",
    "课程方案模板2026-04-13",
    "审计专题研究-课程方案模板2026-04-21",
]


def load_manifest() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") == "success" and row.get("source_pdf") and row.get("md"):
            mapping[Path(row["source_pdf"]).stem] = row["md"]
    return mapping


def extract_jxnr_jxap_tables(md_text: str) -> dict[str, list]:
    """按章节标题切分，提取 HTML 表格 grid。"""
    parts = re.split(r"(^##\s+.+$)", md_text, flags=re.MULTILINE)
    chunks = []
    i = 1
    if parts and not parts[0].strip().startswith("##"):
        chunks.append(("_preamble", parts[0]))
    while i + 1 < len(parts):
        header = re.sub(r"^#+\s*", "", parts[i]).strip()
        chunks.append((header, parts[i + 1]))
        i += 2

    result = {}
    for header, body in chunks:
        if any(k in header for k in ("教学内容", "课程内容", "讲授内容")):
            key = "jxnr"
        elif any(k in header for k in ("教学安排", "课程安排", "授课安排", "教学进度")):
            key = "jxap"
        elif any(k in header for k in ("考核方式", "课程考核", "成绩评定")):
            key = "khfsb"
        elif any(k in header for k in ("课程基本信息", "基本信息")):
            key = "jcxx"
        elif any(k in header for k in ("课程目标", "教学目标")):
            key = "kcmb"
        else:
            continue
        soup = BeautifulSoup(body, "html.parser")
        tables = []
        for table in soup.find_all("table"):
            grids = html_table_to_grid(str(table))
            if grids:
                tables.append(grids)
        if tables:
            result.setdefault(key, []).extend(tables)
    return result


def analyze_table_headers(table: list[list], profile_name: str) -> dict:
    profile = next(p for p in PROFILES if p.name == profile_name)
    active, start, warnings = _detect_header(table, None)
    header_info = []
    if active:
        for idx, hdr in sorted(active.headers.items()):
            field = active.col_map.get(idx)
            header_info.append({"col": idx, "header": hdr, "field": field})
    return {
        "start_row": start,
        "col_map": active.col_map if active else {},
        "headers": header_info,
        "warnings": warnings,
        "first_data_rows": table[start:start + 4] if active else table[:4],
    }


def main() -> int:
    pdf_to_md = load_manifest()
    extractor = MineruMdExtractor()
    results = {}

    for stem in SAMPLE_DOCS:
        md_rel = pdf_to_md.get(stem)
        if not md_rel:
            # 尝试部分匹配
            for k, v in pdf_to_md.items():
                if stem in k or k in stem:
                    md_rel = v
                    break
        if not md_rel:
            results[stem] = {"error": "no md"}
            continue
        md_path = PROJECT_ROOT / Path(md_rel.replace("\\", "/"))
        md_text = md_path.read_text(encoding="utf-8")
        raw = extractor.extract(md_path)
        section_tables = extract_jxnr_jxap_tables(md_text)

        doc_result = {
            "jxnr_rows": len(raw.teaching_content),
            "jxap_rows": len(raw.course_schedule),
            "jxnr_sample": raw.teaching_content[:3],
            "jxap_sample": raw.course_schedule[:3],
            "basic_info": {k: v for k, v in (raw.basic_info or {}).items() if v},
            "course_goals": {k: v for k, v in (raw.course_goals or {}).items() if v},
        }

        if "jxnr" in section_tables:
            doc_result["jxnr_tables"] = [
                analyze_table_headers(t, "教学内容") for t in section_tables["jxnr"][:2]
            ]
        if "jxap" in section_tables:
            doc_result["jxap_tables"] = [
                analyze_table_headers(t, "教学安排") for t in section_tables["jxap"][:2]
            ]
        if "jcxx" in section_tables:
            doc_result["jcxx_tables"] = section_tables["jcxx"][:1]
        if "kcmb" in section_tables:
            doc_result["kcmb_section"] = md_text[md_text.find("课程目标"):md_text.find("课程目标")+500] if "课程目标" in md_text else ""

        results[stem] = doc_result

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
