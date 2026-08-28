"""RAG 最小响应契约（文档级 schema 校验）。"""

from __future__ import annotations

from app.tools.rag_normalize import normalize_rag_result


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
    assert out["grounded"] is True


def test_normalize_empty_sources():
    out = normalize_rag_result({"answer": "x", "grounded": False, "grounding_score": 0.1})
    assert out["sources"] == []
    assert out["grounded"] is False
