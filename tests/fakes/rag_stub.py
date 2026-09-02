"""测试 fake 客户端（薄封装 rag_stub_base）；FakeRag 唯一源。"""

from __future__ import annotations

from typing import Any

from app.tools.rag_stub_base import RagStubClient


class StubRagClient(RagStubClient):
    pass


class FakeRag(StubRagClient):
    """兼容旧测试名；默认 offline=True（Fixture 替身，不是 live）。

    若单测须模拟 HttpRAG 客户端，显式 FakeRag(offline=False) 或 FakeLiveRag。
    """

    def __init__(
        self,
        ask_payload: dict[str, Any] | None = None,
        fail: bool = False,
        parts: list[str] | None = None,
        *,
        offline: bool = True,
    ) -> None:
        # ask_payload=None 时走 stub 默认 + 冲突题动态合成；显式 payload 不被覆盖
        super().__init__(
            ask_payload=ask_payload,
            fail=fail,
            parts=parts,
            ticket_id="T-DEMO-1",
            request_id="fake-req",
        )
        self.offline = offline


class FakeLiveRag(FakeRag):
    """显式模拟 live HttpRAG 客户端（offline=False）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["offline"] = False
        super().__init__(*args, **kwargs)
