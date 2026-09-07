"""共享 pytest fixtures：隔离持久化 + FakeRag。"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.tools.circuit_breaker import reset_circuits
from app.tools.http_pool import close_http_clients
from app.tools.rag_client import RagToolError
from app.tools.rag_factory import reset_rag_reachability_cache
from tests.fakes import FakeRag


@pytest.fixture(autouse=True)
def _test_env_defaults(monkeypatch):
    """全量单测默认：rag_mock_inbox；并隔离本地演示用 `.env`，避免 .env / monkeypatch 交叉污染。

    本地常按 README `copy .env.standalone .env` 再跑 pytest。`.env.standalone` 含
    `STRICT_STARTUP=1` + `COPILOT_RUNTIME_MODE=standalone` + `file_outbox`；
    若只改 SUBMIT_DESTINATION→rag_mock_inbox，lifespan 会以模式错配 `sys.exit(1)`，
    TestClient 整片 ERROR（CI 无 `.env` 故绿）。此处强制离线套件运行时形态。
    """
    # 单元/API 默认走 rag_mock_inbox，便于断言 FakeRag.submit；
    # Standalone 用例自行 monkeypatch SUBMIT_DESTINATION=file_outbox。
    monkeypatch.setenv("SUBMIT_DESTINATION", "rag_mock_inbox")
    monkeypatch.setenv("STRICT_STARTUP", "0")
    # ci：不走 standalone/live 的 submit/offline 硬约束（见 strict_runtime_errors）
    monkeypatch.setenv("COPILOT_RUNTIME_MODE", "ci")
    # 避免本地 .env.standalone 的 DEMO_OFFLINE=1 推导回 standalone
    monkeypatch.setenv("DEMO_OFFLINE", "0")
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
    monkeypatch.setenv("STRICT_STARTUP", "0")
    monkeypatch.setenv("COPILOT_RUNTIME_MODE", "ci")
    monkeypatch.setenv("DEMO_OFFLINE", "0")
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
    reset_rag_reachability_cache()
    with patch("app.main.build_rag_client", lambda *a, **k: fake_rag):
        # 离线套件禁止探测本机 :8001。旧默认 is_rag_reachable=True 时，若本机
        # L1 contract_stub 在跑，health()→RagClient().health() 会把
        # linkage_claim / live_eval_all_ok 污染成联调态（CI 无 stub 故绿）。
        # FakeRag 仍由 build_rag_client 注入，写路径不受影响。
        with patch("app.main.is_rag_reachable", lambda **k: False):
            # 双保险：即使可达探测被误打开，也禁止 /health 直连真实 stub。
            with patch("app.main.RagClient.health", side_effect=RagToolError("offline suite blocks :8001", 503)):
                from app.main import app

                with TestClient(app) as client:
                    yield client
    reset_rag_reachability_cache()
