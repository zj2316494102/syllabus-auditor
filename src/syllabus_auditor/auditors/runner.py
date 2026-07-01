"""批审调度器：多科目并发、续跑、LLM 维度并行。"""


from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from syllabus_auditor.auditors.registry import validate_audit_config
from syllabus_auditor.shared.config import PAYLOAD_SCHEMA_VERSION, load_project_config
from syllabus_auditor.auditors.registry import AUDITORS, run_auditor
from syllabus_auditor.core.audit import AuditRunSummary, SubjectAudit, audit_subject, build_run_name, build_subject_key, refresh_subject_audit
from syllabus_auditor.core.db.audit import AuditStore
from syllabus_auditor.core.llm import load_llm_client
from syllabus_auditor.utils import JsonLlmClient

DEFAULT_SUBJECT_WORKERS = 4


def _audit_config() -> dict:
    value = load_project_config().get("audit", {})
    return value if isinstance(value, dict) else {}


def _default_auditors() -> list[str]:
    value = _audit_config().get("default_auditors", [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _audit_modes(llm_enabled: bool) -> dict:
    modes = dict(_audit_config().get("audit_modes") or {})
    for value in modes.values():
        if isinstance(value, dict) and value.get("type") == "direct_llm":
            value["enabled"] = llm_enabled
    return modes



def _audit_subject_workers(subject_count: int) -> int:
    if subject_count <= 1:
        return 1
    configured = _audit_config().get("llm_subject_workers", DEFAULT_SUBJECT_WORKERS)
    try:
        workers = int(configured)
    except (TypeError, ValueError):
        workers = DEFAULT_SUBJECT_WORKERS
    workers = max(1, workers)
    return min(workers, subject_count)

DEFAULT_AUDITORS = _default_auditors()

def _ensure_subject_keys(subjects: list[AuditSubject]) -> None:
    for subject in subjects:
        if not subject.subject_key:
            subject.subject_key = build_subject_key(
                extraction_id=subject.extraction_id,
                course_code=subject.course_code,
                source_path=subject.source_path,
            )

def _subject_course_code(subject: AuditSubject) -> str:
    jcxx = subject.payload.get("jcxx") if isinstance(subject.payload.get("jcxx"), dict) else {}
    return str(jcxx.get("kcbh") or subject.course_code or "").strip()


def _duplicate_course_codes(subjects: list[AuditSubject]) -> set[str]:
    counts = Counter(_subject_course_code(subject) for subject in subjects)
    return {code for code, count in counts.items() if code and count > 1}


def _count_llm_call_statuses(audit: SubjectAudit) -> tuple[int, int, int]:
    empty_n = parse_n = no_llm_n = 0
    for finding in [*audit.section_findings, *audit.field_findings]:
        calls = (finding.llm_trace or {}).get("calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            status = str(call.get("status") or "")
            if status == "empty_response":
                empty_n += 1
            elif status == "parse_error":
                parse_n += 1
            elif status == "no_llm":
                no_llm_n += 1
    return empty_n, parse_n, no_llm_n



def _run_subject_audit(
    *,
    subject: AuditSubject,
    store: AuditStore,
    specs: list[Any],
    llm_client: JsonLlmClient | None,
    duplicate_course_codes: set[str] | None = None,
) -> SubjectAudit:
    course_match = store.match_course(subject, duplicate_course_codes=duplicate_course_codes or set())
    audit = audit_subject(subject, course_match)
    local_specs = [spec for spec in specs if not spec.needs_llm]
    llm_specs = [spec for spec in specs if spec.needs_llm]
    for spec in local_specs:
        section, fields = run_auditor(spec, subject, llm_client)
        audit.section_findings.append(section)
        audit.field_findings.extend(fields)
    if llm_specs:
        with ThreadPoolExecutor(max_workers=len(llm_specs)) as executor:
            futures = [executor.submit(run_auditor, spec, subject, llm_client) for spec in llm_specs]
            for future in futures:
                section, fields = future.result()
                audit.section_findings.append(section)
                audit.field_findings.extend(fields)
    refresh_subject_audit(audit)
    return audit

def run_batch_audit(
    *,
    run_name: str | None = None,
    import_term: str | None = None,
    latest_only: bool = True,
    limit: int | None = None,
    resume_run_id: int | None = None,
    store: AuditStore | None = None,
) -> AuditRunSummary:
    config_errors = validate_audit_config()
    if config_errors:
        raise ValueError("invalid audit config: " + "; ".join(config_errors))

    store = store or AuditStore()
    llm_client = load_llm_client()
    subjects = store.list_subjects(latest_only=latest_only)
    if limit is not None and limit > 0:
        subjects = subjects[:limit]
    _ensure_subject_keys(subjects)
    total_subject_count = len(subjects)
    duplicate_course_codes = _duplicate_course_codes(subjects)
    auditors = _default_auditors()
    skipped_count = 0
    if resume_run_id is not None:
        run_id = int(resume_run_id)
        completed_subject_keys = store.completed_subject_keys(run_id=run_id)
        pending_subjects = [subject for subject in subjects if subject.subject_key not in completed_subject_keys]
        skipped_count = len(subjects) - len(pending_subjects)
        store.resume_run(
            run_id=run_id,
            course_total=total_subject_count,
            skipped_count=skipped_count,
            pending_count=len(pending_subjects),
        )
        subjects = pending_subjects
    else:
        run_id = store.create_run(
            run_name=run_name or build_run_name(),
            import_term=import_term,
            auditors=auditors,
            config_snapshot={
                "version": 2,
                "payload_schema_version": str(load_project_config().get("payload_schema_version") or PAYLOAD_SCHEMA_VERSION),
                "latest_only": latest_only,
                "auditors": auditors,
                "audit_modes": _audit_modes(llm_client is not None),
                "field_results": "all",
            },
            course_total=total_subject_count,
        )
    pass_count = fail_count = partial_count = error_count = 0
    llm_empty_count = llm_parse_error_count = llm_no_llm_count = 0

    try:
        enabled = set(auditors)
        specs = [item for item in AUDITORS if item.key in enabled]

        subject_workers = _audit_subject_workers(len(subjects))
        with ThreadPoolExecutor(max_workers=subject_workers) as executor:
            futures = [
                executor.submit(
                    _run_subject_audit,
                    subject=subject,
                    store=store,
                    specs=specs,
                    llm_client=llm_client,
                    duplicate_course_codes=duplicate_course_codes,
                )
                for subject in subjects
            ]
            for future in as_completed(futures):
                audit = future.result()
                store.save_subject_audit(run_id=run_id, audit=audit)

                empty_n, parse_n, no_llm_n = _count_llm_call_statuses(audit)
                llm_empty_count += empty_n
                llm_parse_error_count += parse_n
                llm_no_llm_count += no_llm_n

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
            total=total_subject_count,
            pass_count=pass_count,
            fail_count=fail_count,
            partial_count=partial_count,
            error_count=error_count,
            skipped_count=skipped_count,
            llm_empty_count=llm_empty_count,
            llm_parse_error_count=llm_parse_error_count,
            llm_no_llm_count=llm_no_llm_count,
        )
        store.complete_run(summary)
        return summary
    except Exception as exc:
        store.fail_run(run_id=run_id, error_message=f"{type(exc).__name__}: {exc}")
        raise
