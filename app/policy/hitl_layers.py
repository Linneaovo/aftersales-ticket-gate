"""分层人确：冲突 / 缺料 / SLA / 降级 / 站点 / 雨季 不可被单一 approve 一键放行。"""

from __future__ import annotations

from typing import Any

# 与 gates / UI / API 共用的层名（稳定契约）
LAYER_CONFLICT = "conflict"
LAYER_SHORTAGE = "shortage"
LAYER_SLA = "sla"
LAYER_DEGRADE = "degrade"
LAYER_STATION = "station"
LAYER_LEDGER = "ledger"  # 台账 HTTP 降级或未知件号
LAYER_WEATHER = "weather"  # 雨季/户外作业防护
LAYER_INTENT = "intent"  # 意图低置信

LAYER_LABELS: dict[str, str] = {
    LAYER_CONFLICT: "制度/质保冲突并列确认（不作裁决）",
    LAYER_SHORTAGE: "缺料调拨或改约确认",
    LAYER_SLA: "二次进站/紧急首响确认",
    LAYER_DEGRADE: "RAG 降级风险确认",
    LAYER_STATION: "服务站归属确认",
    LAYER_LEDGER: "配件台账降级/未知件/机型不匹配确认",
    LAYER_WEATHER: "雨季/户外作业防护确认",
    LAYER_INTENT: "报修开单意图低置信确认",
}


def compute_pending_layers(state: dict[str, Any]) -> list[str]:
    """根据当前 run 状态计算须单独勾选的人确层（有序去重）。"""
    pending: list[str] = []
    conflict = state.get("conflict_bundle") or {}
    parts = state.get("parts_check") or {}
    ticket = state.get("service_ticket") or {}
    critic = state.get("critic_report") or {}
    intent = state.get("intent")

    if conflict.get("present") or intent == "conflict_review" or conflict.get("requires_chief"):
        pending.append(LAYER_CONFLICT)
    if parts.get("shortage"):
        pending.append(LAYER_SHORTAGE)
    if parts.get("ledger_degraded") or parts.get("unknown_parts") or parts.get("model_mismatch"):
        pending.append(LAYER_LEDGER)
    if ticket.get("second_visit") or ticket.get("urgent"):
        pending.append(LAYER_SLA)
    if state.get("rag_degraded"):
        pending.append(LAYER_DEGRADE)
    if intent == "fault_dispatch" and not (ticket.get("station") or "").strip():
        pending.append(LAYER_STATION)
    if ticket.get("outdoor_weather_risk"):
        from app.config import get_settings

        if get_settings().enable_weather_pol:
            pending.append(LAYER_WEATHER)
    conf = state.get("intent_confidence")
    from app.domain.intent_rules import resolve_intent_confidence_threshold

    intent_thr = resolve_intent_confidence_threshold()
    if (
        intent == "fault_dispatch"
        and conf is not None
        and float(conf) < intent_thr
    ):
        pending.append(LAYER_INTENT)

    # 质检 force_hitl 常与 conflict/degrade 同发；若仅 force_hitl 则归入 degrade 层
    if critic.get("force_hitl") and not pending:
        pending.append(LAYER_DEGRADE)

    seen: set[str] = set()
    out: list[str] = []
    for layer in pending:
        if layer not in seen:
            seen.add(layer)
            out.append(layer)
    return out


def normalize_confirmations(raw: dict[str, Any] | None) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def missing_layer_confirmations(
    pending: list[str],
    confirmations: dict[str, bool] | None,
) -> list[str]:
    conf = normalize_confirmations(confirmations)
    return [layer for layer in pending if not conf.get(layer)]


def confirmations_covering(pending: list[str] | None = None, *, state: dict[str, Any] | None = None) -> dict[str, bool]:
    """测试/剧本：对全部 pending 层显式勾选 True（禁止隐式一键）。"""
    layers = list(pending) if pending is not None else compute_pending_layers(state or {})
    return {layer: True for layer in layers}


def layer_confirmed(hitl: dict[str, Any] | None, layer: str) -> bool:
    """approve 已决议且该层在 confirmations 中为 True。"""
    hitl = hitl or {}
    if not (hitl.get("resolved") and hitl.get("decision") == "approve"):
        return False
    conf = normalize_confirmations(hitl.get("confirmations"))
    return bool(conf.get(layer))


def any_business_layer_confirmed(hitl: dict[str, Any] | None) -> bool:
    """角色放行：须 approve；业务层各自看 layer_confirmed。"""
    hitl = hitl or {}
    return bool(hitl.get("resolved") and hitl.get("decision") == "approve")


def pending_layers_prompt(pending: list[str]) -> str:
    if not pending:
        return ""
    bits = [f"{layer}={LAYER_LABELS.get(layer, layer)}" for layer in pending]
    return " 【分层确认】须在 confirmations 勾选: " + "; ".join(bits)
