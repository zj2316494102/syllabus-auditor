"""LLM 客户端协议接口（Protocol）。"""

from __future__ import annotations

from typing import Protocol


class JsonLlmClient(Protocol):
    def complete_json(self, prompt: str) -> str:
        ...
