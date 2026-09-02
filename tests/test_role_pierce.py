"""角色打穿：配件员在 Copilot 侧冲突脱敏 + 不可直提（对接 RAG demo-parts 叙事）。"""

from __future__ import annotations

from app.graph.runner import public_view
from app.graph.state import empty_state
from app.policy.decision_certificate import build_decision_certificate
from app.policy.gates import can_submit, filter_conflict_for_role
from app.policy.rules_catalog import CORE_POLICIES, POLICY_CATALOG_VERSION


def test_parts_clerk_cannot_submit_direct():
    assert can_submit("parts_clerk") is False
    assert can_submit("station_chief") is True


def test_role_pierce_conflict_redaction_and_certificate():
    """同一 persona=demo-parts：Copilot 冲突脱敏；证书带 catalog version。

    RAG 侧对应：配件员可见 parts ACL、技师不可见内部备货指引（enterprise-rag 演示）。
    """
    conflict = {
        "present": True,
        "items": [{"a": "24个月", "b": "36个月"}],
        "policy": "no_arbitration",
        "requires_chief": True,
    }
    redacted = filter_conflict_for_role(conflict, "parts_clerk")
    assert redacted is not None
    assert redacted.get("redacted") is True
    assert redacted.get("items") == []

    st = empty_state(
        run_id="pierce-parts",
        role="parts_clerk",
        intent="conflict_review",
        status="waiting_hitl",
        conflict_bundle=conflict,
        hitl={
            "required": True,
            "reasons": ["[POL-CONFLICT-01] 制度/质保冲突须并列展示且站长人确，不作自动裁决"],
            "pending_layers": ["conflict"],
            "resolved": False,
            "confirmations": {},
        },
        rag_result={
            "sources": [{"score": 0.9, "chunk": {"source": "warranty_v1.md", "doc_id": "w1"}}],
            "grounded": True,
        },
    )
    cert = build_decision_certificate(st, phase="pending")
    assert cert["schema"] == "decision_certificate/v1"
    assert cert["policy_catalog_version"] == POLICY_CATALOG_VERSION
    assert "POL-CONFLICT-01" in cert["policy_ids"]
    assert cert["conflict_present"] is True
    assert cert["citation_refs"]
    assert cert["is_production_ticket"] is False

    view = public_view(st)
    assert (view.get("conflict_bundle") or {}).get("redacted") is True
    st2 = {**st, "decision_certificate": cert}
    view2 = public_view(st2)  # type: ignore[arg-type]
    assert view2.get("decision_certificate", {}).get("policy_catalog_version") == POLICY_CATALOG_VERSION


def test_interview_core_policies_five():
    assert len(CORE_POLICIES) == 5
    assert "POL-PARTS-01" in CORE_POLICIES
    assert "POL-WEATHER-01" not in CORE_POLICIES
