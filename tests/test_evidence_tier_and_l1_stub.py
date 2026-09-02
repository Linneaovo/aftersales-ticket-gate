"""证据分层与 L1 契约桩单元测试（无 Docker / 无 :8001）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.eval.evidence_tier import (
    CLAIM_MATRIX,
    enforce_pack_tier_rules,
    tier_from_rag_health,
)
from app.tools.rag_contract import CONTRACT_VERSION


def test_claim_matrix_has_three_tiers():
    assert set(CLAIM_MATRIX) >= {"L0", "L1", "L2", "artifacts"}
    assert "live_verified" in CLAIM_MATRIX["L1"]["forbidden_claim"]


def test_tier_from_stub_health():
    assert (
        tier_from_rag_health(
            {
                "mode": "contract_stub",
                "evidence_tier": "L1",
                "consumer_contract_version_supported": CONTRACT_VERSION,
            }
        )
        == "L1"
    )


def test_tier_from_real_rag_health():
    assert (
        tier_from_rag_health(
            {"consumer_contract_version_supported": CONTRACT_VERSION, "mode": "live"}
        )
        == "L2"
    )


def test_from_artifacts_never_l2():
    pack = {
        "mode": "from_artifacts",
        "evidence_tier": "L2",
        "live_verified": True,
        "portfolio_claimable": True,
    }
    out = enforce_pack_tier_rules(pack)
    assert out["evidence_tier"] == "artifacts"
    assert out["live_verified"] is False
    assert out["portfolio_claimable"] is False


def test_l1_pack_cannot_live_verified():
    pack = {
        "mode": "live",
        "evidence_tier": "L1",
        "live_verified": True,
        "l1_verified": True,
    }
    out = enforce_pack_tier_rules(pack)
    assert out["live_verified"] is False
    assert out["l1_verified"] is True
    assert out["portfolio_claimable"] is True


def test_rag_contract_stub_endpoints():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "rag_contract_stub.py"
    spec = importlib.util.spec_from_file_location("rag_contract_stub", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    client = TestClient(mod.create_app())
    h = client.get("/health")
    assert h.status_code == 200
    body = h.json()
    assert body["evidence_tier"] == "L1"
    assert body["mode"] == "contract_stub"
    assert body["consumer_contract_version_supported"] == CONTRACT_VERSION
    assert body["submit_require_copilot_token"] is True

    ask = client.post(
        "/knowledge-bases/demo-kb/ask",
        json={"question": "H103", "history": [], "filters": {}, "parameters": {}},
    )
    assert ask.status_code == 200
    assert isinstance(ask.json().get("answer"), str)
    assert ask.json().get("grounded") is True

    draft = client.post(
        "/work-orders/draft",
        json={"question": "星沙 H103", "knowledge_base": "demo-kb"},
    )
    assert draft.status_code == 200
    assert draft.json()["draft"]["fault_codes"] == ["H103"]

    # 业务无 token → 403
    red = client.post(
        "/work-orders/submit",
        json={
            "draft": draft.json()["draft"],
            "source": "copilot_hitl",
            "submitted_by": "copilot",
        },
    )
    assert red.status_code == 403

    # 探针无 token → 200
    probe = client.post(
        "/work-orders/submit",
        json={
            "draft": draft.json()["draft"],
            "source": "contract_probe",
            "submitted_by": "contract_probe",
            "decision_certificate_phase": "probe",
        },
    )
    assert probe.status_code == 200
    tid = probe.json()["ticket_id"]
    assert probe.json()["source"] == "contract_probe"

    detail = client.get(f"/work-orders/inbox/{tid}")
    assert detail.status_code == 200
    assert detail.json()["source"] == "contract_probe"

    biz = client.get("/work-orders/inbox", params={"lane": "business"})
    assert tid not in {i["ticket_id"] for i in biz.json()["items"]}

    # 业务带 token → 进 business
    ok = client.post(
        "/work-orders/submit",
        headers={"X-Copilot-Submit-Token": "demo-copilot-submit-shared"},
        json={
            "draft": draft.json()["draft"],
            "source": "copilot_hitl",
            "submitted_by": "copilot",
            "run_id": "unit-run",
            "decision_certificate_phase": "resolved",
        },
    )
    assert ok.status_code == 200
    bid = ok.json()["ticket_id"]
    biz2 = client.get("/work-orders/inbox", params={"lane": "business"})
    assert bid in {i["ticket_id"] for i in biz2.json()["items"]}
