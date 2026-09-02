"""RAG 客户端工厂：真连 / 离线兜底 / 强制 DEMO_OFFLINE。"""

from __future__ import annotations

import time
from typing import Any

from app.config import get_settings
from app.logging_config import get_logger
from app.tools.demo_rag import DemoRagClient
from app.tools.rag_client import RagClient, RagToolError

logger = get_logger("rag_factory")

_rag_reachable_cache: bool | None = None
_rag_reachable_checked_at: float = 0.0


def is_rag_reachable(*, force_check: bool = False) -> bool:
    """探测 enterprise-rag :8001 是否可达（带 TTL 缓存）。"""
    global _rag_reachable_cache, _rag_reachable_checked_at
    settings = get_settings()
    if settings.demo_offline:
        return False
    ttl = float(settings.rag_reachability_ttl_s or 0)
    now = time.time()
    if (
        not force_check
        and _rag_reachable_cache is not None
        and ttl > 0
        and (now - _rag_reachable_checked_at) < ttl
    ):
        return _rag_reachable_cache
    try:
        RagClient(settings=settings).health()
        _rag_reachable_cache = True
    except RagToolError as exc:
        logger.warning("enterprise-rag 不可达: %s", exc)
        _rag_reachable_cache = False
    except Exception:
        logger.exception("enterprise-rag 健康检查出现未预期异常")
        _rag_reachable_cache = False
    _rag_reachable_checked_at = now
    return _rag_reachable_cache


def reset_rag_reachability_cache() -> None:
    global _rag_reachable_cache, _rag_reachable_checked_at
    _rag_reachable_cache = None
    _rag_reachable_checked_at = 0.0


def build_rag_client(api_key: str | None = None, *, parts: list[str] | None = None) -> Any:
    """返回 RagClient 或 DemoRagClient（不可达且允许 auto_fallback 时）。"""
    settings = get_settings()
    key = api_key or settings.api_key
    if settings.demo_offline:
        return DemoRagClient(parts=parts)
    if not settings.rag_auto_fallback:
        if not is_rag_reachable(force_check=True):
            raise RagToolError(
                "enterprise-rag 不可达且 RAG_AUTO_FALLBACK=0，请先启动 :8001 或 copy .env.demo .env",
                503,
            )
        return RagClient(api_key=key)
    if is_rag_reachable():
        return RagClient(api_key=key)
    return DemoRagClient(parts=parts)


def rag_client_mode(client: Any) -> str:
    """历史字段：fixture 客户端仍报 demo_offline，避免冲垮既有断言。"""
    if getattr(client, "offline", False):
        return "demo_offline"
    return "live"


def knowledge_port_of(client: Any) -> str:
    """知识源端口：fixture（本仓契约响应）| http（enterprise-rag）。"""
    if getattr(client, "offline", False):
        return "fixture"
    return "http"


def assert_knowledge_port(client: Any) -> bool:
    """结构性检查：客户端是否具备 KnowledgePort 关键表面。"""
    from app.tools.knowledge_port import KnowledgePort

    return isinstance(client, KnowledgePort) or (
        callable(getattr(client, "ask", None))
        and callable(getattr(client, "draft_work_order", None))
        and hasattr(client, "offline")
    )
