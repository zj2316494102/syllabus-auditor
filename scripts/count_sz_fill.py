import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syllabus_auditor.core.extractors.pdfplumber import PdfPlumberExtractor
from syllabus_auditor.core.payload_builder import build_payload, _promote_schedule_sz_cn
from syllabus_auditor.loaders.syllabus_pdf import list_pdf_files
from syllabus_auditor.core.db.connection import get_project_root

ext = PdfPlumberExtractor()
pdfs = list_pdf_files(get_project_root() / "data")[:200]
raw_sz_rows = 0
payload_sz_rows = 0
total_sched_rows = 0
for pdf in pdfs:
    raw = ext.extract(pdf)
    pl = build_payload(raw)
    for row in raw.course_schedule:
        total_sched_rows += 1
        p = _promote_schedule_sz_cn(dict(row))
        if str(p.get("思政元素的融入和预期教学成效") or "").strip():
            raw_sz_rows += 1
    for row in (pl.get("jxap") or {}).get("tm") or []:
        if str(row.get("szyqjxx") or "").strip():
            payload_sz_rows += 1
print("total schedule rows", total_sched_rows)
print("raw cn sz filled", raw_sz_rows)
print("payload szyqjxx filled", payload_sz_rows)
print("missing at payload", total_sched_rows - payload_sz_rows)
