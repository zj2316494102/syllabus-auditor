"""审核维度注册表与配置校验的单元测试。"""""
from __future__ import annotations
from syllabus_auditor.auditors.registry import ALL_AUDIT_KEYS, validate_audit_config
from syllabus_auditor.shared.config import load_project_config
def test_default_auditors_match_registry() -> None:
    auditors = load_project_config()["audit"]["default_auditors"]
    assert len(auditors) == 6
    assert set(auditors) == set(ALL_AUDIT_KEYS)
def test_validate_audit_config_passes() -> None:
    assert validate_audit_config() == []
