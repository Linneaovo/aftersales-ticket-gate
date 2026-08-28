from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from app.tools.rag_client import RagClient

_rag_client: ContextVar[RagClient | None] = ContextVar("rag_client", default=None)


def set_rag_client(client: RagClient | None):
    return _rag_client.set(client)


def reset_rag_client(token: Any) -> None:
    _rag_client.reset(token)


def get_rag_client(api_key: str | None = None) -> RagClient:
    current = _rag_client.get()
    if current is not None:
        return current
    return RagClient(api_key=api_key or "")
