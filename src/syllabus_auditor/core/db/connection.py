from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_dsn() -> str:
    root = get_project_root()
    load_dotenv(root / ".env")

    address = os.getenv("POSTGRES_ADDRESS", "localhost:5432")
    db = os.getenv("POSTGRES_DB", "course")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")

    if ":" in address:
        host, port = address.rsplit(":", 1)
    else:
        host, port = address, "5432"

    return f"host={host} port={port} dbname={db} user={user} password={password}"
