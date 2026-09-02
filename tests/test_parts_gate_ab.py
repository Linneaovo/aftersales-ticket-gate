"""缺料门禁 A/B：stock 翻转 → POL-PARTS-01 有无。"""

from __future__ import annotations

from app.eval.parts_gate_ab import run_parts_gate_ab


def test_parts_gate_ab_offline(isolated_env):
    report = run_parts_gate_ab()
    assert report["all_ok"], report
    a = report["cases"]["A_shortage_pump"]["result"]
    b = report["cases"]["B_in_stock_filter"]["result"]
    assert a["has_pol_parts_01"] is True
    assert a["shortage"] is True
    assert b["has_pol_parts_01"] is False
    assert b["shortage"] is False


def test_nest_parts_gate_ab_artifacts_forbid_live_ok():
    """E3：假包/仅 artifacts 不得出现 live.all_ok=true。"""
    from app.eval.parts_gate_ab import nest_parts_gate_ab

    nested = nest_parts_gate_ab(
        offline={"present": True, "all_ok": True, "rag_mode": "fakerag_stub"},
        live={
            "present": False,
            "all_ok": False,
            "skip_reason": "from_artifacts_only_no_live_ab",
        },
    )
    assert nested["offline"]["all_ok"] is True
    assert nested["live"]["present"] is False
    assert nested["live"]["all_ok"] is False
    assert nested["all_ok"] is True  # 兼容读法=offline
