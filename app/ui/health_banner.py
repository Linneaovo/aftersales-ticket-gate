"""Streamlit 模式横幅：纯函数，便于单测（避免 import streamlit_app 触发页面副作用）。"""

from __future__ import annotations

from typing import Any


def mode_banner_kind(health: dict[str, Any] | None) -> str:
    """返回横幅种类：unreachable | standalone | l1 | l2 | joint。

    health 为空、带 ``_ui_unreachable``、或缺少 ``runtime_mode`` 时视为 API 不可达，
    不得回落到「联调模式」。
    """
    h = health if isinstance(health, dict) else {}
    if h.get("_ui_unreachable") or not h:
        return "unreachable"
    runtime_mode = str(h.get("runtime_mode") or "").strip()
    if not runtime_mode:
        return "unreachable"
    if runtime_mode == "standalone":
        return "standalone"
    claim = str(h.get("linkage_claim") or "").strip().lower()
    tier = str(h.get("rag_evidence_tier") or "").strip().upper()
    if claim == "l1" or tier == "L1":
        return "l1"
    if claim == "l2" or tier == "L2":
        return "l2"
    return "joint"
