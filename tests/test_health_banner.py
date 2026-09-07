"""mode_banner_kind：API 不可达不得回落「联调」。"""

from __future__ import annotations

from app.ui.health_banner import mode_banner_kind


def test_empty_health_is_unreachable():
    assert mode_banner_kind(None) == "unreachable"
    assert mode_banner_kind({}) == "unreachable"
    assert mode_banner_kind({"_ui_unreachable": True}) == "unreachable"
    assert mode_banner_kind({"rag_mode": "live"}) == "unreachable"  # 缺 runtime_mode


def test_standalone_and_linkage_kinds():
    assert mode_banner_kind({"runtime_mode": "standalone"}) == "standalone"
    assert mode_banner_kind(
        {"runtime_mode": "live", "linkage_claim": "L1", "rag_evidence_tier": "L1"}
    ) == "l1"
    assert mode_banner_kind(
        {"runtime_mode": "live", "linkage_claim": "L2", "rag_evidence_tier": "L2"}
    ) == "l2"
    assert mode_banner_kind({"runtime_mode": "live", "linkage_claim": "http_live"}) == "joint"
