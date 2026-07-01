"""将 MinerU MD 入库，并与 PDF 原文、现有 pdfplumber 抽取结果对比。"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.shared.config import load_project_config  # noqa: E402
from syllabus_auditor.core.db.connection import build_dsn, get_project_root  # noqa: E402
from syllabus_auditor.core.db.extractions import ExtractionStore  # noqa: E402
from syllabus_auditor.core.extractors.mineru import EXTRACTOR_NAME, MineruMdExtractor  # noqa: E402
from syllabus_auditor.core.meta_builder import build_meta, relative_source_path  # noqa: E402
from syllabus_auditor.core.payload_builder import build_payload  # noqa: E402
from syllabus_auditor.core.quality import prepare_payload_and_meta_for_insert  # noqa: E402
from syllabus_auditor.core.status import judge_extraction_status  # noqa: E402

MANIFEST = PROJECT_ROOT / "data_md" / "manifest" / "index.jsonl"
OUT_JSON = PROJECT_ROOT / "docs" / "diagnose" / "mineru_md_vs_pdf_vs_db.json"
OUT_CSV = PROJECT_ROOT / "docs" / "diagnose" / "mineru_md_vs_pdf_vs_db.csv"

EMPTY_MARKERS = set(load_project_config().get("payload", {}).get("empty_markers", []))


def load_manifest_success() -> list[dict]:
    rows: list[dict] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "success":
            rows.append(row)
    return rows


def read_pdf_text(pdf_path: Path) -> str:
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
    return "\n".join(parts)


def _has_substantive(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return False
    return cleaned.lower() not in {m.lower() for m in EMPTY_MARKERS if m}


def pdf_section_present(full_text: str, *titles: str) -> bool:
    for title in titles:
        idx = full_text.find(title)
        if idx < 0:
            continue
        chunk = full_text[idx : idx + 2000]
        body = chunk[len(title) :].strip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        substantive = [ln for ln in lines[:20] if _has_substantive(ln) and title not in ln]
        if len(substantive) >= 2:
            return True
        joined = "".join(substantive)
        if _has_substantive(joined) and len(joined) >= 8:
            return True
    return False


def payload_metrics(payload: dict) -> dict:
    jcxx = payload.get("jcxx") or {}
    jxap_rows = (payload.get("jxap") or {}).get("tm") or []
    kh_rows = (payload.get("khfsb") or {}).get("tm") or []
    jxnr_rows = (payload.get("jxnr") or {}).get("tm") or []
    sz_filled = sum(1 for row in jxap_rows if _has_substantive(str(row.get("szyqjxx") or "")))
    skfs_filled = sum(1 for row in jxap_rows if _has_substantive(str(row.get("skfs") or "")))
    return {
        "kcbh": str(jcxx.get("kcbh") or ""),
        "zwkcmc": str(jcxx.get("zwkcmc") or ""),
        "jxnr_rows": len(jxnr_rows),
        "jxap_rows": len(jxap_rows),
        "jxap_sz_filled": sz_filled,
        "jxap_skfs_filled": skfs_filled,
        "khfsb_rows": len(kh_rows),
        "has_kcmb": bool(
            _has_substantive(str((payload.get("kcmb") or {}).get("szmb") or ""))
            or _has_substantive(str((payload.get("kcmb") or {}).get("mbgs") or ""))
        ),
    }


def fetch_db_latest(source_paths: list[str]) -> dict[str, dict]:
    if not source_paths:
        return {}
    sql = """
        SELECT DISTINCT ON (source_path)
            source_path, extractor, extraction_status::text, payload, meta
        FROM syllabus_extractions
        WHERE source_path = ANY(%s)
        ORDER BY source_path, created_at DESC, id DESC
    """
    out: dict[str, dict] = {}
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (source_paths,))
            for source_path, extractor, status, payload, meta in cur.fetchall():
                out[source_path] = {
                    "extractor": extractor,
                    "status": status,
                    "payload": payload if isinstance(payload, dict) else json.loads(payload or "{}"),
                    "meta": meta if isinstance(meta, dict) else json.loads(meta or "{}"),
                }
    return out


def fetch_db_overview() -> dict:
    with psycopg.connect(build_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM syllabus_extractions")
            total = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT extraction_status::text, COUNT(*)
                FROM syllabus_extractions
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
            by_status = dict(cur.fetchall())
            cur.execute(
                """
                SELECT extractor, COUNT(*)
                FROM syllabus_extractions
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
            by_extractor = dict(cur.fetchall())
    return {"total_rows": total, "by_status": by_status, "by_extractor": by_extractor}


