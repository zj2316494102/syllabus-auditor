"""MinerU-only：MD → 入库（不经过 pdfplumber / fusion）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.db.connection import get_project_root  # noqa: E402
from syllabus_auditor.core.db.extractions import ExtractionStore  # noqa: E402
from syllabus_auditor.core.extractors.mineru_md import EXTRACTOR_NAME, MineruMdExtractor  # noqa: E402
from syllabus_auditor.core.meta_builder import build_meta, relative_source_path  # noqa: E402
from syllabus_auditor.core.payload_builder import build_payload  # noqa: E402
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert  # noqa: E402
from syllabus_auditor.core.status import judge_extraction_status  # noqa: E402

MANIFEST = PROJECT_ROOT / "data_change" / "manifest" / "index.jsonl"


def load_success_entries() -> list[dict]:
    rows: list[dict] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success":
            rows.append(row)
    return rows


def main() -> int:
    root = get_project_root()
    entries = load_success_entries()
    extractor = MineruMdExtractor()
    store = ExtractionStore()
    stats = {"success": 0, "partial": 0, "failed": 0, "errors": 0}

    for entry in entries:
        source_pdf_rel = entry["source_pdf"]
        pdf_path = root / Path(source_pdf_rel.replace("\\", "/"))
        md_rel = entry.get("md") or ""
        md_path = root / Path(md_rel.replace("\\", "/"))
        if not md_path.exists():
            stats["errors"] += 1
            print(f"SKIP missing md: {md_rel}")
            continue
        try:
            raw = extractor.extract(md_path, source_pdf=pdf_path)
            payload = build_payload(raw)
            rel_path = relative_source_path(pdf_path.resolve(), root)
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
            stats[status if status in stats else "failed"] += 1
            jxap = len((payload.get("jxap") or {}).get("tm") or [])
            sz = sum(
                1
                for row in (payload.get("jxap") or {}).get("tm") or []
                if str(row.get("szyqjxx") or "").strip()
            )
            print(f"OK {entry['stem'][:40]} | {status} | jxap={jxap} sz={sz} | kcbh={course_code}")
        except Exception as exc:
            stats["errors"] += 1
            print(f"FAIL {entry['stem']}: {exc}")

    print(f"\nDone: {stats} / {len(entries)} docs")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
