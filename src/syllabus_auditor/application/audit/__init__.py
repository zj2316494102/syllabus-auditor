"""审核流水线包入口。"""


from syllabus_auditor.application.audit.batch import run_audit_batch

__all__ = ["run_audit_batch"]
