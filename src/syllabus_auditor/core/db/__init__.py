"""数据库访问模块入口。"""

from syllabus_auditor.core.db.connection import build_dsn, get_project_root
from syllabus_auditor.core.db.courses import CourseStore
from syllabus_auditor.core.db.extractions import ExtractionStore
from syllabus_auditor.core.db.init_db import EXPECTED_TABLES, init_database, main as init_db_main

__all__ = [
    "EXPECTED_TABLES",
    "build_dsn",
    "get_project_root",
    "CourseStore",
    "ExtractionStore",
    "init_database",
    "init_db_main",
]
