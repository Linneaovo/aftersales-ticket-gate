"""共享 pytest fixtures：隔离持久化 + FakeRag。"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.tools.http_pool import close_http_clients
from app.tools.circuit_breaker import reset_circuits
from tests.fakes import FakeRag


@pytest.fixture(autouse=True)
def _test_env_defaults(monkeypatch):
    """全量单测默认：rag_mock_inbox；并在前后清 Settings 缓存，避免 .env / monkeypatch 交叉污染。"""
    # 单元/API 默认走 rag_mock_inbox，便于断言 FakeRag.submit；
    # Standalone 用例自行 monkeypatch SUBMIT_DESTINATION=file_outbox。
    monkeypatch.setenv("SUBMIT_DESTINATION", "rag_mock_inbox")
    get_settings.cache_clear()
    reset_graph_cache()
    yield
    close_http_clients()
    reset_circuits()
    get_settings.cache_clear()
    reset_graph_cache()
    try:
        from app.policy.gates import _load_demo_keys_config

        _load_demo_keys_config.cache_clear()
    except Exception:
        pass


@pytest.fixture
def isolated_env(tmp_path, monkeypatch) -> None:
    """每个测试独立 runs / checkpoints / traces。"""
    monkeypatch.setenv("RUNS_DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("TRACES_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("PERSIST_MODE", "slim")
    monkeypatch.setenv("SUBMIT_DESTINATION", "rag_mock_inbox")
    get_settings.cache_clear()
    reset_graph_cache()


@pytest.fixture
def fake_rag() -> FakeRag:
    return FakeRag(parts=["液压滤芯"])


@pytest.fixture
def api_client(isolated_env, fake_rag, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("RAG_AUTO_FALLBACK", "1")
    monkeypatch.setenv("BLOCK_RUNS_WHEN_NOT_LIVE", "0")
    monkeypatch.setenv("REQUIRE_LIVE", "0")
    monkeypatch.setenv("REQUIRE_KNOWN_API_KEY", "1")
    # API 回归允许 parts_hints；生产/默认 ALLOW_DEMO_PARTS_HINTS=0
    monkeypatch.setenv("ALLOW_DEMO_PARTS_HINTS", "1")
    get_settings.cache_clear()
    with patch("app.main.build_rag_client", lambda *a, **k: fake_rag):
        with patch("app.main.is_rag_reachable", lambda **k: True):
            from app.main import app

            with TestClient(app) as client:
                yield client
