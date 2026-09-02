"""Fixture 知识源客户端（契约形 ask/draft）。

Standalone 一等公民：`DEMO_OFFLINE=1` / `knowledge_port=fixture`。
Live 模式下禁止静默使用本客户端冒充联调。
"""

from __future__ import annotations

from app.tools.rag_stub_base import RagStubClient


class DemoRagClient(RagStubClient):
    """Fixture 知识源；类名保留兼容。request_id 区分来源。"""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("request_id", "demo-offline")
        kwargs.setdefault("ticket_id", "T-DEMO-OFFLINE")
        super().__init__(*args, **kwargs)

    @property
    def knowledge_port(self) -> str:
        return "fixture"
