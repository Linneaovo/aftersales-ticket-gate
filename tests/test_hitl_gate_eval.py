"""HITL 闭集门禁评测回归。"""

from __future__ import annotations

from app.eval.hitl_gate_eval import build_hitl_gate_report


def test_hitl_gate_goldset_all_ok():
    report = build_hitl_gate_report()
    assert report.get("schema") == "hitl_gate_report/v1"
    assert report.get("mode") == "offline_goldset"
    assert int(report.get("n_cases") or 0) >= 10
    assert report.get("all_ok") is True, [
        r["id"] for r in (report.get("results") or []) if not r.get("ok")
    ]
    metrics = report.get("metrics") or {}
    assert metrics.get("should_hitl_recall") == 1.0
    assert metrics.get("false_hitl_rate") == 0.0
    assert metrics.get("leak_submit_count") == 0
