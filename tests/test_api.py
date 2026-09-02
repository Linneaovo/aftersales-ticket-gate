"""FastAPI HTTP 层集成测试（服务契约）。"""

from __future__ import annotations

import json
from unittest.mock import patch

from app.config import get_settings
from app.policy.hitl_layers import confirmations_covering
from tests.test_core import FakeRag

_HITL_RUN_JSON = {
    "question": "长沙星沙 SY215C H103请报修处理",
    "parts_hints": ["液压泵总成"],
    "station": "长沙星沙服务站",
}
_LOW_RISK_RUN_JSON = {
    "question": "长沙星沙 SY215C H103请报修处理",
    "parts_hints": ["液压滤芯"],
    "station": "长沙星沙服务站",
}


def _approve_payload(create_body: dict, note: str = "站长确认") -> dict:
    pending = list((create_body.get("hitl") or {}).get("pending_layers") or [])
    return {"decision": "approve", "note": note, "confirmations": confirmations_covering(pending)}


def test_metrics_requires_known_api_key(api_client):
    denied = api_client.get("/metrics")
    assert denied.status_code == 401
    ok = api_client.get("/metrics", headers={"X-API-Key": "demo-technician"})
    assert ok.status_code == 200
    assert "copilot_run_total" in ok.text


def test_health(api_client):
    resp = api_client.get("/health", headers={"X-API-Key": "demo-technician"})
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert body.get("engine") == "langgraph"
    assert "rag_circuit" in body
    assert "open" in (body.get("rag_circuit") or {})
    assert body.get("parts_ledger_sha256")
    assert isinstance(body.get("parts_item_count"), int)
    assert body.get("rag_contract_version")


