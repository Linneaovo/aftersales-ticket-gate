"""可选 L2 live 集成测试：需真 enterprise-rag :8001 + Copilot :8002（非 L1 契约桩）。

L1 Compose stub（evidence_tier=L1 / mode=contract_stub）会使 rag_mode=live，
但本文件不算 Live；应 skip。L1 契约请用 linkage-l1 / run_l1_linkage。
"""

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


def _rag_health() -> dict | None:
    try:
        r = httpx.get(f"{RAG_BASE}/health", timeout=_HEALTH_PROBE_TIMEOUT)
        if r.status_code != 200:
            return None
        body = r.json() if r.content else {}
        return body if isinstance(body, dict) else {}
    except Exception:
        return None


def _rag_is_l2_live(rag: dict) -> bool:
    """拒绝 L1 契约桩；真 RAG 常无 evidence_tier，但 mode 不得为 contract_stub。"""
    tier = str(rag.get("evidence_tier") or "").strip().upper()
    mode = str(rag.get("mode") or "").strip().lower()
    if tier == "L1" or mode == "contract_stub":
        return False
    if tier == "L2":
        return True
    # 无 tier 的真服务：只要不是 stub 即允许本文件探测
    return mode != "contract_stub"


def _rag_up() -> bool:
    rag = _rag_health()
    return rag is not None and _rag_is_l2_live(rag)


def _copilot_up() -> bool:
    try:
        r = httpx.get(f"{COPILOT_BASE}/health", headers=TECH, timeout=_HEALTH_PROBE_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _copilot_live_ready() -> bool:
    """Copilot 须 Live 配置，且 linkage_claim 不得为 L1（防 stub 冒充）。"""
    try:
        body = httpx.get(f"{COPILOT_BASE}/health", headers=TECH, timeout=_HEALTH_PROBE_TIMEOUT).json()
    except Exception:
        return False
    if body.get("runtime_mode") == "standalone" or body.get("demo_offline"):
        return False
    if body.get("rag_mode") != "live":
        return False
    claim = str(body.get("linkage_claim") or "").strip().lower()
    if claim in {"l1", "none"}:
        return False
    # http_live / L2 / 空（旧二进制）均可；再靠 RAG health 排除 stub
    return True


def _live_stack_up() -> bool:
    return _rag_up() and _copilot_up() and _copilot_live_ready()


_LIVE_SKIP_REASON = (
    "L2 Live 未就绪：需真 :8001+:8002（非 L1 contract_stub），"
    "copy .env.demo .env 后重启 Copilot（非 standalone/demo_offline）"
)


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
def test_live_health_engine_and_rag_mode():
    rag = httpx.get(f"{RAG_BASE}/health", timeout=10.0)
    assert rag.status_code == 200
    rag_body = rag.json()
    assert _rag_is_l2_live(rag_body if isinstance(rag_body, dict) else {})
    body = httpx.get(f"{COPILOT_BASE}/health", headers=TECH, timeout=10.0).json()
    assert body.get("engine") == "langgraph"
    assert body.get("rag_mode") == "live"
    assert str(body.get("linkage_claim") or "").lower() != "l1"


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
def test_live_p1_playbook_shortage_waiting_hitl():
    """缺料 HITL 走 playbook + RAG draft → parts，不手传 parts_hints。"""
    resp = httpx.post(
        f"{COPILOT_BASE}/playbooks/p1_xingsha_h103/run",
        headers=TECH,
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_hitl"
    assert body.get("engine") == "langgraph"
    assert body.get("rag_client_mode") == "live"
    assert body.get("rag_offline_mode") is False
    assert "ask" in (body.get("rag_linkage") or [])
    reasons = " ".join((body.get("hitl") or {}).get("reasons") or [])
    assert "POL-PARTS-01" in reasons


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
def test_live_p1b_playbook_no_shortage_succeeded():
    """有库存路径走 playbook p1b，不手传 parts_hints。"""
    resp = httpx.post(
        f"{COPILOT_BASE}/playbooks/p1b_no_shortage_ready/run",
        headers=TECH,
        timeout=120.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body.get("work_order_state") == "ready_for_chief"
    assert body.get("rag_client_mode") == "live"
    assert not (body.get("parts_check") or {}).get("shortage")


@pytest.mark.integration
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
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
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
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
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
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
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
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
@pytest.mark.skipif(not _live_stack_up(), reason=_LIVE_SKIP_REASON)
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
        json={
            "decision": "approve",
            "note": "站长确认",
            "confirmations": {
                layer: True for layer in list((body.get("hitl") or {}).get("pending_layers") or [])
            },
        },
        timeout=120.0,
    )
    assert approve.status_code == 200
    approved = approve.json()
    assert approved.get("status") == "succeeded"
    submit = approved.get("work_order_submit") or {}
    assert submit.get("destination") == "rag_mock_inbox"
    assert submit.get("is_production_ticket") is False
