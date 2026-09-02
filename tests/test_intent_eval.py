"""意图评测：fit≥50 + held_out≥30，双栏门槛；expect_rule_id 与边界句。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.intent_rules import classify_intent_detailed, fired_rule_id
from app.graph.nodes import classify_intent

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_intent_fit_and_held_out_floors():
    fit = _load(ROOT / "data" / "eval" / "intent_cases.jsonl")
    held = _load(ROOT / "data" / "eval" / "intent_cases_held_out.jsonl")
    assert len(fit) >= 50
    assert len(held) >= 30
    fit_acc = sum(1 for r in fit if classify_intent(r["question"]) == r["expect_intent"]) / len(fit)
    held_acc = sum(1 for r in held if classify_intent(r["question"]) == r["expect_intent"]) / len(held)
    assert fit_acc >= 0.85, f"fit accuracy {fit_acc}"
    assert held_acc >= 0.75, f"held_out accuracy {held_acc}"


def test_intent_cases_pin_expect_rule_id():
    fit = _load(ROOT / "data" / "eval" / "intent_cases.jsonl")
    held = _load(ROOT / "data" / "eval" / "intent_cases_held_out.jsonl")
    assert all(r.get("expect_rule_id") for r in fit)
    assert all(r.get("expect_rule_id") for r in held)
    for r in fit + held:
        _, _, signals = classify_intent_detailed(r["question"])
        assert fired_rule_id(signals) == r["expect_rule_id"], r["id"]


def test_held_out_has_boundary_conflict_and_knowledge():
    held = _load(ROOT / "data" / "eval" / "intent_cases_held_out.jsonl")
    boundaries = {r.get("boundary") for r in held if r.get("boundary")}
    assert "conflict_vs_fault" in boundaries
    assert "knowledge_only_vs_fault" in boundaries
    assert sum(1 for r in held if r.get("boundary") == "conflict_vs_fault") >= 4
    assert sum(1 for r in held if r.get("boundary") == "knowledge_only_vs_fault") >= 4
