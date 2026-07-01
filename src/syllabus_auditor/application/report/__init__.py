"""报告流水线包入口。"""


from syllabus_auditor.application.report.quality import main as quality_report_main
from syllabus_auditor.application.report.quality import run_quality_report

__all__ = ["quality_report_main", "run_quality_report"]