def compare_row(pdf_metrics: dict, md_metrics: dict, db_metrics: dict | None) -> dict:
    def cmp_field(field: str, pdf_key: str, md_key: str, db_key: str) -> str:
        pdf_ok = bool(pdf_metrics.get(pdf_key))
        md_ok = bool(md_metrics.get(md_key)) if isinstance(md_metrics.get(md_key), (int, float)) else _has_substantive(str(md_metrics.get(md_key) or ""))
        db_ok = bool(db_metrics.get(db_key)) if db_metrics and isinstance(db_metrics.get(db_key), (int, float)) else _has_substantive(str((db_metrics or {}).get(db_key) or ""))
        if pdf_ok and md_ok and (not db_metrics or db_ok):
            return "三方一致"
        if pdf_ok and md_ok and db_metrics and not db_ok:
            return "DB缺失/弱于MD"
        if pdf_ok and not md_ok and db_ok:
            return "MD缺失/弱于DB"
        if pdf_ok and md_ok and not db_ok:
            return "DB缺失"
        if pdf_ok and not md_ok and not db_ok:
            return "抽取均弱"
        if not pdf_ok:
            return "PDF亦无/难验证"
        return "待核"

    return {
        "kcbh": cmp_field("kcbh", "has_kcbh", "kcbh", "kcbh"),
        "jxap": cmp_field("jxap", "has_jxap", "jxap_rows", "jxap_rows"),
        "sz": cmp_field("sz", "has_sz", "jxap_sz_filled", "jxap_sz_filled"),
        "khfsb": cmp_field("khfsb", "has_khfsb", "khfsb_rows", "khfsb_rows"),
    }


