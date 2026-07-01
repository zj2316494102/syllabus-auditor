"""MinerU MD 入库流水线：读取 manifest → 抽取 → 写入 syllabus_extractions。"""

from __future__ import annotations

import json
from pathlib import Path

from syllabus_auditor.core.db.connection import get_project_root
from syllabus_auditor.core.db.extractions import ExtractionStore
from syllabus_auditor.core.extractors.mineru import EXTRACTOR_NAME, MineruMdExtractor
from syllabus_auditor.core.meta_builder import build_meta, relative_source_path
from syllabus_auditor.core.payload_builder import build_payload
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert
from syllabus_auditor.core.status import judge_extraction_status
from syllabus_auditor.shared.logging import get_logger

logger = get_logger(__name__)


def _manifest_path(root: Path) -> Path:
    return root / "data_md" / "manifest" / "index.jsonl"


def load_success_entries(manifest: Path) -> list[dict]:
    rows: list[dict] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success":
            rows.append(row)
    return rows


def run_prepare_mineru(*, manifest: Path | None = None) -> dict[str, int]:
    """读取 MinerU manifest，抽取并写入 syllabus_extractions。"""
    root = get_project_root()
    manifest_path = manifest or _manifest_path(root)
    entries = load_success_entries(manifest_path)
    extractor = MineruMdExtractor()
    store = ExtractionStore()
    stats = {"success": 0, "partial": 0, "failed": 0, "errors": 0}

    logger.info("prepare_mineru_start", extra={"total": len(entries), "manifest": str(manifest_path)})

    for entry in entries:
        source_pdf_rel = entry["source_pdf"]
        pdf_path = root / Path(source_pdf_rel.replace("\\", "/"))
        md_rel = entry.get("md") or ""
        if not md_rel.strip():
            stats["errors"] += 1
            logger.warning("prepare_mineru_skip", extra={"reason": "missing_md", "stem": entry.get("stem", "")})
            continue
        md_path = root / Path(md_rel.replace("\\", "/"))
        if not md_path.is_file():
            stats["errors"] += 1
            logger.warning("prepare_mineru_skip", extra={"reason": "md_not_found", "md": md_rel})
            continue
        try:
            middle_rel = (entry.get("json") or {}).get("middle")
            middle_path = None
            if middle_rel:
                candidate = root / Path(middle_rel.replace("\\", "/"))
                if candidate.exists():
                    middle_path = candidate
            raw = extractor.extract(md_path, source_pdf=pdf_path, middle_path=middle_path)
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
            logger.info(
                "prepare_mineru_ok",
                extra={
                    "stem": entry.get("stem", "")[:40],
                    "status": status,
                    "course_code": course_code,
                },
            )
        except Exception as exc:
            stats["errors"] += 1
            logger.exception("prepare_mineru_fail", extra={"stem": entry.get("stem", ""), "error": str(exc)})

    logger.info("prepare_mineru_done", extra={"stats": stats, "total": len(entries)})
    return stats
