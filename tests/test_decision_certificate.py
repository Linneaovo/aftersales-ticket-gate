"""Decision Certificate + 意图置信度。"""

from __future__ import annotations

from app.graph.nodes import INTENT_CONFIDENCE_THRESHOLD, classify_intent_detailed, score_fault_dispatch_signals
from app.graph.runner import public_view, run_until_pause
from app.graph.state import empty_state
from app.policy.decision_certificate import build_decision_certificate
from app.policy.hitl_layers import confirmations_covering
from app.policy.rules_catalog import POLICY_CATALOG_VERSION
from tests.test_core import FakeRag


def test_oral_fault_dispatch_high_confidence():
    intent, conf, signals = classify_intent_detailed(
        "长沙星沙 SY215C 报故障码 H103，客户反映动臂液压无力，请安排报修开单"
    )
    assert intent == "fault_dispatch"
    assert conf >= INTENT_CONFIDENCE_THRESHOLD
    assert "fault_code" in signals or "model" in signals


def test_low_confidence_signals_below_threshold():
    conf, signals = score_fault_dispatch_signals("动臂有点异响你们帮忙看看")
    assert conf < 1.0
    assert signals


def test_decision_certificate_on_hitl_run():
    client = FakeRag(parts=["液压泵总成"])
    st = empty_state(
        run_id="cert-p1",
        raw_input="长沙星沙服务站：SY215C 报故障码 H103，请报修开单",
        role="technician",
        api_key="demo-technician",
        parts_force_hints=["液压泵总成"],
        station_override="长沙星沙服务站",
    )
    out = run_until_pause(st, client=client, persist=False)
    assert out.get("status") == "waiting_hitl"
    cert = out.get("decision_certificate") or {}
    assert cert.get("schema") == "decision_certificate/v1"
    assert cert.get("kind") == "decision_snapshot"
    assert cert.get("display_name") == "Decision Snapshot"
    assert cert.get("assurance") == "state_snapshot_not_tamper_proof"
    assert cert.get("not_erp_dispatch") is True
    assert cert.get("is_production_ticket") is False
    assert cert.get("policy_catalog_version") == POLICY_CATALOG_VERSION
    assert cert.get("phase") == "pending"
    assert cert.get("policy_ids")
    assert (cert.get("station_ops") or {}).get("recommended_crew")
    assert "演示" in str((cert.get("station_ops") or {}).get("note") or "")
    view = public_view(out)
    assert view.get("decision_certificate", {}).get("phase") == "pending"
    assert view.get("intent_confidence") is not None
    assert view.get("intent_label") == "报修开单"
    assert view.get("not_erp_dispatch") is True


def test_build_certificate_resolved_fields():
    st = empty_state(
        run_id="cert-r",
        intent="fault_dispatch",
        intent_confidence=0.9,
        status="succeeded",
        hitl={
            "resolved": True,
            "decision": "approve",
            "reasons": ["[POL-PARTS-01] x"],
            "confirmations": {"shortage": True},
        },
        work_order_submit={
            "ticket_id": "T1",
            "destination": "rag_mock_inbox",
            "is_production_ticket": False,
        },
        parts_check={"shortage": True, "shortage_items": ["泵"], "hints_source": "force_hints"},
    )
    cert = build_decision_certificate(st, phase="resolved")
    assert cert["hitl_decision"] == "approve"
    assert cert["destination"] == "rag_mock_inbox"
    assert cert["is_production_ticket"] is False
    assert cert["assurance"] == "state_snapshot_not_tamper_proof"
    assert cert["ticket_id"] == "T1"
    assert confirmations_covering(["shortage"]) == {"shortage": True}


def test_certificate_required_fields_present():
    from app.policy.decision_certificate import REQUIRED_CERTIFICATE_FIELDS, validate_certificate

    st = empty_state(run_id="cert-req", intent="fault_dispatch", status="waiting_hitl", role="technician")
    cert = build_decision_certificate(st, phase="pending")
    missing = [f for f in REQUIRED_CERTIFICATE_FIELDS if f not in cert]
    assert not missing, f"certificate missing required fields: {missing}"
    assert cert["assurance"] == "state_snapshot_not_tamper_proof"
    assert validate_certificate(cert) == []


def test_validate_certificate_rejects_tamper_claim():
    from app.policy.decision_certificate import validate_certificate

    st = empty_state(run_id="cert-bad", intent="fault_dispatch", status="waiting_hitl", role="technician")
    cert = build_decision_certificate(st, phase="pending")
    cert["assurance"] = "tamper_proof_audit"
    cert["is_production_ticket"] = True
    errs = validate_certificate(cert)
    assert any("assurance" in e for e in errs)
    assert any("is_production_ticket" in e for e in errs)


def test_policy_catalog_lock_requires_bump_on_core_text_change():
    from app.policy.rules_catalog import (
        POLICY_CATALOG_LOCK,
        POLICY_CATALOG_VERSION,
        core_policies_fingerprint,
    )

    assert POLICY_CATALOG_LOCK["version"] == POLICY_CATALOG_VERSION, (
        "POLICY_CATALOG_LOCK.version 须与 POLICY_CATALOG_VERSION 同步 bump"
    )
    fp = core_policies_fingerprint()
    assert POLICY_CATALOG_LOCK["core_fingerprint"] == fp, (
        "CORE 策略文案已变：请 bump POLICY_CATALOG_VERSION，并更新 POLICY_CATALOG_LOCK"
    )
