"""RAG 响应归一化单测。"""

from __future__ import annotations

from app.tools.rag_normalize import normalize_conflicts, normalize_rag_result


def test_normalize_conflicts_mixed_shapes():
    assert normalize_conflicts(None) == []
    assert normalize_conflicts("x") == [{"detail": "x"}]
    assert normalize_conflicts([{"a": 1}, "b"]) == [{"a": 1}, {"detail": "b"}]


def test_normalize_rag_result_defaults():
    out = normalize_rag_result({"answer": "ok"})
    assert out["sources"] == []
    assert out["grounding_score"] == 0.0
    assert out["grounded"] is False
