"""应用层总入口，聚合 prepare / audit / report 三大流水线。"""


from syllabus_auditor.application.audit import run_audit_batch
from syllabus_auditor.application.prepare import (
    run_prepare_course_library,
    run_prepare_courses,
    run_prepare_mineru,
)
from syllabus_auditor.application.report import run_quality_report

__all__ = [
    "run_audit_batch",
    "run_prepare_course_library",
    "run_prepare_courses",
    "run_prepare_mineru",
    "run_quality_report",
]
