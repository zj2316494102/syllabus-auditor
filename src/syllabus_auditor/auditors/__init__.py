"""审核维度实现包入口。"""


from syllabus_auditor.auditors.jxmbnrfsfhyq import audit_jxmbnrfsfhyq, build_audit_input as build_jxmbnrfsfhyq_audit_input
from syllabus_auditor.auditors.registry import AUDITORS, AUDITOR_BY_KEY, AuditorSpec, run_auditor
from syllabus_auditor.auditors.runner import run_batch_audit
from syllabus_auditor.auditors.szysfyxrghj import audit_szysfyxrghj, build_audit_input as build_szysfyxrghj_audit_input
from syllabus_auditor.auditors.xxyzwzfhmb import audit_xxyzwzfhmb

__all__ = [
    "AUDITORS",
    "AUDITOR_BY_KEY",
    "AuditorSpec",
    "audit_jxmbnrfsfhyq",
    "audit_szysfyxrghj",
    "audit_xxyzwzfhmb",
    "build_jxmbnrfsfhyq_audit_input",
    "build_szysfyxrghj_audit_input",
    "run_auditor",
    "run_batch_audit",
]
