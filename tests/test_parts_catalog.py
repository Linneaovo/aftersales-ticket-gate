"""配件台账 master data 回归。"""

from __future__ import annotations

from app.domain.parts_master import normalize_part_hints, reset_parts_master_cache, resolve_part_hint
from app.domain.ticket_extract import extract_service_ticket
from app.policy.hitl_layers import LAYER_WEATHER, compute_pending_layers
from app.tools.parts_ledger import check_parts, hints_from_rag_and_draft, load_parts_ledger


def test_parts_ledger_has_expanded_skus():
    ledger = load_parts_ledger()
    assert len(ledger.get("items") or []) >= 14
    assert isinstance(ledger.get("aliases"), dict)


def test_resolve_new_catalog_entries():
    reset_parts_master_cache()
    row = resolve_part_hint("行走马达")
    assert row is not None
    assert row.get("part_no") == "WLK-MTR-03"
    assert int(row.get("stock") or 0) == 0


def test_walk_motor_shortage_via_check_parts():
    reset_parts_master_cache()
    out = check_parts(["行走马达"])
    assert out.get("shortage") is True
    assert "行走马达" in " ".join(out.get("shortage_items") or [])


def test_normalize_maps_alias_to_canonical():
    reset_parts_master_cache()
    canonical, mapping = normalize_part_hints(["泵总成"])
    assert any("液压泵" in c for c in canonical)
    assert mapping[0].get("matched") is True
    assert mapping[0].get("match_via") == "alias"


def test_part_no_exact_match():
    reset_parts_master_cache()
    row = resolve_part_hint("hy-pump-08")
    assert row is not None
    assert row.get("name") == "液压泵总成"


def test_free_substring_no_longer_matches():
    """短子串「阀」不得误命中主控电磁阀/主控阀组。"""
    reset_parts_master_cache()
    assert resolve_part_hint("阀") is None
    out = check_parts(["阀"])
    assert out.get("unknown_parts") is True
    assert out.get("shortage") is False


def test_draft_hints_preferred_over_answer_tokens():
    draft = {"draft": {"recommended_parts": ["HY-PUMP-08"]}}
    rag = {"answer": "建议更换电磁阀与滤芯"}
    hints = hints_from_rag_and_draft(rag, draft)
    assert "液压泵总成" in hints


def test_outdoor_weather_risk_opt_in_only(monkeypatch):
    """雨季关键词可抽取；ENABLE_WEATHER_POL 关则 HITL/pending/submit 均不触发 weather。"""
    from app.config import get_settings
    from app.graph.nodes import _evaluate_hitl_gates
    from app.policy.gates import evaluate_submit_eligible

    ticket = extract_service_ticket("星沙 SY215C 雨季户外作业 H103 请报修")
    assert ticket.get("outdoor_weather_risk") is True
    state = {
        "intent": "fault_dispatch",
        "service_ticket": ticket,
        "conflict_bundle": {},
        "parts_check": {"shortage": False},
        "critic_report": {"passed": True, "force_hitl": False, "reasons": []},
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "hitl": {},
        "role": "technician",
        "auto_submit": False,
    }
    get_settings.cache_clear()
    monkeypatch.setenv("ENABLE_WEATHER_POL", "0")
    get_settings.cache_clear()
    assert LAYER_WEATHER not in compute_pending_layers(state)
    need_off, reasons_off = _evaluate_hitl_gates(
        state,  # type: ignore[arg-type]
        intent="fault_dispatch",
        critic=state["critic_report"],
        parts=state["parts_check"],
        conflict={},
        ticket=ticket,
        hitl={},
        settings=get_settings(),
    )
    assert "POL-WEATHER-01" not in "".join(reasons_off)

    monkeypatch.setenv("ENABLE_WEATHER_POL", "1")
    get_settings.cache_clear()
    assert LAYER_WEATHER in compute_pending_layers(state)
    need_on, reasons_on = _evaluate_hitl_gates(
        state,  # type: ignore[arg-type]
        intent="fault_dispatch",
        critic=state["critic_report"],
        parts=state["parts_check"],
        conflict={},
        ticket=ticket,
        hitl={},
        settings=get_settings(),
    )
    assert need_on is True
    assert "POL-WEATHER-01" in "".join(reasons_on)
    eligible, blockers = evaluate_submit_eligible(state)
    assert eligible is False
    assert any("POL-WEATHER-01" in b for b in blockers)

    monkeypatch.delenv("ENABLE_WEATHER_POL", raising=False)
    get_settings.cache_clear()


def test_machine_model_mismatch_blocks_as_ledger_layer():
    """票面机型与台账 machine_models 不符 → model_mismatch + POL-PARTS-02 层。"""
    reset_parts_master_cache()
    out = check_parts(["液压泵总成"], machine_model="SR155")
    assert out.get("model_mismatch") is True
    assert out.get("shortage") is False
    assert any(i.get("status") == "model_mismatch" for i in out.get("items") or [])
    state = {
        "intent": "fault_dispatch",
        "service_ticket": {"station": "长沙星沙服务站", "machine_model": "SR155"},
        "conflict_bundle": {},
        "parts_check": out,
        "critic_report": {},
    }
    from app.policy.hitl_layers import LAYER_LEDGER

    assert LAYER_LEDGER in compute_pending_layers(state)


def test_machine_model_family_compatible():
    reset_parts_master_cache()
    out = check_parts(["液压泵总成"], machine_model="SY215C")
    assert out.get("model_mismatch") is False


