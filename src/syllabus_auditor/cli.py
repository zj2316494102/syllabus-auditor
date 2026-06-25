"""syllabus-auditor 命令行入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from syllabus_auditor.auditors.runner import run_batch_audit
from syllabus_auditor.core.db.connection import get_project_root
from syllabus_auditor.core.db.init_db import main as init_db_main
from syllabus_auditor.loaders.course_library import run_prepare_course_library
from syllabus_auditor.loaders.syllabus_pdf import run_prepare_courses

app = typer.Typer(help="syllabus-auditor：课程库与 PDF 导入、数据库初始化")


@app.command("init-db")
def init_db() -> None:
    """执行 schema.sql，初始化 PostgreSQL 表结构。"""
    raise typer.Exit(init_db_main())


@app.command("prepare-courses")
def prepare_courses(
    input_dir: str = typer.Option("data", "--input", help="PDF 所在目录"),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="跳过已有 success 记录的 PDF"),
    list_only: bool = typer.Option(False, "--list-only", help="仅列出将处理的 PDF"),
) -> None:
    """递归扫描 PDF 并写入 syllabus_extractions 表。"""
    run_prepare_courses(
        _resolve_path(input_dir),
        skip_existing=skip_existing,
        list_only=list_only,
    )


@app.command("prepare-course-library")
def prepare_course_library_cmd(
    input_path: Optional[str] = typer.Option(None, "--input", help="课程库 Excel 路径"),
    data_dir: str = typer.Option("data", "--data-dir", help="数据目录"),
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


@app.command("run-batch")
def run_batch(
    run_name: Optional[str] = typer.Option(None, "--run-name", help="本轮审核名称"),
    term: Optional[str] = typer.Option(None, "--term", help="审核学期标识"),
    all_extractions: bool = typer.Option(False, "--all-extractions", help="审核全部抽取记录，而不是每个 PDF 只取最新记录"),
) -> None:
    """按轮次审核 PDF 抽取结果，并写入 audit_* 表。"""
    summary = run_batch_audit(
        run_name=run_name,
        import_term=term,
        latest_only=not all_extractions,
    )
    print(
        f"审核完成：run_id={summary.run_id}，共 {summary.total} 套，"
        f"通过 {summary.pass_count}，不通过 {summary.fail_count}，"
        f"部分通过 {summary.partial_count}，异常 {summary.error_count}"
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