def test_admin_reload_ledger(api_client):
    resp = api_client.post("/admin/reload-ledger", headers={"X-API-Key": "demo-technician"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("parts_ledger_sha256")


def test_playbooks_lane_core_default(api_client):
    core = api_client.get("/playbooks").json()
    assert core.get("lane") == "core"
    ids = {i["id"] for i in core.get("items") or []}
    assert ids == {"p1_xingsha_h103", "p1b_no_shortage_ready", "p8_parts_clerk_conflict"}
    ext = api_client.get("/playbooks?lane=extended").json()
    ext_ids = {i["id"] for i in ext.get("items") or []}
    assert "p6_chitchat" in ext_ids
    assert len(ext_ids) > len(ids)

def test_health_live_eval_from_portfolio_json(api_client):
    """Portfolio 证据只读 live_*.json，不引用 smoke_report。"""
    from app.eval.live_contract import (
        LIVE_FUNCTION_EXPECTED_TOTAL,
        LIVE_FUNCTION_SCRIPT_VERSION,
        LIVE_MANUAL_EXPECTED_TOTAL,
        LIVE_MANUAL_SCRIPT_VERSION,
    )

    resp = api_client.get("/health", headers={"X-API-Key": "demo-technician"})
    body = resp.json()
    assert "live_eval_summary" in body
    assert body.get("live_integration_manual_total") == LIVE_MANUAL_EXPECTED_TOTAL
    assert body.get("live_function_test_total") == LIVE_FUNCTION_EXPECTED_TOTAL
    assert body.get("live_integration_manual_script_version") == LIVE_MANUAL_SCRIPT_VERSION
    assert body.get("live_function_test_script_version") == LIVE_FUNCTION_SCRIPT_VERSION
    assert body.get("live_eval_all_ok") is True
    assert not body.get("live_eval_stale")
    assert "orchestration" in body
    assert body["orchestration"].get("llm_location") == "enterprise-rag_only_when_http"


def test_health_joint_verified_cleared_when_not_live(api_client, monkeypatch):
    """O4：非 live 运行时不得当场宣称 joint_evidence_live_verified。"""
    monkeypatch.setattr("app.main.is_rag_reachable", lambda force_check=False: False)
    with patch(
        "app.main._read_live_eval_meta",
        return_value={
            "joint_evidence_live_verified": True,
            "joint_evidence_claimable": True,
            "joint_evidence_mode": "live",
        },
    ):
        resp = api_client.get("/health", headers={"X-API-Key": "demo-technician"})
    body = resp.json()
    assert body.get("rag_mode") != "live" or not (body.get("rag") or {}).get("ok")
    assert body.get("joint_evidence_live_verified") is False
    assert body.get("joint_evidence_stale_vs_runtime") is True


def test_create_run_waiting_hitl(api_client):
    resp = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    assert body.get("engine") == "langgraph"
    assert body.get("work_order_draft")
    run_id = body["run_id"]

    trace = api_client.get(f"/runs/{run_id}/trace")
    assert trace.status_code == 200
    events = trace.json().get("events") or []
    nodes = [e["node"] for e in events]
    assert "hitl" in nodes


def test_create_run_draft_driven_no_parts_hints(api_client, fake_rag):
    """无 parts_hints 时配件预核应来自 RAG draft（FakeRag 默认推荐液压泵总成）。"""
    fake_rag.parts = ["液压泵总成"]
    resp = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json={
            "question": "长沙星沙 SY215C H103请报修处理",
            "station": "长沙星沙服务站",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    parts = body.get("parts_check") or {}
    assert parts.get("hints_source") == "rag_draft"
    assert parts.get("shortage") is True


def test_api_parts_hints_ignored_unless_allow_flag(api_client, fake_rag, monkeypatch):
    """ALLOW_DEMO_PARTS_HINTS=0 时丢弃 API parts_hints，改走 RAG draft。"""
    from app.config import get_settings

    fake_rag.parts = ["液压泵总成"]
    monkeypatch.setenv("ALLOW_DEMO_PARTS_HINTS", "0")
    get_settings.cache_clear()
    resp = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json={
            "question": "长沙星沙 SY215C H103请报修处理",
            "station": "长沙星沙服务站",
            "parts_hints": ["液压滤芯"],  # 有货；若注入会不缺料
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    parts = body.get("parts_check") or {}
    assert parts.get("demo_injected_hints") is False
    assert parts.get("hints_source") == "rag_draft"
    assert parts.get("shortage") is True  # draft 泵总成缺料
    monkeypatch.setenv("ALLOW_DEMO_PARTS_HINTS", "1")
    get_settings.cache_clear()


def test_hitl_forbidden_for_technician(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    assert create.json()["status"] == "waiting_hitl"
    resp = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-technician"},
        json={"decision": "approve", "note": "不应成功"},
    )
    assert resp.status_code == 403


def test_hitl_approve_by_chief(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    body = create.json()
    run_id = body["run_id"]
    assert body["status"] == "waiting_hitl"
    resp = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json=_approve_payload(body),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"


def test_hitl_approve_requires_layer_confirmations(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    resp = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json={"decision": "approve", "note": "一键批准应被拒"},
    )
    assert resp.status_code == 400
    assert "分层人确" in resp.text or "pending_layers" in resp.text


def test_playbook_run_p6_rejected(api_client):
    resp = api_client.post(
        "/playbooks/p6_chitchat/run",
        headers={"X-API-Key": "demo-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    meta = body.get("playbook_meta") or {}
    assert meta.get("validation_passed") is True


def test_playbook_validate_endpoint(api_client):
    resp = api_client.post(
        "/playbooks/p4_manual_only/validate",
        headers={"X-API-Key": "demo-technician"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("passed") is True
    assert body.get("playbook_id") == "p4_manual_only"
    assert body["run_summary"]["engine"] == "langgraph"
    assert body["run_summary"]["status"] == "succeeded"


def test_cancel_run(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_LOW_RISK_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    assert create.json()["status"] == "succeeded"
    resp = api_client.post(f"/runs/{run_id}/cancel", headers={"X-API-Key": "demo-chief"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_run_forbidden_for_technician(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_LOW_RISK_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    resp = api_client.post(f"/runs/{run_id}/cancel", headers={"X-API-Key": "demo-technician"})
    assert resp.status_code == 403


def test_get_run_not_found(api_client):
    assert api_client.get("/runs/nonexistent").status_code == 404


def test_policies_list(api_client):
    resp = api_client.get("/policies")
    assert resp.status_code == 200
    items = resp.json().get("items") or []
    assert any(i["id"] == "POL-CONFLICT-01" for i in items)
    assert all("trigger" in i for i in items)


def test_eval_compare_default_langgraph(api_client):
    resp = api_client.post("/eval/compare", headers={"X-API-Key": "demo-technician"})
    assert resp.status_code == 200
    summary = resp.json().get("summary") or {}
    assert summary.get("engine") == "langgraph"


def test_eval_compare_requires_api_key(api_client):
    resp = api_client.post("/eval/compare")
    assert resp.status_code == 422


def test_trace_public_view_redacts_events(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    full = api_client.get(f"/runs/{run_id}/trace")
    public = api_client.get(f"/runs/{run_id}/trace?view=public")
    assert len(full.json().get("events") or []) > 0
    assert public.json().get("events") == []
    assert public.json().get("view_mode") == "public"


def test_run_public_view_hides_trace_preview(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    body = api_client.get(f"/runs/{run_id}?view=public").json()
    assert body.get("trace_events") == []
    assert body.get("trace_preview") == []


def test_persistence_repair_requires_chief(api_client):
    ok = api_client.post("/persistence/repair", headers={"X-API-Key": "demo-chief"})
    assert ok.status_code == 200
    denied = api_client.post("/persistence/repair", headers={"X-API-Key": "demo-technician"})
    assert denied.status_code == 403


def test_playbook_chitchat_no_rag_trace(api_client):
    with patch("app.main.build_rag_client", lambda *a, **k: FakeRag()):
        resp = api_client.post("/playbooks/p6_chitchat/run", headers={"X-API-Key": "demo-key"})
    body = resp.json()
    nodes = [e["node"] for e in body.get("trace_events") or []]
    assert "rag" not in nodes


def test_hitl_409_when_not_waiting(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    body = create.json()
    run_id = body["run_id"]
    assert body["status"] == "waiting_hitl"
    api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json=_approve_payload(body, note="ok"),
    )
    resp = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json=_approve_payload(body, note="重复"),
    )
    assert resp.status_code == 409


def test_hitl_return_requires_note(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    assert create.json()["status"] == "waiting_hitl"
    resp = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json={"decision": "return", "note": ""},
    )
    assert resp.status_code in (400, 422)
    # 历史别名 edit 同样要求 note
    resp2 = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json={"decision": "edit", "note": ""},
    )
    assert resp2.status_code in (400, 422)


def test_hitl_return_terminates_without_mutating_draft(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    body = create.json()
    run_id = body["run_id"]
    draft_before = body.get("work_order_draft")
    resp = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json={"decision": "return", "note": "缺现场照片，退回重新开单"},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "succeeded"
    assert "POL-HITL-EDIT" in str(out.get("final_summary") or "")
    assert out.get("return_for_rework") is True
    assert out.get("return_note")
    assert out.get("reopen_hint")
    # 退回不改草稿内容
    assert out.get("work_order_draft") == draft_before
    assert out.get("work_order_submit") in (None, {})


def test_hitl_return_reopen_via_parent_run_id(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_HITL_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    ret = api_client.post(
        f"/runs/{run_id}/hitl",
        headers={"X-API-Key": "demo-chief"},
        json={"decision": "return", "note": "缺现场照片，退回重新开单"},
    )
    assert ret.status_code == 200
    reopen = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json={"question": "（沿用原单）", "parent_run_id": run_id},
    )
    assert reopen.status_code == 200
    body = reopen.json()
    assert body.get("parent_run_id") == run_id
    assert body["run_id"] != run_id
    # 非 return 父单应 400
    bad = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json={"question": "x", "parent_run_id": body["run_id"]},
    )
    assert bad.status_code == 400

def test_runs_list_after_create(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json={"question": "H103是什么意思"},
    )
    run_id = create.json()["run_id"]
    resp = api_client.get("/runs?limit=50")
    assert resp.status_code == 200
    ids = [r["run_id"] for r in resp.json().get("items") or []]
    assert run_id in ids


def test_run_persist_and_reload(api_client):
    create = api_client.post(
        "/runs",
        headers={"X-API-Key": "demo-technician"},
        json=_LOW_RISK_RUN_JSON,
    )
    run_id = create.json()["run_id"]
    assert create.json()["status"] == "succeeded"
    get_resp = api_client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["status"] == "succeeded"
    assert body["engine"] == "langgraph"
    assert body.get("work_order_state") == "ready_for_chief"
    assert body.get("work_order_draft")
    assert body.get("rag_client_mode") == "demo_offline"
    assert body.get("knowledge_port") in {"fixture", None} or body.get("rag_offline_mode") is True


def test_unknown_api_key_rejected_when_required(isolated_env, fake_rag, monkeypatch):
    monkeypatch.setenv("REQUIRE_KNOWN_API_KEY", "1")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    with patch("app.main.build_rag_client", lambda *a, **k: fake_rag):
        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/runs",
                headers={"X-API-Key": "not-a-real-key"},
                json={"question": "H103是什么意思"},
            )
            assert resp.status_code == 401


def test_read_runs_rejects_unknown_key_when_required(isolated_env, monkeypatch):
    monkeypatch.setenv("REQUIRE_KNOWN_API_KEY", "1")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/runs", headers={"X-API-Key": "not-a-real-key"})
        assert resp.status_code == 401
        resp2 = client.get("/runs/fake-id", headers={"X-API-Key": "not-a-real-key"})
        assert resp2.status_code == 401


def test_block_runs_when_live_required_and_rag_down(isolated_env, monkeypatch):
    """联调配置 REQUIRE_LIVE=1 时 RAG 不可达须 503。"""
    monkeypatch.setenv("COPILOT_RUNTIME_MODE", "live")
    monkeypatch.setenv("DEMO_OFFLINE", "0")
    monkeypatch.setenv("REQUIRE_LIVE", "1")
    monkeypatch.setenv("RAG_AUTO_FALLBACK", "0")
    monkeypatch.setenv("BLOCK_RUNS_WHEN_NOT_LIVE", "1")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    with patch("app.main.is_rag_reachable", lambda **k: False):
        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/runs",
                headers={"X-API-Key": "demo-technician"},
                json={"question": "SY215C H103请报修处理"},
            )
            assert resp.status_code == 503


def test_persistence_audit_endpoint(api_client):
    resp = api_client.get("/persistence/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert "healthy" in body
    assert "orphan_checkpoints" in body


def test_offline_fallback_when_rag_down(isolated_env, monkeypatch):
    monkeypatch.setenv("RAG_AUTO_FALLBACK", "1")
    monkeypatch.setenv("DEMO_OFFLINE", "0")
    monkeypatch.setenv("BLOCK_RUNS_WHEN_NOT_LIVE", "0")
    monkeypatch.setenv("REQUIRE_LIVE", "0")
    get_settings.cache_clear()

    def _offline(*a, **k):
        from app.tools.demo_rag import DemoRagClient

        return DemoRagClient(parts=["液压滤芯"])

    from fastapi.testclient import TestClient

    with patch("app.main.build_rag_client", _offline):
        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/runs",
                headers={"X-API-Key": "demo-technician"},
                json={"question": "SY215C H103请报修处理", "parts_hints": ["液压滤芯"]},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    assert body.get("rag_offline_mode") is True
    assert body.get("rag_client_mode") == "demo_offline"
