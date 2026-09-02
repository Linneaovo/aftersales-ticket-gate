"""B5：从 enterprise-rag evaluation_baseline 索引摘要数字（不争 MRR）。

- 只读对端 baseline；本仓不生成「双仓综合分」
- `copilot_claims_mrr` 恒为 False
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT

SCHEMA = "rag_eval_index/v1"
_DEFAULT_REL = Path("data") / "demo" / "evaluation_baseline.json"


def resolve_rag_baseline_path() -> Path | None:
    """优先 env RAG_BASELINE_PATH，否则 sibling ../enterprise-rag/data/demo/evaluation_baseline.json。"""
    env = (os.environ.get("RAG_BASELINE_PATH") or "").strip()
    if env:
        p = Path(env)
        return p if p.is_file() else None
    sibling = PROJECT_ROOT.parent / "enterprise-rag" / _DEFAULT_REL
    if sibling.is_file():
        return sibling
    return None


def _acl_spotlight(baseline: dict[str, Any]) -> dict[str, Any]:
    spot = baseline.get("generation_spotlight") if isinstance(baseline.get("generation_spotlight"), dict) else {}
    samples = [s for s in (spot.get("sampled_checks") or []) if isinstance(s, dict)]
    acl = [s for s in samples if str(s.get("category") or "").lower() == "acl"]
    ok_n = sum(1 for s in acl if s.get("ok") is True)
    return {
        "sampled_acl_n": len(acl),
        "sampled_acl_ok_n": ok_n,
        "sampled_pass_rate": spot.get("sampled_pass_rate"),
        "note": "ACL 抽样来自 RAG generation_spotlight；非 Copilot 门禁分",
    }


def _param_fingerprint(baseline: dict[str, Any]) -> dict[str, Any]:
    pd = baseline.get("param_decision") if isinstance(baseline.get("param_decision"), dict) else {}
    rec = pd.get("recommended_defaults") if isinstance(pd.get("recommended_defaults"), dict) else {}
    return {
        "scheme": pd.get("scheme") or (baseline.get("headline") or {}).get("scheme"),
        "change_default_params": pd.get("change_default_params"),
        "dense_weight": rec.get("dense_weight"),
        "bm25_weight": rec.get("bm25_weight"),
        "use_reranker": rec.get("use_reranker"),
    }


def build_rag_eval_index(*, baseline_path: Path | None = None) -> dict[str, Any]:
    """构建 pack 用 rag_eval_index；缺文件时 present=false，仍声明不抢 MRR。"""
    path = baseline_path if baseline_path is not None else resolve_rag_baseline_path()
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": "enterprise-rag",
        "copilot_claims_mrr": False,
        "combined_score_forbidden": True,
        "note": "检索/MRR/金标归知识仓；本仓只索引摘要，governance_scorecard 只管门禁正确性",
        "present": False,
        "source_path": None,
        "refs": [
            "enterprise-rag/data/demo/evaluation_baseline.json",
            "data/eval/governance_scorecard.json",
        ],
    }
    if path is None or not path.is_file():
        base["skip_reason"] = "rag_baseline_not_found"
        return base

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        base["skip_reason"] = f"rag_baseline_unreadable:{exc}"
        return base
    if not isinstance(data, dict):
        base["skip_reason"] = "rag_baseline_not_object"
        return base

    headline = data.get("headline") if isinstance(data.get("headline"), dict) else {}
    full_ab = data.get("full_retrieval_ablation") if isinstance(data.get("full_retrieval_ablation"), dict) else {}
    try:
        rel = str(path.resolve().relative_to(PROJECT_ROOT.parent.resolve()))
    except ValueError:
        rel = str(path)

    base.update(
        {
            "present": True,
            "source_path": rel.replace("\\", "/"),
            "sample_count": data.get("sample_count"),
            "knowledge_base": data.get("knowledge_base"),
            "headline": {
                "fusion_mrr": headline.get("fusion_mrr"),
                "dense_mrr": headline.get("dense_mrr"),
                "bm25_mrr": headline.get("bm25_mrr"),
                "recall_at_k": headline.get("recall_at_k"),
                "scheme": headline.get("scheme"),
            },
            "full_retrieval_ablation": {
                "sample_count": full_ab.get("sample_count"),
                "mrr": (full_ab.get("overall") or {}).get("mrr")
                if isinstance(full_ab.get("overall"), dict)
                else None,
            },
            "acl_spotlight": _acl_spotlight(data),
            "param_fingerprint": _param_fingerprint(data),
            "skip_reason": None,
        }
    )
    return base
