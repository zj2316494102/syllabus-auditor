"""诊断：缺 szyqjxx 时 raw 行里有什么。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syllabus_auditor.core.extractors.pdfplumber import PdfPlumberExtractor
from syllabus_auditor.core.payload_builder import build_payload, _promote_schedule_sz_cn
from syllabus_auditor.loaders.syllabus_pdf import list_pdf_files
from syllabus_auditor.core.db.connection import get_project_root

extractor = PdfPlumberExtractor()
root = get_project_root()
pdfs = list_pdf_files(root / "data")[:200]

missing_samples = 0
raw_has_sz = 0
raw_kzzd_has_sz = 0
promote_filled = 0

for pdf in pdfs:
    raw = extractor.extract(pdf)
    payload = build_payload(raw)
    rows = (payload.get("jxap") or {}).get("tm") or []
    if not rows:
        continue
    miss = [r for r in rows if not str(r.get("szyqjxx") or "").strip()]
    if not miss:
        continue
    missing_samples += 1
    if missing_samples > 5:
        break
    print("===", pdf.name, "missing rows", len(miss), "/", len(rows))
    for i, cn_row in enumerate(raw.course_schedule[:3]):
        promoted = _promote_schedule_sz_cn(dict(cn_row))
        sz = promoted.get("思政元素的融入和预期教学成效", "")
        kzzd = cn_row.get("kzzd")
        print(f"  raw[{i}] keys:", list(cn_row.keys()))
        if sz:
            raw_has_sz += 1
            print("  promoted sz:", sz[:60])
        if isinstance(kzzd, dict):
            for k, v in list(kzzd.items())[:3]:
                print(f"  kzzd[{k!r}]:", str(v)[:50])
                if any(t in k for t in ("思政", "成效", "课程思政")):
                    raw_kzzd_has_sz += 1

print("\nSamples inspected:", missing_samples)
