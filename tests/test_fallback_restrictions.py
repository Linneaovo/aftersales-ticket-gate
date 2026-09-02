"""Fallback 引擎限制：不得假 HITL / 不得 silent submit。"""

from __future__ import annotations

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.graph.runner import create_initial_state, run_until_pause, step_fallback
from app.graph.state import merge_state
from tests.test_core import FakeRag


def test_fallback_hitl_becomes_failed(isolated_env):
    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="fallback",
        station="长沙星沙服务站",
        parts_force_hints=["液压泵总成"],
    )
    client = FakeRag(parts=["液压泵总成"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert out["status"] == "failed"
    assert "fallback" in str(out.get("error") or "").lower()
    assert out.get("engine") == "fallback"


def test_step_fallback_no_waiting_hitl(isolated_env):
    state = merge_state(
        create_initial_state("SY215C H103报修", api_key="demo-technician", engine="fallback"),
        status="waiting_hitl",
        next_action="hitl",
        hitl={"required": True, "resolved": False, "reasons": ["POL-PARTS-01"]},
    )
    out = step_fallback(state)
    assert out["status"] == "failed"
    assert "HITL" in str(out.get("error") or "")


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
