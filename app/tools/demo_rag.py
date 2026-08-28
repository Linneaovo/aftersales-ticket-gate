"""离线演示 RAG 客户端：:8001 不可达时兜底，保证开发/CI 主路径可跑。"""

from __future__ import annotations

from app.tools.rag_stub_base import RagStubClient


class DemoRagClient(RagStubClient):
    """API / DEMO_OFFLINE 模式；复用 RagStubClient，request_id 区分来源。"""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("request_id", "demo-offline")
        kwargs.setdefault("ticket_id", "T-DEMO-OFFLINE")
        super().__init__(*args, **kwargs)
