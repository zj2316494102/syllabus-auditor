"""syllabus-auditor 命令行入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from syllabus_auditor.application.audit.batch import run_audit_batch
from syllabus_auditor.application.prepare import (
    run_prepare_course_library,
    run_prepare_courses,
    run_prepare_mineru,
)
from syllabus_auditor.application.report.quality import run_quality_report
from syllabus_auditor.core.db.connection import get_project_root
from syllabus_auditor.core.db.init_db import main as init_db_main
from syllabus_auditor.shared.logging import configure_logging

app = typer.Typer(help="syllabus-auditor：课程库与 PDF 导入、批处理审核、质量报告")
prepare_app = typer.Typer(help="数据准备：MinerU / PDF / 课程库 → PostgreSQL")
audit_app = typer.Typer(help="批处理审核")
report_app = typer.Typer(help="只读分析报告")

app.add_typer(prepare_app, name="prepare")
app.add_typer(audit_app, name="audit")
app.add_typer(report_app, name="report")


@app.callback()
def _root() -> None:
    configure_logging()


@app.command("init-db")
def init_db() -> None:
    """执行 schema.sql，初始化 PostgreSQL 表结构。"""
    raise typer.Exit(init_db_main())


@prepare_app.command("mineru")
def prepare_mineru_cmd() -> None:
    """MinerU manifest → 抽取 → syllabus_extractions（不经过 pdfplumber）。"""
    stats = run_prepare_mineru()
    typer.echo(f"Done: {stats}")


@prepare_app.command("courses")
def prepare_courses_cmd(
    input_dir: str = typer.Option("data_pdf", "--input", help="PDF 所在目录"),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="跳过已有 success 记录的 PDF"),
    list_only: bool = typer.Option(False, "--list-only", help="仅列出将处理的 PDF"),
) -> None:
    """递归扫描 PDF 并写入 syllabus_extractions 表。"""
    run_prepare_courses(
        _resolve_path(input_dir),
        skip_existing=skip_existing,
        list_only=list_only,
    )


@prepare_app.command("course-library")
def prepare_course_library_cmd(
    input_path: Optional[str] = typer.Option(None, "--input", help="课程库 Excel 路径"),
    data_dir: str = typer.Option("data_pdf", "--data-dir", help="数据目录"),
    term: Optional[str] = typer.Option(None, "--term", help="导入学期标识，如 2026-spring"),
    list_only: bool = typer.Option(False, "--list-only", help="仅预览，不写库"),
) -> None:
    """导入课程库 Excel 到 courses 表。"""
    project_root = get_project_root()
    resolved_data_dir = _resolve_path(data_dir)
    explicit = _resolve_path(input_path) if input_path else None
    if explicit and not explicit.is_absolute():
        explicit = project_root / explicit

    run_prepare_course_library(
        resolved_data_dir,
        explicit=explicit,
        import_term=term,
        list_only=list_only,
    )


@audit_app.command("run")
def audit_run_cmd(
    run_name: Optional[str] = typer.Option(None, "--run-name", help="本轮审核名称"),
    term: Optional[str] = typer.Option(None, "--term", help="审核学期标识"),
    all_extractions: bool = typer.Option(False, "--all-extractions", help="审核全部抽取记录，而不是每个 PDF 只取最新记录"),
    limit: Optional[int] = typer.Option(None, "--limit", help="最多审核多少套（试跑用）"),
    resume_run_id: Optional[int] = typer.Option(None, "--resume-run-id", help="续跑已有 audit_runs.id，跳过已入库结果"),
) -> None:
    """按配置维度批审 PDF 抽取结果，并写入 audit_* 表。"""
    summary = run_audit_batch(
        run_name=run_name,
        import_term=term,
        latest_only=not all_extractions,
        limit=limit,
        resume_run_id=resume_run_id,
    )
    _print_audit_summary(summary)


@report_app.command("quality")
def report_quality_cmd(
    refresh_middle_cache: bool = typer.Option(False, "--refresh-middle-cache", help="重建 middle 文本缓存"),
) -> None:
    """生成 docs/data_quality_report.md（只读已有产物）。"""
    code = run_quality_report(refresh_middle_cache=refresh_middle_cache)
    raise typer.Exit(code)


@app.command("prepare-courses", hidden=True)
def prepare_courses_legacy(
    input_dir: str = typer.Option("data_pdf", "--input"),
    skip_existing: bool = typer.Option(False, "--skip-existing"),
    list_only: bool = typer.Option(False, "--list-only"),
) -> None:
    """[已废弃] 请使用 prepare courses。"""
    prepare_courses_cmd(input_dir=input_dir, skip_existing=skip_existing, list_only=list_only)


@app.command("prepare-course-library", hidden=True)
def prepare_course_library_legacy(
    input_path: Optional[str] = typer.Option(None, "--input"),
    data_dir: str = typer.Option("data_pdf", "--data-dir"),
    term: Optional[str] = typer.Option(None, "--term"),
    list_only: bool = typer.Option(False, "--list-only"),
) -> None:
    """[已废弃] 请使用 prepare course-library。"""
    prepare_course_library_cmd(input_path=input_path, data_dir=data_dir, term=term, list_only=list_only)


@app.command("run-batch", hidden=True)
def run_batch_legacy(
    run_name: Optional[str] = typer.Option(None, "--run-name"),
    term: Optional[str] = typer.Option(None, "--term"),
    all_extractions: bool = typer.Option(False, "--all-extractions"),
    limit: Optional[int] = typer.Option(None, "--limit"),
    resume_run_id: Optional[int] = typer.Option(None, "--resume-run-id"),
) -> None:
    """[已废弃] 请使用 audit run。"""
    audit_run_cmd(run_name=run_name, term=term, all_extractions=all_extractions, limit=limit, resume_run_id=resume_run_id)


def _print_audit_summary(summary) -> None:
    print(
        f"审核完成：run_id={summary.run_id}，共 {summary.total} 套，"
        f"通过 {summary.pass_count}，不通过 {summary.fail_count}，"
        f"部分通过 {summary.partial_count}，异常 {summary.error_count}"
    )
    if getattr(summary, "skipped_count", 0):
        print(f"续跑跳过已完成 {summary.skipped_count} 套，本次处理 {max(summary.total - summary.skipped_count, 0)} 套。")
    if summary.llm_empty_count or summary.llm_parse_error_count or summary.llm_no_llm_count:
        print(
            f"LLM 调用：空回复 {summary.llm_empty_count}，解析失败 {summary.llm_parse_error_count}，"
            f"未配置 {summary.llm_no_llm_count}"
        )
    print(
        "复核查询："
        f"SELECT * FROM audit_results WHERE run_id = {summary.run_id} "
        "AND overall_status IN ('fail','partial','error');"
    )


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return get_project_root() / path


def main() -> None:
    app()


if __name__ == "__main__":
    main()
