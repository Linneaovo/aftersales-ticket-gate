# -*- coding: utf-8 -*-
"""Playbook 回放稳定性：同输入两次运行应对齐的门禁/证书字段。

不含 run_id / 时间戳；不引入新 replay API。
"""

from __future__ import annotations

from typing import Any


def stability_fingerprint(state: dict[str, Any]) -> dict[str, Any]:
    """从运行态提取可复现比对视图（Decision Certificate + HITL 关键字段）。"""
    cert = state.get("decision_certificate") if isinstance(state.get("decision_certificate"), dict) else {}
    hitl = state.get("hitl") if isinstance(state.get("hitl"), dict) else {}
    parts = cert.get("parts") if isinstance(cert.get("parts"), dict) else None
    return {
        "status": state.get("status"),
        "intent": state.get("intent"),
        "intent_confidence": state.get("intent_confidence"),
        "phase": cert.get("phase"),
        "policy_ids": list(cert.get("policy_ids") or []),
        "pending_layers": list(cert.get("pending_layers") or hitl.get("pending_layers") or []),
        "hitl_reasons": list(cert.get("hitl_reasons") or hitl.get("reasons") or []),
        "conflict_present": bool(cert.get("conflict_present")),
        "parts_shortage": None if parts is None else bool(parts.get("shortage")),
        "parts_unknown": None if parts is None else bool(parts.get("unknown_parts")),
        "policy_catalog_version": cert.get("policy_catalog_version"),
        "not_erp_dispatch": cert.get("not_erp_dispatch"),
        "is_production_ticket": cert.get("is_production_ticket"),
        "assurance": cert.get("assurance"),
    }
