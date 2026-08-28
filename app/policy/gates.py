from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.policy.rules_catalog import tag

_DEFAULT_KEY_ROLE_MAP: dict[str, str] = {
    "demo-key": "technician",
    "demo-general": "technician",
    "demo-technician": "technician",
    "demo-parts": "parts_clerk",
    "demo-chief": "station_chief",
    "demo-finance": "finance",
    "demo-hr": "finance",
}

_DEFAULT_CHIEF_KEYS = frozenset({"demo-chief"})

_DEFAULT_ROLE_DEFAULT_KEYS: dict[str, str] = {
    "technician": "demo-technician",
    "parts_clerk": "demo-parts",
    "station_chief": "demo-chief",
    "finance": "demo-finance",
    "general": "demo-key",
}


@lru_cache
def _load_demo_keys_config() -> dict[str, Any]:
    from app.config import get_settings

    path = Path(get_settings().demo_keys_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _key_role_map() -> dict[str, str]:
    cfg = _load_demo_keys_config()
    raw = cfg.get("key_role_map")
    if isinstance(raw, dict) and raw:
        return {str(k): str(v) for k, v in raw.items()}
    return dict(_DEFAULT_KEY_ROLE_MAP)


def _chief_keys() -> frozenset[str]:
    cfg = _load_demo_keys_config()
    raw = cfg.get("chief_keys")
    if isinstance(raw, list) and raw:
        return frozenset(str(k) for k in raw)
    return _DEFAULT_CHIEF_KEYS


def _role_default_keys() -> dict[str, str]:
    cfg = _load_demo_keys_config()
    raw = cfg.get("role_default_keys")
    if isinstance(raw, dict) and raw:
        return {str(k): str(v) for k, v in raw.items()}
    return dict(_DEFAULT_ROLE_DEFAULT_KEYS)


# 模块级别名（测试/导入兼容）
KEY_ROLE_MAP = _key_role_map()
CHIEF_KEYS = _chief_keys()
ROLE_DEFAULT_KEYS = _role_default_keys()


_ROLE_CLAIM_ALLOWED = frozenset({"technician", "parts_clerk", "station_chief", "finance", "general"})


def resolve_role(api_key: str | None, role_claim: str | None = None) -> str:
    """解析业务角色：默认 Key 映射；TRUST_ROLE_CLAIM=1 时信任 IdP 注入的 claim。"""
    from app.config import get_settings

    key_role = role_from_api_key(api_key)
    claim = (role_claim or "").strip().lower()
    if not claim:
        return key_role
    if claim not in _ROLE_CLAIM_ALLOWED:
        raise ValueError(f"非法角色声明: {claim}")
    if get_settings().trust_role_claim:
        return claim
    if claim != key_role:
        raise ValueError(f"角色声明与 API Key 不匹配: claim={claim}, key_role={key_role}")
    return key_role


def role_from_api_key(api_key: str | None) -> str:
    if not api_key:
        return "technician"
    return _key_role_map().get(api_key.strip(), "technician")


def is_known_api_key(api_key: str | None) -> bool:
    if not api_key:
        return False
    return api_key.strip() in _key_role_map()


def assert_known_api_key(api_key: str | None) -> str:
    """校验 Key 在演示白名单内；返回 strip 后的 key。"""
    from app.config import get_settings

    key = (api_key or "").strip()
    if get_settings().require_known_api_key and not is_known_api_key(key):
        raise ValueError(f"未知 API Key: {key or '(empty)'}")
    return key or "demo-key"


def is_station_chief(api_key: str | None = None, role: str | None = None) -> bool:
    if role == "station_chief":
        return True
    if api_key and api_key.strip() in _chief_keys():
        return True
    return role_from_api_key(api_key) == "station_chief"


def can_submit(role: str) -> bool:
    return role in {"station_chief"}


def can_create_draft(role: str) -> bool:
    return role in {"technician", "parts_clerk", "station_chief", "general"}


def can_see_full_conflict(role: str) -> bool:
    return role in {"technician", "station_chief", "general", "finance"}


def evaluate_submit_eligible(state: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    role = state.get("role") or "technician"
    hitl = state.get("hitl") or {}
    critic = state.get("critic_report") or {}
    conflict = state.get("conflict_bundle") or {}
    parts = state.get("parts_check") or {}
    draft = state.get("work_order_draft") or {}
    ticket = state.get("service_ticket") or {}
    sla = state.get("sla_flags") or {}
    approved = bool(hitl.get("resolved") and hitl.get("decision") == "approve")

    if not draft:
        blockers.append("尚无工单草稿")
    if critic and not critic.get("passed", True):
        blockers.append("质检未通过: " + "; ".join(critic.get("reasons") or []))
    if conflict.get("present") and not approved:
        blockers.append(tag("POL-CONFLICT-01"))
    if parts.get("shortage") and not approved:
        blockers.append(tag("POL-PARTS-01", str(parts.get("note") or "")))
    if critic.get("force_hitl") and not approved:
        blockers.append(tag("POL-HITL-WAIT", "质检要求人确"))
    if state.get("rag_degraded") and not approved:
        blockers.append(tag("POL-DEGRADE-01"))
    if ticket.get("second_visit") and not approved:
        blockers.append(tag("POL-SLA-01"))
    if ticket.get("urgent") and not approved:
        blockers.append(tag("POL-SLA-02"))
    if hitl.get("required") and not hitl.get("resolved"):
        blockers.append(tag("POL-HITL-WAIT"))
    if hitl.get("resolved") and hitl.get("decision") == "reject":
        blockers.append(tag("POL-HITL-REJECT", str(hitl.get("note") or "")))
    if hitl.get("resolved") and hitl.get("decision") == "edit":
        blockers.append(tag("POL-HITL-EDIT", str(hitl.get("note") or "需改单说明")))
    if not (ticket.get("station") or "").strip():
        blockers.append(tag("POL-STATION-01"))
    if not can_submit(role) and not approved:
        blockers.append(tag("POL-ROLE-01", f"role={role}"))

    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for b in blockers:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return (len(uniq) == 0, uniq)


def filter_conflict_for_role(conflict: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    if not conflict:
        return conflict
    if can_see_full_conflict(role):
        return conflict
    return {
        "present": bool(conflict.get("present")),
        "policy": conflict.get("policy") or "no_arbitration",
        "reason": "配件岗仅见冲突摘要，明细需站长/技师查看",
        "items": [],
        "sources_pair": [],
        "requires_chief": True,
        "redacted": True,
    }
