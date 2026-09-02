"""POL-INTENT-01 阈值 SSOT：gates / hitl_layers / nodes 须同源。"""

from __future__ import annotations

import json

import pytest

from app.domain.intent_rules import reload_intent_rules, resolve_intent_confidence_threshold
from app.policy.gates import evaluate_submit_eligible
from app.policy.hitl_layers import LAYER_INTENT, compute_pending_layers


@pytest.fixture(autouse=True)
def _restore_intent_rules():
    yield
    reload_intent_rules()


def _state(confidence: float):
    return {
        "role": "station_chief",
        "intent": "fault_dispatch",
        "intent_confidence": confidence,
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "critic_report": {"passed": True},
        "conflict_bundle": {"present": False},
        "parts_check": {"shortage": False},
        "service_ticket": {"station": "星沙", "second_visit": False},
        "hitl": {"required": False, "resolved": True, "decision": "approve", "confirmations": {}},
        "rag_degraded": False,
    }


def test_hitl_layers_and_gates_share_threshold(monkeypatch, tmp_path):
    import json

    from app.domain import intent_rules as ir

    data = json.loads(ir._RULES_PATH.read_text(encoding="utf-8"))
    data["intent_confidence_threshold"] = 0.7
    path = tmp_path / "intent_rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ir, "_RULES_PATH", path)
    from app.config import get_settings

    get_settings.cache_clear()
    reload_intent_rules()
    thr = resolve_intent_confidence_threshold()
    assert thr == 0.7

    low = _state(0.65)
    pending = compute_pending_layers(low)
    ok, blockers = evaluate_submit_eligible(low)
    assert LAYER_INTENT in pending
    assert ok is False
    assert any("POL-INTENT-01" in b for b in blockers)

    high = _state(0.75)
    assert LAYER_INTENT not in compute_pending_layers(high)
    ok2, blockers2 = evaluate_submit_eligible(high)
    assert ok2 is True
    assert not any("POL-INTENT-01" in b for b in blockers2)


def test_json_threshold_overrides_config(monkeypatch, tmp_path):
    import json

    from app.domain import intent_rules as ir

    data = json.loads(ir._RULES_PATH.read_text(encoding="utf-8"))
    data["intent_confidence_threshold"] = 0.6
    path = tmp_path / "intent_rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ir, "_RULES_PATH", path)
    reload_intent_rules()
    assert resolve_intent_confidence_threshold() == 0.6
