from __future__ import annotations

from config import load_project_config


def _labels() -> dict[str, str]:
    audit_config = load_project_config().get("audit", {})
    labels = audit_config.get("dimension_labels", {}) if isinstance(audit_config, dict) else {}
    return {str(key): str(value) for key, value in labels.items()} if isinstance(labels, dict) else {}


AUDIT_WD_LABELS = _labels()


def audit_wd_label(value: str) -> str:
    return AUDIT_WD_LABELS.get(str(value or ""), str(value or ""))


def audit_wd_code(value: str) -> str:
    text = str(value or "")
    for code, label in AUDIT_WD_LABELS.items():
        if text == label:
            return code
    return text

