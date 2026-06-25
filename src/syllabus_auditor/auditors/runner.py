from __future__ import annotations

from typing import Any

from syllabus_auditor.auditors.jxmbnrfsfhyq import audit_jxmbnrfsfhyq
from syllabus_auditor.auditors.szysfyxrghj import audit_szysfyxrghj
from syllabus_auditor.auditors.xxyzwzfhmb import audit_xxyzwzfhmb
from syllabus_auditor.core.audit import AuditRunSummary, audit_subject, build_run_name, refresh_subject_audit
from config import load_project_config
from syllabus_auditor.core.db.audit import AuditStore
from syllabus_auditor.core.llm import load_llm_client


def _audit_config() -> dict[str, Any]:
    value = load_project_config().get("audit", {})
    return value if isinstance(value, dict) else {}


def _default_auditors() -> list[str]:
    value = _audit_config().get("default_auditors", [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _audit_modes(llm_enabled: bool) -> dict[str, Any]:
    modes = dict(_audit_config().get("audit_modes") or {})
    for value in modes.values():
        if isinstance(value, dict) and value.get("type") == "direct_llm":
            value["enabled"] = llm_enabled
    return modes


DEFAULT_AUDITORS = _default_auditors()


def run_batch_audit(
    *,
    run_name: str | None = None,
    import_term: str | None = None,
    latest_only: bool = True,
    store: AuditStore | None = None,
) -> AuditRunSummary:
    store = store or AuditStore()
    llm_client = load_llm_client()
    subjects = store.list_subjects(latest_only=latest_only)
    auditors = _default_auditors()
    run_id = store.create_run(
        run_name=run_name or build_run_name(),
        import_term=import_term,
        auditors=auditors,
        config_snapshot={
            "version": 1,
            "latest_only": latest_only,
            "auditors": auditors,
            "audit_modes": _audit_modes(llm_client is not None),
            "field_results": "all",
        },
        course_total=len(subjects),
    )

    pass_count = 0
    fail_count = 0
    partial_count = 0
    error_count = 0

    try:
        for subject in subjects:
            course_match = store.match_course(subject)
            audit = audit_subject(subject, course_match)
            jx_section, jx_fields = audit_jxmbnrfsfhyq(subject, llm_client)
            audit.section_findings.append(jx_section)
            audit.field_findings.extend(jx_fields)
            sz_section, sz_fields = audit_szysfyxrghj(subject, llm_client)
            audit.section_findings.append(sz_section)
            audit.field_findings.extend(sz_fields)
            xx_section, xx_fields = audit_xxyzwzfhmb(subject)
            audit.section_findings.append(xx_section)
            audit.field_findings.extend(xx_fields)
            refresh_subject_audit(audit)
            store.save_subject_audit(run_id=run_id, audit=audit)

            if audit.overall_status == "pass":
                pass_count += 1
            elif audit.overall_status == "fail":
                fail_count += 1
            elif audit.overall_status == "error":
                error_count += 1
            else:
                partial_count += 1

        summary = AuditRunSummary(
            run_id=run_id,
            total=len(subjects),
            pass_count=pass_count,
            fail_count=fail_count,
            partial_count=partial_count,
            error_count=error_count,
        )
        store.complete_run(summary)
        return summary
    except Exception as exc:
        store.fail_run(run_id=run_id, error_message=f"{type(exc).__name__}: {exc}")
        raise

