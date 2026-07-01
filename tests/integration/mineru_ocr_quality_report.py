"""P4：批量评估 MinerU MD OCR 质量，输出重跑建议清单。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.extractors.mineru import (
    MineruMdExtractor,
    assess_ocr_quality,
    repair_md_html,
    resolve_middle_path,
)
from syllabus_auditor.core.extractors.mineru import html_table_to_grid
from bs4 import BeautifulSoup

MANIFEST = PROJECT_ROOT / "data_md" / "manifest" / "index.jsonl"
OUT_JSON = PROJECT_ROOT / "docs" / "diagnose" / "ocr_quality_report.json"
OUT_CSV = PROJECT_ROOT / "docs" / "diagnose" / "ocr_rerun_queue.csv"


def load_manifest() -> list[dict]:
    rows: list[dict] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("status") == "success":
                rows.append(row)
    return rows


def html_tables(md_text: str):
    soup = BeautifulSoup(md_text, "html.parser")
    grids = []
    for table in soup.find_all("table"):
        g = html_table_to_grid(str(table))
        if g:
            grids.append(g)
    return grids


def main() -> int:
    entries = load_manifest()
    report_rows: list[dict] = []
    rerun: list[dict] = []

    for entry in entries:
        md_path = PROJECT_ROOT / Path((entry.get("md") or "").replace("\\", "/"))
        if not md_path.exists():
            continue
        md_text = repair_md_html(md_path.read_text(encoding="utf-8"))
        tables = html_tables(md_text)
        quality = assess_ocr_quality(md_text, tables)
        middle_rel = (entry.get("json") or {}).get("middle")
        middle_path = resolve_middle_path(middle_rel, PROJECT_ROOT)
        row = {
            "stem": entry.get("stem"),
            "source_pdf": entry.get("source_pdf"),
            "md": entry.get("md"),
            "has_middle": bool(middle_path),
            **quality,
        }
        report_rows.append(row)
        if quality.get("rerun_recommended"):
            rerun.append({"stem": entry.get("stem"), "score": quality.get("score"), "issues": "|".join(quality.get("issues") or [])})

    report_rows.sort(key=lambda x: x.get("score", 0))
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({"total": len(report_rows), "rerun_count": len(rerun), "rows": report_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["stem,score,issues"]
    for item in rerun:
        lines.append(f"{json.dumps(item['stem'], ensure_ascii=False)},{item['score']},{item['issues']}")
    OUT_CSV.write_text("\n".join(lines), encoding="utf-8-sig")

    print(f"OCR quality report: {OUT_JSON}")
    print(f"Rerun queue ({len(rerun)}): {OUT_CSV}")
    if rerun:
        print("\nLowest scores:")
        for row in report_rows[:10]:
            print(f"  {row.get('score')} | {row.get('stem')[:50]} | {row.get('issues')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
