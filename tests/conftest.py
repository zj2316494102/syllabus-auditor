"""pytest 共用配置。"""

from __future__ import annotations

import pytest

pytest_plugins: list[str] = []


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: 需要 DATABASE_URL 与本地 data_pdf/data_md，默认不跑",
    )
