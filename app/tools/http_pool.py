"""进程内 httpx 连接池（RAG / WMS 等出站 HTTP 复用）。"""

from __future__ import annotations

import threading

import httpx

_pool_lock = threading.Lock()
_http_clients: dict[tuple[str, str], httpx.Client] = {}


def get_http_client(base_url: str, api_key: str = "") -> httpx.Client:
    key = (base_url.rstrip("/"), api_key or "")
    with _pool_lock:
        client = _http_clients.get(key)
        if client is None or client.is_closed:
            client = httpx.Client(
                base_url=key[0],
                timeout=httpx.Timeout(120.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
            )
            _http_clients[key] = client
        return client


def close_http_clients() -> None:
    with _pool_lock:
        for client in _http_clients.values():
            try:
                client.close()
            except Exception:
                pass
        _http_clients.clear()
