"""知识源端口协议（与 SubmitDestination 对称）。

实现：DemoRagClient / RagStubClient（fixture）、RagClient（http）。
工厂见 rag_factory.build_rag_client / knowledge_port_of。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class KnowledgePort(Protocol):
    """可插拔知识源：ask / draft；offline 区分 fixture vs http。"""

    offline: bool

    def ask(
        self,
        question: str,
        *,
        knowledge_base: str | None = None,
        history: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        ...

    def draft_work_order(
        self,
        question: str,
        *,
        knowledge_base: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        ...
