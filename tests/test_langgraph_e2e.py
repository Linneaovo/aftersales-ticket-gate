"""LangGraph 主路径：interrupt → resume（与 POST /runs 一致）。"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.graph.runner import apply_hitl, create_initial_state, run_until_pause
from app.policy.hitl_layers import compute_pending_layers, confirmations_covering
from tests.test_core import FakeRag

pytestmark = pytest.mark.langgraph


def _chief_confirmations(state: dict) -> dict[str, bool]:
    pending = list((state.get("hitl") or {}).get("pending_layers") or []) or compute_pending_layers(state)
    return confirmations_covering(pending)


def test_langgraph_hitl_interrupt_and_resume(tmp_path, monkeypatch):
    cp_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(cp_path))
    get_settings.cache_clear()
    reset_graph_cache()

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        auto_submit=False,
        station="长沙星沙服务站",
        parts_force_hints=["液压泵总成"],
    )
    client = FakeRag(parts=["液压泵总成"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert out.get("engine") == "langgraph"
    assert out["status"] == "waiting_hitl"

    out2 = apply_hitl(
        out,
        "approve",
        "站长确认",
        client=client,
        persist=False,
        approver_api_key="demo-chief",
        confirmations=_chief_confirmations(out),
    )  # type: ignore[arg-type]
    assert out2["status"] == "succeeded"
    assert out2.get("work_order_draft")


def test_terminal_run_clears_checkpoint(tmp_path, monkeypatch):
    """终态成功后清理 checkpoint，避免 orphan。"""
    from app.graph.builder import checkpoint_exists

    cp_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(cp_path))
    get_settings.cache_clear()
    reset_graph_cache()

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        auto_submit=False,
        station="长沙星沙服务站",
        parts_force_hints=["液压泵总成"],
    )
    client = FakeRag(parts=["液压泵总成"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    run_id = str(out["run_id"])
    assert out["status"] == "waiting_hitl"
    assert checkpoint_exists(run_id)

    out2 = apply_hitl(
        out,
        "approve",
        "站长确认",
        client=client,
        persist=False,
        approver_api_key="demo-chief",
        confirmations=_chief_confirmations(out),
    )  # type: ignore[arg-type]
    assert out2["status"] == "succeeded"
    assert not checkpoint_exists(run_id)


def test_engine_strict_no_silent_fallback(monkeypatch, tmp_path):
    from unittest.mock import patch

    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("ENGINE_STRICT", "1")
    get_settings.cache_clear()
    reset_graph_cache()

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        station="长沙星沙服务站",
    )
    client = FakeRag(parts=["液压滤芯"])
    with patch("app.graph.runner._run_langgraph", side_effect=RuntimeError("graph boom")):
        out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert out["status"] == "failed"
    assert out.get("engine") == "langgraph"
    assert not out.get("engine_degraded")
    assert "ENGINE_STRICT" in str(out.get("error") or "")


def test_hitl_checkpoint_missing_fails_under_engine_strict(monkeypatch, tmp_path):
    """O5：无 checkpoint 时 STRICT 不得默默 fallback 续跑。"""
    from unittest.mock import patch

    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("ENGINE_STRICT", "1")
    get_settings.cache_clear()
    reset_graph_cache()

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        station="长沙星沙服务站",
        parts_force_hints=["液压泵总成"],
    )
    client = FakeRag(parts=["液压泵总成"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert out["status"] == "waiting_hitl"

    with patch("app.graph.runner.checkpoint_exists", return_value=False):
        out2 = apply_hitl(
            out,
            "approve",
            "无 checkpoint",
            client=client,
            persist=False,
            approver_api_key="demo-chief",
            confirmations=_chief_confirmations(out),
        )  # type: ignore[arg-type]
    assert out2["status"] == "failed"
    assert "checkpoint_missing" in str(out2.get("error") or "")


def test_langgraph_checkpoint_survives_graph_cache_reset(tmp_path, monkeypatch):
    """模拟服务重启：清 graph 缓存后仍可从 Sqlite checkpoint resume。"""
    cp_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(cp_path))
    get_settings.cache_clear()
    reset_graph_cache()

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        station="长沙星沙服务站",
        parts_force_hints=["液压泵总成"],
    )
    client = FakeRag(parts=["液压泵总成"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    run_id = out["run_id"]
    assert out["status"] == "waiting_hitl"

    reset_graph_cache()
    get_settings.cache_clear()

    out2 = apply_hitl(
        out,
        "approve",
        "重启后续跑",
        client=client,
        persist=False,
        approver_api_key="demo-chief",
        confirmations=_chief_confirmations(out),
    )  # type: ignore[arg-type]
    assert out2["run_id"] == run_id
    assert out2["status"] == "succeeded"


def test_langgraph_draft_driven_parts_without_force_hints(tmp_path, monkeypatch):
    """无 parts_force_hints 时，配件需求应来自 RAG draft → parts 节点。"""
    cp_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(cp_path))
    get_settings.cache_clear()
    reset_graph_cache()

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        auto_submit=False,
        station="长沙星沙服务站",
    )
    client = FakeRag(parts=["液压泵总成"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert out.get("engine") == "langgraph"
    assert out["status"] == "waiting_hitl"
    parts = out.get("parts_check") or {}
    assert parts.get("needed") is True
    assert parts.get("shortage") is True
    assert parts.get("hints_source") == "rag_draft"
    assert "POL-PARTS-01" in " ".join((out.get("hitl") or {}).get("reasons") or [])
