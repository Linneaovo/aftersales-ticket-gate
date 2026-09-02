"""HttpPartsLedger、mock WMS 契约与持久化重置回归。"""

from __future__ import annotations

from app.tracing.store import reset_all_persistence


def test_reset_all_persistence_clears_graph_cache(isolated_env, monkeypatch):
    from app.graph.builder import get_compiled_graph

    get_compiled_graph()
    report = reset_all_persistence()
    assert report.get("runs_db_cleared") == 1
    assert report.get("checkpoints_cleared") == 1


def test_mock_parts_wms_contract_marks_non_production():
    """学生伪 WMS：HTTP 契约可测，且自标非生产。"""
    from fastapi.testclient import TestClient

    from scripts.mock_parts_wms import app

    client = TestClient(app)
    health = client.get("/health").json()
    assert health.get("is_production_wms") is False
    assert health.get("mode") == "demo_mock_wms"

    body = client.post(
        "/parts/check",
        json={"hints": ["液压泵总成"], "machine_model": "SY215C"},
    ).json()
    assert body.get("is_production_wms") is False
    assert body.get("source") == "demo_mock_wms_http"
    assert body.get("shortage") is True
