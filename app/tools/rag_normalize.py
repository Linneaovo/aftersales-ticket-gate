"""归一化 enterprise-rag 响应字段，降低 live 与 Fake 规格漂移。"""

from __future__ import annotations

from typing import Any


def normalize_conflicts(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return [{"detail": str(raw)}]
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(dict(item))
        else:
            out.append({"detail": str(item)})
    return out


def normalize_rag_result(result: dict[str, Any]) -> dict[str, Any]:
    """统一 conflicts / grounding / sources 结构供质检与 conflict_bundle 消费。"""
    out = dict(result or {})
    out["conflicts"] = normalize_conflicts(out.get("conflicts"))
    try:
        out["grounding_score"] = float(out.get("grounding_score") or 0.0)
    except (TypeError, ValueError):
        out["grounding_score"] = 0.0
    if out.get("grounded") is None:
        out["grounded"] = bool(out.get("sources")) and out["grounding_score"] >= 0.35
    sources = out.get("sources")
    if sources is None:
        out["sources"] = []
    elif not isinstance(sources, list):
        out["sources"] = [{"chunk": {"source": str(sources), "text": ""}, "score": 0.0}]
    return out