def test_answer_token_hints_opt_in(monkeypatch):
    from app.config import get_settings

    rag = {"answer": "建议更换液压滤芯并检查管路"}
    monkeypatch.setenv("ALLOW_ANSWER_TOKEN_HINTS", "0")
    get_settings.cache_clear()
    assert hints_from_rag_and_draft(rag, None) == []

    monkeypatch.setenv("ALLOW_ANSWER_TOKEN_HINTS", "1")
    get_settings.cache_clear()
    hints = hints_from_rag_and_draft(rag, None)
    assert any("滤芯" in h for h in hints)
    monkeypatch.delenv("ALLOW_ANSWER_TOKEN_HINTS", raising=False)
    get_settings.cache_clear()


def test_ledger_hot_reload_same_process(tmp_path, monkeypatch):
    """E1：改临时 ledger 后同进程第二次 check_parts 必须看到新 stock。"""
    import json
    from pathlib import Path

    from app.config import get_settings
    from app.tools.parts_ledger import JsonPartsLedger

    src = Path(__file__).resolve().parents[1] / "data" / "parts_ledger.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    for row in data.get("items") or []:
        if str(row.get("part_no")) == "60277011":
            row["stock"] = 0
            row["qty_available"] = 0
    ledger_path = tmp_path / "parts_ledger.json"
    ledger_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PARTS_LEDGER_PATH", str(ledger_path))
    get_settings.cache_clear()
    reset_parts_master_cache()

    client = JsonPartsLedger()
    first = client.check_parts(["60277011"])
    assert first.get("shortage") is True

    for row in data.get("items") or []:
        if str(row.get("part_no")) == "60277011":
            row["stock"] = 9
            row["qty_available"] = 9
    ledger_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    second = client.check_parts(["60277011"])
    assert second.get("shortage") is False
    assert any(int(i.get("stock") or 0) == 9 for i in second.get("items") or [])
    monkeypatch.delenv("PARTS_LEDGER_PATH", raising=False)
    get_settings.cache_clear()
    reset_parts_master_cache()


def test_empty_hints_no_false_shortage():
    """空 hints：不伪造缺料；needed 可为 False。"""
    reset_parts_master_cache()
    out = check_parts([])
    assert out.get("shortage") is False
    assert out.get("unknown_parts") is False
    assert not (out.get("shortage_items") or [])


def test_ledger_degraded_flag_forces_parts_02_layer():
    """台账降级标记 → POL-PARTS-02 / LAYER_LEDGER，不得按缺料静默调拨。"""
    from app.policy.gates import evaluate_submit_eligible
    from app.policy.hitl_layers import LAYER_LEDGER, compute_pending_layers

    parts = {
        "needed": True,
        "shortage": False,
        "unknown_parts": False,
        "ledger_degraded": True,
        "items": [],
        "suggested_action": "confirm_ledger",
    }
    state = {
        "intent": "fault_dispatch",
        "role": "technician",
        "service_ticket": {"station": "长沙星沙服务站"},
        "conflict_bundle": {},
        "parts_check": parts,
        "critic_report": {"passed": True, "force_hitl": False, "reasons": []},
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "hitl": {},
        "auto_submit": False,
    }
    assert LAYER_LEDGER in compute_pending_layers(state)
    eligible, blockers = evaluate_submit_eligible(state)
    assert eligible is False
    assert "POL-PARTS-02" in " ".join(blockers)


def test_shortage_plus_unknown_keeps_parts_01():
    """E2：可解析缺料件 + 未知件并存 → shortage 仍成立，门禁同时挂 01+02。"""
    from app.policy.gates import evaluate_submit_eligible
    from app.policy.hitl_layers import LAYER_LEDGER, LAYER_SHORTAGE, compute_pending_layers

    reset_parts_master_cache()
    out = check_parts(["液压泵总成", "NOT-A-REAL-PART-XYZ"])
    assert out.get("shortage") is True
    assert out.get("unknown_parts") is True
    state = {
        "intent": "fault_dispatch",
        "role": "technician",
        "service_ticket": {"station": "长沙星沙服务站"},
        "conflict_bundle": {},
        "parts_check": out,
        "critic_report": {"passed": True, "force_hitl": False, "reasons": []},
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "hitl": {},
        "auto_submit": False,
    }
    layers = compute_pending_layers(state)
    assert LAYER_SHORTAGE in layers
    assert LAYER_LEDGER in layers
    eligible, blockers = evaluate_submit_eligible(state)
    assert eligible is False
    joined = " ".join(blockers)
    assert "POL-PARTS-01" in joined
    assert "POL-PARTS-02" in joined


def test_partial_multi_part_shortage_keeps_parts_01():
    """多件号：一缺料一有库存 → shortage 仍真，POL-PARTS-01 可触发。"""
    from app.policy.gates import evaluate_submit_eligible
    from app.policy.hitl_layers import LAYER_SHORTAGE, compute_pending_layers

    reset_parts_master_cache()
    out = check_parts(["液压泵总成", "液压滤芯"])
    assert out.get("shortage") is True
    assert "液压泵总成" in (out.get("shortage_items") or []) or any(
        "泵" in str(x) for x in (out.get("shortage_items") or [])
    )
    state = {
        "intent": "fault_dispatch",
        "role": "technician",
        "service_ticket": {"station": "长沙星沙服务站", "machine_model": "SY215C"},
        "conflict_bundle": {},
        "parts_check": out,
        "critic_report": {"passed": True, "force_hitl": False, "reasons": []},
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "hitl": {},
        "auto_submit": False,
    }
    assert LAYER_SHORTAGE in compute_pending_layers(state)
    eligible, blockers = evaluate_submit_eligible(state)
    assert eligible is False
    assert "POL-PARTS-01" in " ".join(blockers)
