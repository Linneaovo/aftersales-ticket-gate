"""HTTP 连接池、熔断与 parts 台账客户端测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import get_settings
from app.tools.circuit_breaker import (
    circuit_allow,
    circuit_record_failure,
    circuit_record_success,
    circuit_snapshot,
    reset_circuits,
)
from app.tools.http_pool import close_http_clients, get_http_client
from app.tools.parts_ledger import HttpPartsLedger, reset_parts_ledger_client
from app.tools.rag_client import RagClient, RagToolError


def test_http_pool_reuses_client():
    close_http_clients()
    a = get_http_client("http://127.0.0.1:8001", "demo-key")
    b = get_http_client("http://127.0.0.1:8001", "demo-key")
    assert a is b
    close_http_clients()


def test_http_pool_separate_per_api_key():
    close_http_clients()
    a = get_http_client("http://127.0.0.1:8001", "demo-technician")
    b = get_http_client("http://127.0.0.1:8001", "demo-chief")
    assert a is not b
    close_http_clients()


def test_circuit_opens_after_threshold_failures():
    reset_circuits()
    name = "test-circuit"
    assert circuit_allow(name, failure_threshold=3, cooldown_s=60.0) is True
    circuit_record_failure(name, failure_threshold=3)
    circuit_record_failure(name, failure_threshold=3)
    assert circuit_allow(name, failure_threshold=3, cooldown_s=60.0) is True
    circuit_record_failure(name, failure_threshold=3)
    assert circuit_snapshot(name)["open"] is True
    assert circuit_allow(name, failure_threshold=3, cooldown_s=60.0) is False
    circuit_record_success(name)
    assert circuit_allow(name, failure_threshold=3, cooldown_s=60.0) is True
    reset_circuits()


def test_rag_client_circuit_blocks_when_open():
    reset_circuits()
    close_http_clients()
    client = RagClient(api_key="demo-technician")
    name = client._circuit_name()
    for _ in range(3):
        circuit_record_failure(name, failure_threshold=3)
    with pytest.raises(RagToolError) as ei:
        client.health()
    assert "熔断" in str(ei.value)
    reset_circuits()


def test_http_parts_ledger_uses_remote_payload(monkeypatch):
    monkeypatch.setenv("PARTS_LEDGER_URL", "http://wms.example")
    get_settings.cache_clear()
    reset_parts_ledger_client()

    mock_resp = MagicMock()
    mock_resp.content = b'{"needed": true, "shortage": false, "items": []}'
    mock_resp.json.return_value = {"needed": True, "shortage": False, "items": []}
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    with patch("app.tools.http_pool.get_http_client", return_value=mock_client):
        out = HttpPartsLedger("http://wms.example").check_parts(["液压泵总成"])

    assert out.get("source") == "wms_http"
    assert out.get("shortage") is False
    mock_client.post.assert_called_once()


def test_http_parts_ledger_fallback_marks_degraded(monkeypatch):
    monkeypatch.setenv("PARTS_LEDGER_URL", "http://wms.example")
    get_settings.cache_clear()
    reset_parts_ledger_client()

    mock_client = MagicMock()
    mock_client.post.side_effect = RuntimeError("connection refused")

    with patch("app.tools.http_pool.get_http_client", return_value=mock_client):
        out = HttpPartsLedger("http://wms.example").check_parts(["液压泵总成"])

    assert out.get("ledger_degraded") is True
    assert out.get("source") == "json_fallback_after_http_error"
    assert "降级" in str(out.get("note") or out.get("suggested_action") or "")


def test_reset_parts_ledger_client(monkeypatch):
    monkeypatch.setenv("PARTS_LEDGER_URL", "")
    get_settings.cache_clear()
    reset_parts_ledger_client()
    from app.tools.parts_ledger import JsonPartsLedger, get_parts_ledger_client

    c1 = get_parts_ledger_client()
    assert isinstance(c1, JsonPartsLedger)
    reset_parts_ledger_client()
    c2 = get_parts_ledger_client()
    assert c1 is not c2
