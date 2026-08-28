"""共享 pytest fixtures：隔离持久化 + FakeRag。"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from tests.fakes.rag_stub import StubRagClient


class FakeRag(StubRagClient):
    """API 单测用 live RAG 客户端替身。"""

    offline = False


@pytest.fixture
def isolated_env(tmp_path, monkeypatch) -> None:
    """每个测试独立 runs / checkpoints / traces。"""
    monkeypatch.setenv("RUNS_DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("TRACES_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("PERSIST_MODE", "slim")
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
    get_settings.cache_clear()
    with patch("app.main.build_rag_client", lambda *a, **k: fake_rag):
        with patch("app.main.is_rag_reachable", lambda **k: True):
            from app.main import app

            with TestClient(app) as client:
                yield client
