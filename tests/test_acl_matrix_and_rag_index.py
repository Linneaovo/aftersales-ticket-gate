"""B5 RAG baseline 索引 + B7 ACL 矩阵。"""

from __future__ import annotations

import json
from pathlib import Path

from app.eval.acl_matrix import run_acl_matrix
from app.eval.rag_baseline_index import build_rag_eval_index, resolve_rag_baseline_path


def test_rag_eval_index_reads_sibling_or_fixture(tmp_path: Path, monkeypatch):
    fixture = tmp_path / "evaluation_baseline.json"
    fixture.write_text(
        json.dumps(
            {
                "sample_count": 104,
                "knowledge_base": "demo-kb",
                "headline": {
                    "fusion_mrr": 0.838,
                    "dense_mrr": 0.874,
                    "bm25_mrr": 0.78,
                    "recall_at_k": 1.0,
                    "scheme": "A",
                },
                "full_retrieval_ablation": {"sample_count": 87, "overall": {"mrr": 0.86}},
                "generation_spotlight": {
                    "sampled_pass_rate": 1.0,
                    "sampled_checks": [
                        {"category": "acl", "role": "general", "blocked": True, "ok": True},
                        {"category": "acl", "role": "restricted", "blocked": False, "ok": True},
                    ],
                },
                "param_decision": {
                    "scheme": "A",
                    "change_default_params": False,
                    "recommended_defaults": {
                        "dense_weight": 0.7,
                        "bm25_weight": 0.3,
                        "use_reranker": False,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_BASELINE_PATH", str(fixture))
    idx = build_rag_eval_index()
    assert idx["present"] is True
    assert idx["copilot_claims_mrr"] is False
    assert idx["combined_score_forbidden"] is True
    assert idx["sample_count"] == 104
    assert idx["headline"]["fusion_mrr"] == 0.838
    assert idx["acl_spotlight"]["sampled_acl_n"] == 2
    assert idx["param_fingerprint"]["dense_weight"] == 0.7
    # 禁止综合分字段
    assert "combined_score" not in idx
    assert "portfolio_mrr" not in idx


def test_rag_eval_index_missing_is_honest(monkeypatch):
    monkeypatch.setenv("RAG_BASELINE_PATH", str(Path("/nonexistent/evaluation_baseline.json")))
    idx = build_rag_eval_index()
    assert idx["present"] is False
    assert idx["copilot_claims_mrr"] is False
    assert idx.get("skip_reason")


def test_rag_baseline_sibling_resolves_when_present():
    # 本机双仓布局下应能解析；CI 若无 sibling 则 skip 语义仍诚实
    path = resolve_rag_baseline_path()
    if path is None:
        idx = build_rag_eval_index()
        assert idx["present"] is False
        return
    idx = build_rag_eval_index()
    assert idx["present"] is True
    assert idx["sample_count"] == 104
    assert idx["copilot_claims_mrr"] is False


def test_acl_matrix_l1_l2_short_circuit():
    report = run_acl_matrix()
    assert report["schema"] == "acl_matrix/v1"
    assert report["all_ok"] is True, report
    assert report["matrix"]["l1_only"] is True
    assert report["matrix"]["l2_only"] is True
    assert report["matrix"]["dual_short_circuit"] is True
    by_id = {c["id"]: c for c in report["cases"]}
    assert by_id["l1_only"]["rag_called"] is False
    assert by_id["l2_only"]["rag_called"] is True
    assert "POL-GROUND-02" in by_id["l2_only"]["policy_ids"]
    assert by_id["dual_l1_short_circuit"]["rag_called"] is False
