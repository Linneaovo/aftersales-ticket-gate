"""启动守卫：多 worker / 模式错配 / validate_mode 别名。"""

from __future__ import annotations

from app.config import (
    Settings,
    get_settings,
    multi_worker_forbidden,
    resolve_runtime_mode,
    strict_runtime_errors,
    submit_destination_name,
    validate_mode,
    validate_runtime_mode,
)


def test_validate_mode_aliases_runtime_mode():
    s = Settings(copilot_runtime_mode="standalone", demo_offline=True, submit_destination="file_outbox")
    assert validate_mode(s) == validate_runtime_mode(s)


def test_multi_worker_always_in_strict_errors():
    s = Settings(
        copilot_runtime_mode="standalone",
        demo_offline=True,
        submit_destination="file_outbox",
        uvicorn_workers=2,
    )
    assert multi_worker_forbidden(s) is True
    errs = strict_runtime_errors(s)
    assert any("UVICORN_WORKERS" in e or "workers" in e.lower() for e in errs)


def test_standalone_mismatch_in_strict_errors():
    s = Settings(
        copilot_runtime_mode="standalone",
        demo_offline=False,
        submit_destination="rag_mock_inbox",
        uvicorn_workers=1,
    )
    errs = strict_runtime_errors(s)
    assert any("file_outbox" in e for e in errs)
    assert any("DEMO_OFFLINE" in e for e in errs)


def test_conftest_isolates_demo_dotenv_from_offline_suite():
    """本地已 copy .env.standalone 时，离线套件不得仍处 standalone+strict 错配态。"""
    s = get_settings()
    assert s.strict_startup is False
    assert s.demo_offline is False
    assert submit_destination_name(s) == "rag_mock_inbox"
    assert resolve_runtime_mode(s) != "standalone"


def test_standalone_plus_rag_inbox_is_strict_fatal_shape():
    """文档/演示档若与测试默认终点叠加且 STRICT=1，属于应 fail-fast 的错配（故 conftest 必须隔离）。"""
    s = Settings(
        copilot_runtime_mode="standalone",
        demo_offline=True,
        submit_destination="rag_mock_inbox",
        strict_startup=True,
        uvicorn_workers=1,
    )
    errs = strict_runtime_errors(s)
    assert any("file_outbox" in e for e in errs)
    assert s.strict_startup is True


def test_api_client_healthy_under_isolated_suite(api_client):
    """隔离后 TestClient lifespan 可正常启动（对照本地 .env.standalone 场景）。"""
    resp = api_client.get("/health", headers={"X-API-Key": "demo-technician"})
    assert resp.status_code == 200


def test_linkage_claim_from_rag_labels():
    from app.main import _linkage_claim_from_rag

    assert _linkage_claim_from_rag(
        runtime_mode="standalone",
        rag_mode="demo_offline",
        rag_status={"ok": True},
        demo_offline=True,
    )[2] == "none"
    assert _linkage_claim_from_rag(
        runtime_mode="live",
        rag_mode="live",
        rag_status={"ok": True, "payload": {"evidence_tier": "L1", "mode": "contract_stub"}},
        demo_offline=False,
    )[2] == "L1"
    assert _linkage_claim_from_rag(
        runtime_mode="live",
        rag_mode="live",
        rag_status={"ok": True, "payload": {"evidence_tier": "L2"}},
        demo_offline=False,
    )[2] == "L2"
    assert _linkage_claim_from_rag(
        runtime_mode="live",
        rag_mode="live",
        rag_status={"ok": True, "payload": {"mode": "ollama"}},
        demo_offline=False,
    )[2] == "http_live"


def test_integration_probe_rejects_l1_stub():
    from tests.test_integration_live import _rag_is_l2_live

    assert _rag_is_l2_live({"evidence_tier": "L1", "mode": "contract_stub"}) is False
    assert _rag_is_l2_live({"evidence_tier": "L2", "mode": "live"}) is True
    assert _rag_is_l2_live({"mode": "ollama"}) is True
    assert _rag_is_l2_live({"mode": "contract_stub"}) is False

