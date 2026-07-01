"""批处理审核应用层封装，带结构化日志。"""


from __future__ import annotations

from syllabus_auditor.auditors.runner import run_batch_audit
from syllabus_auditor.core.audit import AuditRunSummary
from syllabus_auditor.shared.logging import get_logger

logger = get_logger(__name__)


def run_audit_batch(
    *,
    run_name: str | None = None,
    import_term: str | None = None,
    latest_only: bool = True,
    limit: int | None = None,
    resume_run_id: int | None = None,
) -> AuditRunSummary:
    logger.info(
        "audit_batch_start",
        extra={
            "run_name": run_name,
            "import_term": import_term,
            "latest_only": latest_only,
            "limit": limit,
            "resume_run_id": resume_run_id,
        },
    )
    summary = run_batch_audit(
        run_name=run_name,
        import_term=import_term,
        latest_only=latest_only,
        limit=limit,
        resume_run_id=resume_run_id,
    )
    logger.info(
        "audit_batch_done",
        extra={
            "run_id": summary.run_id,
            "total": summary.total,
            "pass_count": summary.pass_count,
            "fail_count": summary.fail_count,
            "partial_count": summary.partial_count,
            "error_count": summary.error_count,
        },
    )
    return summary
