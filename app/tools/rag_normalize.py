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
    """统一 conflicts / grounding / sources 结构供质检与 conflict_bundle 消费。

    O3：禁止用 sources 推断 grounded=True（会改变门禁语义）。
    缺 grounded → False + contract_gate_incomplete，由 detect_rag_degraded 强制 HITL。
    """
    out = dict(result or {})
    out["conflicts"] = normalize_conflicts(out.get("conflicts"))
    try:
        out["grounding_score"] = float(out.get("grounding_score") or 0.0)
    except (TypeError, ValueError):
        out["grounding_score"] = 0.0

    incomplete = bool(out.get("contract_gate_incomplete"))
    if out.get("_contract_errors"):
        incomplete = True
    if "grounded" not in out or out.get("grounded") is None:
        out["grounded"] = False
        incomplete = True
    elif not isinstance(out.get("grounded"), bool):
        out["grounded"] = False
        incomplete = True

    sources = out.get("sources")
    if sources is None:
        out["sources"] = []
        incomplete = True
    elif not isinstance(sources, list):
        out["sources"] = [{"chunk": {"source": str(sources), "text": ""}, "score": 0.0}]

    out["contract_gate_incomplete"] = incomplete
    return out
