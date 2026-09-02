"""governance scorecard + synergy 聚合回归（离线）。"""

from __future__ import annotations

from app.eval.governance_scorecard import build_scorecard, scorecard_is_stale
from app.eval.synergy_checks import apply_synergy_to_claimability, build_synergy_checks


def test_scorecard_builds_without_hand_fill():
    card = build_scorecard()
    assert card.get("schema") == "governance_scorecard/v1"
    assert card.get("hand_filled") is False
    names = {m["name"] for m in card.get("metrics") or []}
    assert "hitl_gate_agreement" in names
    assert "leak_submit_rate" in names
    assert "parts_gate_ab_ok" in names
    assert "degrade_blocks_auto_submit" in names
    assert "core_policy_evidence_coverage" in names
    assert "contract_drift" in names
    # degrade 进程内断言必须绿
    degrade = next(m for m in card["metrics"] if m["name"] == "degrade_blocks_auto_submit")
    assert degrade["ok"] is True


def test_standalone_scorecard_does_not_require_joint_leak():
    card = build_scorecard(profile="standalone")
    assert card["all_ok"] is True
    leak = next(m for m in card["metrics"] if m["name"] == "leak_submit_rate")
    assert leak.get("required") is False
    outbox = next(m for m in card["metrics"] if m["name"] == "file_outbox_port_ok")
    assert outbox["ok"] is True
    hitl = next(m for m in card["metrics"] if m["name"] == "hitl_gate_agreement")
    assert hitl["ok"] is True
    assert int((hitl.get("value") or {}).get("n_cases") or 0) >= 25
    intent = next(m for m in card["metrics"] if m["name"] == "intent_held_out")
    assert intent.get("required") is True
    assert intent["ok"] is True
    cost = next(m for m in card["metrics"] if m["name"] == "false_hitl_cost_proxy")
    assert cost.get("required") is False
    hitl = next(m for m in card["metrics"] if m["name"] == "hitl_gate_agreement")
    assert int((hitl.get("value") or {}).get("n_cases") or 0) >= 25
    intent = next(m for m in card["metrics"] if m["name"] == "intent_held_out")
    assert intent.get("required") is True
    assert intent["ok"] is True
    proxy = next(m for m in card["metrics"] if m["name"] == "false_hitl_cost_proxy")
    assert proxy.get("required") is False


def test_synergy_required_gates_claimability():
    pack = {
        "live_verified": True,
        "mode": "live",
        "live_sample_p1": {
            "rag_client_mode": "live",
            "status": "waiting_hitl",
            "policy_ids": ["POL-PARTS-01"],
            "ownership_ok": True,
            "after_approve": {"source": "copilot_hitl", "inbox_source": "copilot_hitl"},
        },
        "parts_gate_ab": {
            "offline": {"present": True, "all_ok": True},
            "live": {"present": True, "all_ok": True},
        },
        "live_probe": {"contract_version_match": True},
    }
    out = apply_synergy_to_claimability(dict(pack))
    assert out["synergy_checks"]["required_ok"] is True
    assert out["portfolio_claimable"] is True

    bad = dict(pack)
    bad["live_sample_p1"] = dict(pack["live_sample_p1"], ownership_ok=False)
    out_bad = apply_synergy_to_claimability(bad)
    assert out_bad["synergy_checks"]["required_ok"] is False
    assert out_bad["portfolio_claimable"] is False


def test_synergy_checks_shape():
    checks = build_synergy_checks({})
    ids = [c["id"] for c in checks["checks"]]
    assert ids == [
        "draft_then_gate",
        "hitl_then_inbox",
        "probe_not_business",
        "parts_ab_live",
        "contract_aligned",
        "degrade_blocks_auto_submit",
        "acl_l1_or_l2",
    ]
    assert "F3" in (checks.get("failure_mode_coverage") or {})
    assert "F6" in (checks.get("failure_mode_coverage") or {})
    cov = checks.get("failure_mode_required_coverage") or {}
    assert cov.get("total") == 7
    assert "F8" in (cov.get("required") or [])
    acl = next(c for c in checks["checks"] if c["id"] == "acl_l1_or_l2")
    assert acl.get("required") is True
