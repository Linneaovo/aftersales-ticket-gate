"""HttpPartsLedger 与持久化重置回归。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.tools.parts_ledger import HttpPartsLedger


def test_http_parts_ledger_uses_remote_payload(monkeypatch):
    monkeypatch.setenv("PARTS_LEDGER_URL", "http://wms.example")
    get_settings.cache_clear()

    mock_resp = MagicMock()
    mock_resp.content = b'{"needed": true, "shortage": false, "items": []}'
    mock_resp.json.return_value = {"needed": True, "shortage": False, "items": []}
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        out = HttpPartsLedger("http://wms.example").check_parts(["液压泵总成"])

    assert out.get("source") == "wms_http"
    assert out.get("shortage") is False
    mock_client.post.assert_called_once()


def test_reset_all_persistence_clears_graph_cache(isolated_env, monkeypatch):
    from app.graph.builder import get_compiled_graph
    from app.tracing.store import reset_all_persistence

    get_compiled_graph()
    report = reset_all_persistence()
    assert report.get("runs_db_cleared") == 1
    assert report.get("checkpoints_cleared") == 1
