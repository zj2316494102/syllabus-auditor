"""配置加载入口，合并 project.yaml 与领域 schema。"""


from syllabus_auditor.shared.config.loader import (
    load_extraction_config,
    load_project_config,
    load_project_yaml,
    load_yaml_config,
    project_yaml_path,
    reload_config,
)

PAYLOAD_SCHEMA_VERSION = "1.0"

__all__ = [
    "PAYLOAD_SCHEMA_VERSION",
    "load_extraction_config",
    "load_project_config",
    "load_project_yaml",
    "load_yaml_config",
    "project_yaml_path",
    "reload_config",
]
