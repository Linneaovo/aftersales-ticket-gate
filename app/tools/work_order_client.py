from __future__ import annotations

from typing import Any


def extract_draft_body(payload: dict[str, Any]) -> dict[str, Any]:
    """从 /work-orders/draft 响应取出可 submit 的草稿本体。"""
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("draft")
    if isinstance(inner, dict) and (
        "ticket_type" in inner
        or "fault_codes" in inner
        or "fill_fields" in inner
        or "machine_model" in inner
    ):
        return inner
    return payload
