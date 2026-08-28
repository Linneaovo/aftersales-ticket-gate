"""LangGraph 主路径：interrupt → resume（与 POST /runs 一致）。"""

from __future__ import annotations

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.graph.runner import apply_hitl, create_initial_state, run_until_pause
from tests.test_core import FakeRag


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
    )  # type: ignore[arg-type]
    assert out2["status"] == "succeeded"
    assert out2.get("work_order_draft")


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
    )  # type: ignore[arg-type]
    assert out2["run_id"] == run_id
    assert out2["status"] == "succeeded"