def main() -> int:
    root = get_project_root()
    manifest_rows = load_manifest_success()
    source_paths = [row["source_pdf"] for row in manifest_rows]

    db_overview = fetch_db_overview()
    db_latest = fetch_db_latest(source_paths)

    extractor = MineruMdExtractor()
    store = ExtractionStore()

    rows: list[dict] = []
    md_status_counter: Counter[str] = Counter()
    load_stats = {"inserted": 0, "errors": 0}

    for entry in manifest_rows:
        source_pdf_rel = entry["source_pdf"]
        pdf_path = root / source_pdf_rel.replace("/", "\\") if "\\" not in source_pdf_rel else root / source_pdf_rel
        if not pdf_path.exists():
            pdf_path = root / Path(source_pdf_rel)

        md_rel = entry["md"]
        md_path = root / md_rel.replace("/", "\\")
        if not md_path.exists():
            md_path = root / Path(md_rel)

        row: dict = {
            "stem": entry["stem"],
            "source_pdf": source_pdf_rel,
            "md_path": md_rel,
        }

        try:
            pdf_text = read_pdf_text(pdf_path)
            pdf_metrics = {
                "has_kcbh": bool(re.search(r"课程编号\s*[：:]", pdf_text)),
                "has_jxap": pdf_section_present(pdf_text, "教学安排", "授课安排", "课程安排"),
                "has_sz": "思政" in pdf_text and pdf_section_present(pdf_text, "教学安排", "授课安排"),
                "has_khfsb": pdf_section_present(pdf_text, "考核方式", "成绩评定", "课程考核"),
                "text_len": len(pdf_text),
            }
        except Exception as exc:
            pdf_metrics = {"error": f"{type(exc).__name__}: {exc}"}

        try:
            raw = extractor.extract(md_path, source_pdf=pdf_path)
            payload = build_payload(raw)
            meta = build_meta(raw, relative_source_path(pdf_path.resolve(), root))
            payload, meta = prepare_payload_and_meta_for_insert(payload, meta)
            md_status = judge_extraction_status(payload, meta)
            md_status_counter[md_status] += 1
            md_metrics = payload_metrics(payload)
            md_metrics["status"] = md_status
            md_metrics["warnings"] = len(meta.get("extraction_warnings") or [])

            course_code = (payload.get("jcxx") or {}).get("kcbh") or ""
            store.insert(
                course_code=course_code,
                source_path=relative_source_path(pdf_path.resolve(), root),
                payload=payload,
                meta=meta,
                extractor=EXTRACTOR_NAME,
                extraction_status=md_status,
            )
            load_stats["inserted"] += 1
        except Exception as exc:
            load_stats["errors"] += 1
            md_metrics = {"error": f"{type(exc).__name__}: {exc}", "status": "failed"}
            md_status_counter["failed"] += 1

        db_row = db_latest.get(source_pdf_rel)
        if db_row:
            db_payload = db_row["payload"]
            db_metrics = payload_metrics(db_payload)
            db_metrics["status"] = db_row["status"]
            db_metrics["extractor"] = db_row["extractor"]
            db_metrics["warnings"] = len((db_row.get("meta") or {}).get("extraction_warnings") or [])
        else:
            db_metrics = None

        row["pdf"] = pdf_metrics
        row["mineru_md"] = md_metrics
        row["db_latest"] = db_metrics
        if isinstance(md_metrics, dict) and isinstance(db_metrics, dict) and "error" not in md_metrics:
            row["compare"] = compare_row(
                pdf_metrics if "error" not in pdf_metrics else {},
                md_metrics,
                db_metrics,
            )
        rows.append(row)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "db_overview": db_overview,
        "db_coverage_for_50": {
            "with_any_record": sum(1 for p in source_paths if p in db_latest),
            "without_record": sum(1 for p in source_paths if p not in db_latest),
        },
        "mineru_md_load": load_stats,
        "mineru_md_status": dict(md_status_counter),
        "compare_counts": {
            "md_better_jxap": sum(
                1
                for r in rows
                if isinstance(r.get("mineru_md"), dict)
                and isinstance(r.get("db_latest"), dict)
                and r["mineru_md"].get("jxap_rows", 0) > r["db_latest"].get("jxap_rows", 0)
            ),
            "md_better_sz": sum(
                1
                for r in rows
                if isinstance(r.get("mineru_md"), dict)
                and isinstance(r.get("db_latest"), dict)
                and r["mineru_md"].get("jxap_sz_filled", 0) > r["db_latest"].get("jxap_sz_filled", 0)
            ),
            "md_better_kh": sum(
                1
                for r in rows
                if isinstance(r.get("mineru_md"), dict)
                and isinstance(r.get("db_latest"), dict)
                and r["mineru_md"].get("khfsb_rows", 0) > r["db_latest"].get("khfsb_rows", 0)
            ),
            "md_success_vs_db": sum(
                1
                for r in rows
                if r.get("mineru_md", {}).get("status") == "success"
                and (r.get("db_latest") or {}).get("status") != "success"
            ),
        },
        "rows": rows,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_lines = [
        "stem,pdf_has_jxap,pdf_has_sz,pdf_has_khfsb,md_status,md_jxap_rows,md_sz_filled,md_kh_rows,db_status,db_extractor,db_jxap_rows,db_sz_filled,db_kh_rows,cmp_jxap,cmp_sz,cmp_kh"
    ]
    for r in rows:
        pdf = r.get("pdf") or {}
        md = r.get("mineru_md") or {}
        db = r.get("db_latest") or {}
        cmp_ = r.get("compare") or {}
        csv_lines.append(
            ",".join(
                [
                    json.dumps(r["stem"], ensure_ascii=False),
                    str(pdf.get("has_jxap", "")),
                    str(pdf.get("has_sz", "")),
                    str(pdf.get("has_khfsb", "")),
                    str(md.get("status", "")),
                    str(md.get("jxap_rows", "")),
                    str(md.get("jxap_sz_filled", "")),
                    str(md.get("khfsb_rows", "")),
                    str(db.get("status", "")),
                    str(db.get("extractor", "")),
                    str(db.get("jxap_rows", "")),
                    str(db.get("jxap_sz_filled", "")),
                    str(db.get("khfsb_rows", "")),
                    str(cmp_.get("jxap", "")),
                    str(cmp_.get("sz", "")),
                    str(cmp_.get("khfsb", "")),
                ]
            )
        )
    OUT_CSV.write_text("\n".join(csv_lines), encoding="utf-8-sig")

    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
