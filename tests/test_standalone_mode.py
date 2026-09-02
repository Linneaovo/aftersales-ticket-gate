"""Standalone 模式：Fixture 知识源 + file_outbox，无 :8001。"""

from __future__ import annotations

from app.config import Settings, resolve_runtime_mode, submit_destination_name
from app.tools.demo_rag import DemoRagClient
from app.tools.rag_factory import knowledge_port_of, rag_client_mode
from app.tools.submit_destination import FileOutboxDestination


def test_resolve_runtime_mode_standalone_explicit():
    s = Settings(
        copilot_runtime_mode="standalone",
        demo_offline=True,
        require_live=False,
        block_runs_when_not_live=False,
        submit_destination="file_outbox",
    )
    assert resolve_runtime_mode(s) == "standalone"
    assert submit_destination_name(s) == "file_outbox"


def test_resolve_runtime_mode_derived_from_demo_offline():
    s = Settings(
        copilot_runtime_mode="",
        demo_offline=True,
        require_live=False,
        block_runs_when_not_live=False,
    )
    assert resolve_runtime_mode(s) == "standalone"


def test_resolve_runtime_mode_live():
    s = Settings(
        copilot_runtime_mode="",
        demo_offline=False,
        require_live=True,
        block_runs_when_not_live=True,
    )
    assert resolve_runtime_mode(s) == "live"


def test_knowledge_port_fixture_vs_http():
    client = DemoRagClient()
    assert knowledge_port_of(client) == "fixture"
    assert rag_client_mode(client) == "demo_offline"
    assert client.knowledge_port == "fixture"


def test_standalone_p1_hitl_then_file_outbox(tmp_path, monkeypatch):
    """无网络：P1 等人确 → file_outbox 可写可读。"""
    from app.graph.runner import create_initial_state, run_until_pause
    from app.playbooks.validate import load_playbook

    spec = load_playbook("p1_xingsha_h103")
    client = DemoRagClient(parts=list(spec.get("parts_hints") or []))
    state = create_initial_state(
        spec["question"],
        api_key=spec.get("api_key") or "demo-technician",
        role="technician",
        knowledge_base=spec.get("knowledge_base") or "demo-kb",
        engine="langgraph",
        parts_force_hints=list(spec.get("parts_hints") or []),
    )
    state = run_until_pause(state, client=client, persist=False)
    assert state.get("status") == "waiting_hitl"
    reasons = (state.get("hitl") or {}).get("reasons") or []
    pols = ((state.get("critic_report") or {}).get("policy_ids") or [])
    blob = " ".join(str(x) for x in list(reasons) + list(pols))
    assert "PARTS-01" in blob or "POL-PARTS-01" in blob

    dest = FileOutboxDestination(outbox_dir=tmp_path)
    rid = str(state.get("run_id") or "standalone-p1")
    submitted = dest.submit(
        (state.get("work_order_draft") or {}),
        run_id=rid,
        source="copilot_hitl",
    )
    assert submitted["destination"] == "file_outbox"
    assert submitted["source"] == "copilot_hitl"
    assert dest.get_ticket(rid) is not None


def test_standalone_scorecard_profile_ok():
    from app.eval.governance_scorecard import build_scorecard

    card = build_scorecard(profile="standalone")
    assert card.get("schema") == "standalone_scorecard/v1"
    assert card.get("profile") == "standalone"
    assert card.get("hand_filled") is False
    names = {m["name"] for m in card.get("metrics") or []}
    assert "file_outbox_port_ok" in names
    assert "degrade_blocks_auto_submit" in names
    required = [m for m in card["metrics"] if m.get("required", True)]
    assert all(m["ok"] for m in required), [m["name"] for m in required if not m["ok"]]
    assert card["all_ok"] is True


def test_hitl_approve_resume_writes_file_outbox(tmp_path, monkeypatch):
    """端到端：waiting_hitl → chief approve → submit_node 写 file_outbox（不调 RAG submit）。"""
    from app.config import get_settings
    from app.graph.builder import reset_graph_cache
    from app.graph.runner import apply_hitl, create_initial_state, run_until_pause
    from app.policy.decision_certificate import validate_certificate
    from app.policy.hitl_layers import compute_pending_layers, confirmations_covering
    from app.tools.submit_destination import FileOutboxDestination
    from tests.test_core import FakeRag

    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("SUBMIT_DESTINATION", "file_outbox")
    get_settings.cache_clear()
    reset_graph_cache()

    outbox = tmp_path / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    def _dest(client=None):
        return FileOutboxDestination(outbox_dir=outbox)

    monkeypatch.setattr("app.tools.submit_destination.get_submit_destination", _dest)

    state = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        engine="langgraph",
        auto_submit=True,
        station="长沙星沙服务站",
        parts_force_hints=["液压泵总成"],
    )
    client = FakeRag(parts=["液压泵总成"])
    paused = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    assert paused.get("status") == "waiting_hitl"
    pending = list((paused.get("hitl") or {}).get("pending_layers") or []) or compute_pending_layers(
        paused
    )
    confirmations = confirmations_covering(pending)

    done = apply_hitl(
        paused,
        "approve",
        "站长确认缺料调拨",
        client=client,
        persist=False,
        approver_api_key="demo-chief",
        confirmations=confirmations,
    )  # type: ignore[arg-type]
    assert done.get("status") == "succeeded"
    submit = done.get("work_order_submit") or {}
    assert submit.get("destination") == "file_outbox"
    assert submit.get("source") == "copilot_hitl"
    assert submit.get("is_production_ticket") is False
    assert client.submit_calls == 0  # 未走 RAG inbox
    rid = str(done.get("run_id") or "")
    assert (outbox / f"{rid}.json").exists()
    ticket = FileOutboxDestination(outbox_dir=outbox).get_ticket(rid)
    assert ticket and ticket.get("run_id") == rid
    cert = done.get("decision_certificate") or {}
    assert validate_certificate(cert) == []
    assert cert.get("phase") in {"resolved", "approved", "pending"} or cert.get("phase")

    get_settings.cache_clear()
    reset_graph_cache()


def test_outbox_api_lists_tickets(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.tools.submit_destination import FileOutboxDestination

    dest = FileOutboxDestination(outbox_dir=tmp_path)
    dest.submit({"draft": {"k": 1}}, run_id="api-outbox-1", source="copilot_hitl")
    monkeypatch.setattr(
        "app.main.FileOutboxDestination",
        lambda: FileOutboxDestination(outbox_dir=tmp_path),
    )
    client = TestClient(app)
    r = client.get("/outbox?limit=5", headers={"X-API-Key": "demo-chief"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("destination") == "file_outbox"
    assert body.get("count", 0) >= 1
    assert any(it.get("run_id") == "api-outbox-1" for it in (body.get("items") or []))
    one = client.get("/outbox/api-outbox-1", headers={"X-API-Key": "demo-chief"})
    assert one.status_code == 200
    assert one.json().get("source") == "copilot_hitl"
