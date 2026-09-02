"""SubmitDestination 端口与幂等。"""

from __future__ import annotations

from app.tools.submit_destination import FileOutboxDestination, RagMockInboxDestination


class _StubClient:
    def __init__(self) -> None:
        self.calls = 0

    def submit_work_order(self, *args, **kwargs):
        self.calls += 1
        return {"ticket_id": f"t-{self.calls}", "source": kwargs.get("source")}


def test_rag_mock_destination_adds_boundary_and_idempotency_key():
    client = _StubClient()
    dest = RagMockInboxDestination(client)
    out = dest.submit({"draft": {}}, run_id="abc123", source="copilot_hitl")
    assert out["destination"] == "rag_mock_inbox"
    assert out["is_production_ticket"] is False
    assert out["idempotency_key"] == "abc123"
    assert out["source"] == "copilot_hitl"
    assert out["policy_ids"] == []
    assert out["hitl"] == {}
    assert client.calls == 1


def test_rag_mock_destination_envelope_includes_policy_and_hitl():
    """与 file_outbox 同 envelope：policy_ids / hitl 始终可审计。"""
    client = _StubClient()
    dest = RagMockInboxDestination(client)
    out = dest.submit(
        {"draft": {}},
        run_id="r-pol",
        policy_ids=["POL-PARTS-01"],
        hitl_summary={"decision": "approve", "resolved": True},
    )
    assert out["policy_ids"] == ["POL-PARTS-01"]
    assert out["hitl"]["decision"] == "approve"


def test_file_outbox_idempotent(tmp_path):
    dest = FileOutboxDestination(outbox_dir=tmp_path)
    first = dest.submit({"draft": {"x": 1}}, run_id="run1")
    second = dest.submit({"draft": {"x": 2}}, run_id="run1")
    assert first["ticket_id"] == second["ticket_id"]
    assert second.get("idempotent_replay") is True
    assert (tmp_path / "run1.json").exists()


def test_file_outbox_list_tickets(tmp_path):
    dest = FileOutboxDestination(outbox_dir=tmp_path)
    dest.submit({"draft": {"a": 1}}, run_id="a1")
    dest.submit({"draft": {"b": 1}}, run_id="b2")
    rows = dest.list_tickets(limit=10)
    assert len(rows) == 2
    assert {r["run_id"] for r in rows} == {"a1", "b2"}
    assert all(r.get("is_production_ticket") is False for r in rows)


def test_file_outbox_includes_policy_ids(tmp_path):
    dest = FileOutboxDestination(outbox_dir=tmp_path)
    out = dest.submit(
        {"draft": {"x": 1}},
        run_id="run-pol",
        policy_ids=["POL-PARTS-01", "POL-ROLE-01"],
        hitl_summary={"decision": "approve", "resolved": True, "pending_layers": ["shortage"]},
    )
    assert out["policy_ids"] == ["POL-PARTS-01", "POL-ROLE-01"]
    assert out["hitl"]["decision"] == "approve"
    loaded = dest.get_ticket("run-pol")
    assert loaded is not None
    assert "POL-PARTS-01" in loaded.get("policy_ids", [])


def test_format_submit_error_stable_fields():
    from app.tools.submit_destination import format_submit_error

    err = format_submit_error(RuntimeError("boom"), error_code="submit_failed", run_id="r1")
    assert err["error_code"] == "submit_failed"
    assert err["error"] == "boom"
    assert err["run_id"] == "r1"
    assert err["is_production_ticket"] is False
    assert err["ok"] is False


def test_submit_node_skips_destination_when_not_eligible():
    """无门禁通过时不得调用 SubmitDestination。"""
    from app.graph.nodes import submit_node
    from app.graph.state import empty_state

    class _Boom:
        def submit_work_order(self, *a, **k):
            raise AssertionError("destination must not be called")

    st = empty_state(
        run_id="no-submit",
        intent="fault_dispatch",
        role="technician",
        api_key="demo-technician",
        status="running",
        work_order_draft={"draft": {}},
        hitl={"required": True, "resolved": False},
        critic_report={"passed": True, "force_hitl": True, "reasons": ["x"], "policy_ids": []},
        parts_check={"shortage": True},
        auto_submit=False,
    )
    out = submit_node(st, client=_Boom())  # type: ignore[arg-type]
    assert out.get("status") == "failed"
    assert not out.get("work_order_submit")
    assert (out.get("submit_error") or {}).get("error_code") == "submit_gate_blocked"
