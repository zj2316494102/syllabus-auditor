"""OpenAI 兼容 LLM 客户端与调用轨迹记录。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from syllabus_auditor.shared.config import load_project_config
from syllabus_auditor.core.db.connection import get_project_root


@dataclass(slots=True)
class LlmConfig:
    model: str
    api_key: str
    base_url: str | None = None


class EmptyLlmResponseError(ValueError):
    """LLM 返回空内容或仅空白字符。"""


def ensure_nonempty_response(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise EmptyLlmResponseError("模型返回为空")
    return cleaned


class LlmClient:
    def __init__(self, config: LlmConfig) -> None:
        llm_settings = _llm_settings()
        kwargs = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = OpenAI(**kwargs)
        self._model = config.model
        self._provider = str(llm_settings.get("provider") or "openai_compatible")
        self._system_prompt = str(llm_settings.get("system_prompt") or "你是严格输出 JSON 的课程方案审核专家。")
        self._temperature = llm_settings.get("temperature", 0)
        self._response_format = llm_settings.get("response_format") or {"type": "json_object"}

    @property
    def model_name(self) -> str:
        return self._model

    def metadata(self) -> dict[str, str]:
        return {"provider": self._provider, "model": self._model}

    def complete_json(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=self._temperature,
            response_format=self._response_format,
        )
        content = response.choices[0].message.content or ""
        return ensure_nonempty_response(content)


def load_llm_client() -> LlmClient | None:
    load_dotenv(get_project_root() / ".env")
    settings = _llm_settings()
    model = _first_env_value(settings.get("model_env_vars", []))
    api_key = _first_env_value(settings.get("api_key_env_vars", []))
    base_url = _first_env_value(settings.get("base_url_env_vars", [])) or None
    if not model.strip() or not api_key.strip():
        return None
    return LlmClient(LlmConfig(model=model.strip(), api_key=api_key.strip(), base_url=base_url))


def build_llm_trace(
    *,
    llm_client: Any,
    dimension: str,
    item: str,
    prompt: str,
    raw_response: str = "",
    parsed: Any | None = None,
    parse_error: str = "",
    status: str = "parsed",
    created_by: str = "direct_llm",
) -> dict[str, Any]:
    metadata = _llm_metadata(llm_client)
    call = {
        "provider": metadata.get("provider", ""),
        "model": metadata.get("model", ""),
        "dimension": dimension,
        "item": item,
        "prompt": prompt,
        "raw_response": raw_response,
        "parsed": parsed if parsed is not None else {},
        "parse_error": parse_error,
        "status": status,
        "created_by": created_by,
    }
    return append_llm_trace(
        {},
        dimension=dimension,
        mode=created_by,
        call=call,
    )


def append_llm_trace(
    llm_trace: dict[str, Any] | None,
    *,
    dimension: str,
    mode: str,
    call: dict[str, Any],
) -> dict[str, Any]:
    trace = dict(llm_trace or {})
    calls = trace.get("calls")
    if not isinstance(calls, list):
        calls = []
    calls.append(call)
    trace["dimension"] = str(trace.get("dimension") or dimension)
    trace["mode"] = str(trace.get("mode") or mode)
    trace["calls"] = calls
    return trace


def merge_llm_traces(
    traces: list[dict[str, Any]],
    *,
    dimension: str,
    mode: str,
) -> dict[str, Any]:
    merged: dict[str, Any] = {"dimension": dimension, "mode": mode, "calls": []}
    for trace in traces:
        calls = trace.get("calls") if isinstance(trace, dict) else None
        if isinstance(calls, list):
            merged["calls"].extend(calls)
    return merged


def first_llm_call(llm_trace: dict[str, Any] | None) -> dict[str, Any]:
    calls = (llm_trace or {}).get("calls")
    if isinstance(calls, list) and calls:
        first = calls[0]
        return first if isinstance(first, dict) else {}
    return {}


def _llm_metadata(llm_client: Any) -> dict[str, str]:
    if llm_client is None:
        return {"provider": "", "model": ""}
    metadata = getattr(llm_client, "metadata", None)
    if callable(metadata):
        value = metadata()
        if isinstance(value, dict):
            return {"provider": str(value.get("provider") or ""), "model": str(value.get("model") or "")}
    model = getattr(llm_client, "model_name", "") or getattr(llm_client, "_model", "")
    provider = str(_llm_settings().get("provider") or "openai_compatible")
    return {"provider": provider if model else "", "model": str(model or "")}


def _llm_settings() -> dict[str, Any]:
    value = load_project_config().get("llm", {})
    return value if isinstance(value, dict) else {}


def _first_env_value(names: Any) -> str:
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list):
        return ""
    for name in names:
        value = os.getenv(str(name))
        if value:
            return value
    return ""

