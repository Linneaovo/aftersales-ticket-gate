"""大纲 A-01～A-09 验收向用例（A-02～A-05 默认 langgraph，与 POST /runs 一致）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.eval.compare import compare_cases
from app.graph.builder import reset_graph_cache
from app.graph.runner import apply_hitl, create_initial_state, public_view, run_until_pause
from app.policy.gates import is_station_chief
from tests.test_core import FakeRag

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _langgraph_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))
    get_settings.cache_clear()
    reset_graph_cache()


def test_a01_p1_playbook_shape():
    data = (ROOT / "data" / "playbooks" / "p1_xingsha_h103.json").read_text(encoding="utf-8")
    assert "H103" in data and "星沙" in data


def test_a02_conflict_blocks_submit_until_chief_approve():
    payload = {
        "answer": "并列不作裁决",
        "sources": [{"chunk": {"source": "a"}, "score": 0.9}],
        "grounded": True,
        "grounding_score": 0.9,
        "blocked": False,
        "conflicts": [{"a": 1, "b": 2}],
    }
    state = create_initial_state(
        "SY215C H103请报修处理，并核对质保期哪个为准",
        api_key="demo-technician",
        engine="langgraph",
        auto_submit=True,
        station="长沙星沙服务站",
        parts_force_hints=["液压滤芯"],
    )
    client = FakeRag(ask_payload=payload, parts=["液压滤芯"])
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert out["status"] == "waiting_hitl"
    assert client.submit_calls == 0
    assert out.get("engine") == "langgraph"
    assert (out.get("conflict_bundle") or {}).get("present")
    out2 = apply_hitl(
        out,
        "approve",
        "确认并列口径后开单",
        client=client,
        persist=False,
        approver_api_key="demo-chief",
    )  # type: ignore[arg-type]
    assert client.submit_calls == 1
    assert out2["status"] == "succeeded"


def test_a03_role_paths_differ():
    tech = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        station="长沙星沙服务站",
        parts_force_hints=["液压滤芯"],
    )
    chief = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-chief",
        engine="langgraph",
        station="长沙星沙服务站",
        parts_force_hints=["液压滤芯"],
    )
    out_t = run_until_pause(tech, client=FakeRag(parts=["液压滤芯"]), persist=False)  # type: ignore[arg-type]
    out_c = run_until_pause(chief, client=FakeRag(parts=["液压滤芯"]), persist=False)  # type: ignore[arg-type]
    assert out_t["status"] == "succeeded"
    assert out_t.get("work_order_state") == "ready_for_chief"
    assert out_c["status"] == "succeeded"
    assert out_t["role"] != out_c["role"]


def test_a04_tool_error_and_iteration():
    out = run_until_pause(
        create_initial_state("H103是什么意思", engine="langgraph"),
        client=FakeRag(fail=True),
        persist=False,
    )  # type: ignore[arg-type]
    assert out["status"] == "failed"


def test_a05_trace_has_key_nodes():
    out = run_until_pause(
        create_initial_state("SY215C H103请报修处理", api_key="demo-technician", engine="langgraph"),
        client=FakeRag(),
        persist=False,
    )  # type: ignore[arg-type]
    nodes = [e["node"] for e in out["trace_events"]]
    for n in ("supervisor", "rag", "quality", "work_order", "parts", "hitl"):
        assert n in nodes
    view = public_view(out)
    assert len(view["trace_events"]) == len(out["trace_events"])
    assert view.get("engine") == "langgraph"


def test_a06_case_file_min_30():
    lines = [
        ln
        for ln in (ROOT / "data" / "eval" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) >= 30


def test_a07_compare_delta():
    summary = compare_cases()["summary"]
    assert summary["case_count"] >= 6
    assert summary["delta_miss_hitl"] >= 0
    assert summary["acl_leak_risk_copilot"] <= summary["acl_leak_risk_single"]


def test_a08_readme_lists_rag_apis():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/ask" in text and "work-orders" in text.lower() or "工单" in text
    assert is_station_chief(api_key="demo-chief")


def test_a09_demo_assets_exist():
    assert (ROOT / "DEMO_SCRIPT.md").exists()
    assert (ROOT / "start_copilot.cmd").exists()
    assert (ROOT / "start_ui.cmd").exists()
    assert (ROOT / "start_all.cmd").exists()
    assert (ROOT / ".env.example").exists()
    assert (ROOT / ".env.demo").exists()
    assert (ROOT / "docs" / "RAG_RESPONSE_SCHEMA.md").exists()
    assert (ROOT / "data" / "playbooks" / "p1_xingsha_h103.json").exists()
    assert (ROOT / "data" / "playbooks" / "p8_parts_clerk_conflict.json").exists()
