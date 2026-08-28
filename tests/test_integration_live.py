"""可选 live 集成测试：需 enterprise-rag :8001 + Copilot :8002 运行。"""

from __future__ import annotations

import httpx
import pytest

COPILOT_BASE = "http://127.0.0.1:8002"
RAG_BASE = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}
PARTS = {"X-API-Key": "demo-parts", "Content-Type": "application/json"}


# Copilot 繁忙时 health 可能 >2s；过短会导致误 SKIP（服务实际在跑）
_HEALTH_PROBE_TIMEOUT = 15.0


def _rag_up() -> bool:
    try:
        r = httpx.get(f"{RAG_BASE}/health", timeout=_HEALTH_PROBE_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _copilot_up() -> bool:
    try:
        r = httpx.get(f"{COPILOT_BASE}/health", headers=TECH, timeout=_HEALTH_PROBE_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _live_stack_up() -> bool:
    return _rag_up() and _copilot_up()


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_health_engine_and_rag_mode():
    rag = httpx.get(f"{RAG_BASE}/health", timeout=10.0)
    assert rag.status_code == 200
    body = httpx.get(f"{COPILOT_BASE}/health", headers=TECH, timeout=10.0).json()
    assert body.get("engine") == "langgraph"
    assert body.get("rag_mode") == "live"


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_create_run_shortage_waiting_hitl():
    resp = httpx.post(
        f"{COPILOT_BASE}/runs",
        headers=TECH,
        json={
            "question": "长沙星沙 SY215C H103请报修处理",
            "parts_hints": ["液压泵总成"],
            "station": "长沙星沙服务站",
        },
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    assert body.get("engine") == "langgraph"
    assert body.get("rag_client_mode") == "live"
    assert body.get("rag_offline_mode") is False
    assert "ask" in (body.get("rag_linkage") or [])


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_low_risk_technician_succeeded():
    resp = httpx.post(
        f"{COPILOT_BASE}/runs",
        headers=TECH,
        json={
            "question": "长沙星沙 SY215C H103请报修处理",
            "parts_hints": ["液压滤芯"],
            "station": "长沙星沙服务站",
        },
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body.get("work_order_state") == "ready_for_chief"
    assert body.get("rag_client_mode") == "live"


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_p2_conflict_waits_hitl_not_reject():
    """POL-CONFLICT-02 仅 force_hitl，冲突场景须 waiting_hitl 而非 rejected。"""
    resp = httpx.post(
        f"{COPILOT_BASE}/playbooks/p2_warranty_conflict/run",
        headers=TECH,
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    assert body["intent"] == "conflict_review"
    meta = body.get("playbook_meta") or {}
    assert meta.get("validation_passed") is True
    reasons = " ".join((body.get("hitl") or {}).get("reasons") or [])
    assert "POL-CONFLICT-01" in reasons


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_p8_parts_clerk_conflict_waits_hitl():
    resp = httpx.post(
        f"{COPILOT_BASE}/playbooks/p8_parts_clerk_conflict/run",
        headers=PARTS,
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    meta = body.get("playbook_meta") or {}
    assert meta.get("validation_passed") is True
    reasons = " ".join((body.get("hitl") or {}).get("reasons") or [])
    assert "POL-CONFLICT-01" in reasons


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_p4_knowledge_only_succeeded_no_draft():
    resp = httpx.post(
        f"{COPILOT_BASE}/playbooks/p4_manual_only/run",
        headers=TECH,
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["intent"] == "knowledge_only"
    assert body.get("work_order_draft") is None
    meta = body.get("playbook_meta") or {}
    assert meta.get("validation_passed") is True


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_oral_off_script_fault_dispatch():
    from app.eval.compare import ORAL_SMOKE_QUESTIONS

    oral_q = ORAL_SMOKE_QUESTIONS[-1]
    resp = httpx.post(
        f"{COPILOT_BASE}/runs",
        headers=TECH,
        json={"question": oral_q, "station": "长沙星沙服务站"},
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("intent") == "fault_dispatch"
    assert body.get("rag_client_mode") == "live"


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason="RAG :8001 或 Copilot :8002 未启动")
def test_live_p1_playbook_validation_and_hitl_approve():
    resp = httpx.post(f"{COPILOT_BASE}/playbooks/p1_xingsha_h103/run", headers=TECH, timeout=120.0)
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    meta = body.get("playbook_meta") or {}
    assert meta.get("validation_passed") is True
    run_id = body.get("run_id")
    assert run_id
    approve = httpx.post(
        f"{COPILOT_BASE}/runs/{run_id}/hitl",
        headers=CHIEF,
        json={"decision": "approve", "note": "站长确认"},
        timeout=120.0,
    )
    assert approve.status_code == 200
    approved = approve.json()
    assert approved.get("status") == "succeeded"
    submit = approved.get("work_order_submit") or {}
    assert submit.get("destination") == "rag_mock_inbox"
    assert submit.get("is_production_ticket") is False
