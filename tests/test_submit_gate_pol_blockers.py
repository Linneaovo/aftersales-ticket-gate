"""POL 负向门禁：每条 blocker 至少一个最小用例。"""

from __future__ import annotations

import pytest

from app.policy.gates import evaluate_submit_eligible
from app.policy.hitl_layers import (
    LAYER_CONFLICT,
    LAYER_DEGRADE,
    LAYER_INTENT,
    LAYER_LEDGER,
    LAYER_SHORTAGE,
    LAYER_SLA,
    LAYER_STATION,
    LAYER_WEATHER,
)


def _base(**overrides):
    state = {
        "role": "station_chief",
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "critic_report": {"passed": True},
        "conflict_bundle": {"present": False},
        "parts_check": {"shortage": False},
        "service_ticket": {"station": "星沙", "second_visit": False, "urgent": False},
        "hitl": {"required": False, "resolved": True, "decision": "approve", "confirmations": {}},
        "rag_degraded": False,
        "intent": "fault_dispatch",
        "intent_confidence": 0.9,
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    "pol_id,state_overrides,need_confirm",
    [
        ("POL-CONFLICT-01", {"conflict_bundle": {"present": True}}, LAYER_CONFLICT),
        ("POL-PARTS-01", {"parts_check": {"shortage": True, "note": "缺液压泵"}}, LAYER_SHORTAGE),
        (
            "POL-PARTS-02",
            {"parts_check": {"shortage": False, "ledger_degraded": True, "note": "台账降级"}},
            LAYER_LEDGER,
        ),
        ("POL-DEGRADE-01", {"rag_degraded": True}, LAYER_DEGRADE),
        ("POL-SLA-01", {"service_ticket": {"station": "星沙", "second_visit": True}}, LAYER_SLA),
        ("POL-SLA-02", {"service_ticket": {"station": "星沙", "urgent": True}}, LAYER_SLA),
        ("POL-STATION-01", {"service_ticket": {"station": "", "second_visit": False}}, LAYER_STATION),
        ("POL-INTENT-01", {"intent_confidence": 0.2}, LAYER_INTENT),
        ("POL-ROLE-01", {"role": "technician", "hitl": {"required": False, "resolved": False}}, None),
        ("POL-HITL-WAIT", {"hitl": {"required": True, "resolved": False}}, None),
        ("POL-HITL-REJECT", {"hitl": {"required": True, "resolved": True, "decision": "reject"}}, None),
        ("POL-HITL-EDIT", {"hitl": {"required": True, "resolved": True, "decision": "return"}}, None),
    ],
)
def test_submit_gate_pol_blockers(pol_id, state_overrides, need_confirm):
    ok, blockers = evaluate_submit_eligible(_base(**state_overrides))
    assert ok is False
    joined = " ".join(blockers)
    assert pol_id in joined
    if need_confirm:
        ok2, _ = evaluate_submit_eligible(
            _base(
                **state_overrides,
                hitl={
                    "required": True,
                    "resolved": True,
                    "decision": "approve",
                    "confirmations": {need_confirm: True},
                },
            )
        )
        # 单 layer 确认可能仍被其他 POL 挡；至少该 POL 不再出现
        if pol_id not in ("POL-ROLE-01",):
            assert pol_id not in " ".join(_) or ok2


def test_pol_weather_01_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_WEATHER_POL", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    ok, blockers = evaluate_submit_eligible(
        _base(service_ticket={"station": "星沙", "outdoor_weather_risk": True})
    )
    assert ok is False
    assert "POL-WEATHER-01" in " ".join(blockers)
    ok2, blockers2 = evaluate_submit_eligible(
        _base(
            service_ticket={"station": "星沙", "outdoor_weather_risk": True},
            hitl={
                "required": True,
                "resolved": True,
                "decision": "approve",
                "confirmations": {LAYER_WEATHER: True},
            },
        )
    )
    assert "POL-WEATHER-01" not in " ".join(blockers2)
