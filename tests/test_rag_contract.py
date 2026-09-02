"""RAG 响应契约：normalize + FakeRag stub 与文档 schema 对齐。"""

from __future__ import annotations

import pytest

from app.tools.rag_contract import (
    assert_contract,
    validate_ask_response,
    validate_draft_response,
    validate_inbox_response,
    validate_submit_response,
)
from app.tools.rag_normalize import normalize_rag_result
from app.tools.rag_stub_base import RagStubClient, build_stub_ask_payload, build_stub_draft


def test_normalize_ask_minimal_schema():
    raw = {
        "answer": "H103 液压",
        "sources": [{"chunk": {"source": "故障码对照表.txt", "text": "H103"}, "score": 0.9}],
        "grounding_score": "0.82",
        "conflicts": {"unexpected": 1},
    }
    out = normalize_rag_result(raw)
    assert isinstance(out["answer"], str)
    assert isinstance(out["sources"], list)
    assert isinstance(out["conflicts"], list)
    assert out["grounding_score"] == 0.82
    # O3：禁止用 sources 推断 grounded=True
    assert out["grounded"] is False
    assert out["contract_gate_incomplete"] is True
    assert validate_ask_response(out) == []  # grounded 已是 bool False


def test_normalize_empty_sources():
    out = normalize_rag_result({"answer": "x", "grounded": False, "grounding_score": 0.1})
    assert out["sources"] == []
    assert out["grounded"] is False
    assert out["contract_gate_incomplete"] is True  # sources was missing
    assert validate_ask_response(out) == []


def test_normalize_does_not_infer_grounded_true():
    out = normalize_rag_result(
        {
            "answer": "ok",
            "sources": [{"chunk": {"source": "a", "text": "b"}, "score": 0.9}],
            "grounding_score": 0.9,
        }
    )
    assert out["grounded"] is False
    assert out["contract_gate_incomplete"] is True


def test_ask_contract_rejects_missing_sources():
    errors = validate_ask_response({"answer": "ok", "grounded": True})
    assert any("sources" in e for e in errors)


def test_ask_contract_rejects_missing_grounded():
    errors = validate_ask_response({"answer": "ok", "sources": []})
    assert any("grounded" in e for e in errors)


def test_ask_contract_blocked_needs_reason():
    errors = validate_ask_response(
        {"answer": "", "sources": [], "blocked": True, "block_reason": None}
    )
    assert any("block_reason" in e for e in errors)


def test_stub_ask_draft_submit_inbox_pass_contract():
    client = RagStubClient()
    ask = normalize_rag_result(client.ask("SY215C H103 报修开单"))
    assert_contract("ask", ask)
    assert_contract("draft", client.draft_work_order())
    assert_contract("submit", client.submit_work_order({}))
    assert_contract("inbox", client.list_inbox())


def test_stub_conflict_ask_passes_contract():
    ask = normalize_rag_result(build_stub_ask_payload("质保多久哪个为准"))
    assert ask["conflicts"]
    assert_contract("ask", ask)


def test_draft_contract_rejects_empty():
    assert validate_draft_response({"ok": True}) != []
    assert validate_draft_response(build_stub_draft()) == []


def test_submit_and_inbox_contract_edge():
    assert validate_submit_response({}) != []
    assert validate_submit_response({"ok": True}) == []
    assert validate_inbox_response({"count": 0}) != []
    assert validate_inbox_response({"items": []}) == []


def test_assert_contract_raises():
    with pytest.raises(AssertionError, match="ask"):
        assert_contract("ask", {"answer": 1})


def test_contract_version_fingerprint():
    from app.tools.rag_contract import CONTRACT_VERSION

    assert CONTRACT_VERSION.startswith("2026-")
    assert "." in CONTRACT_VERSION


def test_rag_client_ask_marks_incomplete_without_grounded(monkeypatch):
    from app.config import Settings
    from app.tools.rag_client import RagClient

    client = RagClient(Settings(contract_validate="strict", rag_base_url="http://127.0.0.1:9"))

    def fake_request(*_a, **_k):
        return {"answer": "H103", "sources": []}

    monkeypatch.setattr(client, "_request", fake_request)
    out = client.ask("H103")
    assert out.get("contract_gate_incomplete") is True
    assert out.get("_contract_errors")
