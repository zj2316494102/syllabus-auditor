"""审核维度注册与调度。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from syllabus_auditor.auditors.jxmbnrfsfhyq import audit_jxmbnrfsfhyq
from syllabus_auditor.auditors.szysfyxrghj import audit_szysfyxrghj
from syllabus_auditor.auditors.xxyzwzfhmb import audit_xxyzwzfhmb
from syllabus_auditor.core.audit import AuditSubject, FieldFinding, SectionFinding
from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.utils.llm_protocol import JsonLlmClient

AuditFn = Callable[..., tuple[SectionFinding, list[FieldFinding]]]

RULE_AUDIT_KEYS = frozenset({"kcjbxxsfykckyz", "jxnrsfyxspp", "jxapsfyzcpp"})
REGISTERED_AUDIT_KEYS = frozenset({"jxmbnrfsfhyq", "szysfyxrghj", "xxyzwzfhmb"})
ALL_AUDIT_KEYS = RULE_AUDIT_KEYS | REGISTERED_AUDIT_KEYS


@dataclass(frozen=True, slots=True)
class AuditorSpec:
    key: str
    label: str
    run: AuditFn
    needs_llm: bool


AUDITORS: tuple[AuditorSpec, ...] = (
    AuditorSpec("jxmbnrfsfhyq", "教学目标、内容、方式是否符合要求", audit_jxmbnrfsfhyq, True),
    AuditorSpec("szysfyxrghj", "是否将思政元素有效融入各环节", audit_szysfyxrghj, True),
    AuditorSpec("xxyzwzfhmb", "信息要素完整、符合模板、是否有中英文简介", audit_xxyzwzfhmb, False),
)

AUDITOR_BY_KEY = {item.key: item for item in AUDITORS}


def validate_audit_config(config: dict[str, Any] | None = None) -> list[str]:
    """校验 default_auditors 与 audit_modes 是否可执行。返回错误列表，空表示通过。"""
    audit = (config or load_project_config()).get("audit", {})
    if not isinstance(audit, dict):
        return ["audit config must be a dict"]

    errors: list[str] = []
    default = audit.get("default_auditors", [])
    modes = audit.get("audit_modes", {})
    if not isinstance(default, list):
        return ["default_auditors must be a list"]
    if not isinstance(modes, dict):
        return ["audit_modes must be a dict"]

    for key in default:
        key = str(key)
        if key not in ALL_AUDIT_KEYS:
            errors.append(f"unknown auditor in default_auditors: {key}")
        if key not in modes:
            errors.append(f"missing audit_modes entry for default auditor: {key}")

    for key in modes:
        if str(key) not in ALL_AUDIT_KEYS:
            errors.append(f"audit_modes key not runnable: {key}")

    return errors


def run_auditor(spec: AuditorSpec, subject: AuditSubject, llm_client: JsonLlmClient | None) -> tuple[SectionFinding, list[FieldFinding]]:
    if spec.needs_llm:
        return spec.run(subject, llm_client)
    return spec.run(subject)
