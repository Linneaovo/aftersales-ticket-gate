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
    "demo-hr": "hr",
}

_DEFAULT_CHIEF_KEYS = frozenset({"demo-chief"})

_DEFAULT_ROLE_DEFAULT_KEYS: dict[str, str] = {
    "technician": "demo-technician",
    "parts_clerk": "demo-parts",
    "station_chief": "demo-chief",
    "finance": "demo-finance",
    "hr": "demo-hr",
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


def __getattr__(name: str) -> Any:
    """运行时读取 demo_keys.json，避免 import 时固化。"""
    if name == "KEY_ROLE_MAP":
        return _key_role_map()
    if name == "CHIEF_KEYS":
        return _chief_keys()
    if name == "ROLE_DEFAULT_KEYS":
        return _role_default_keys()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_ROLE_CLAIM_ALLOWED = frozenset({"technician", "parts_clerk", "station_chief", "finance", "hr", "general"})


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
    """Key→角色。未知 Key 在 require_known_api_key=True 时不应走到业务路径（API 已 401）。"""
    if not api_key:
        return "technician"
    mapped = _key_role_map().get(api_key.strip())
    if mapped:
        return mapped
    # 未知 Key：不再静默提权为技师语义上的「默认放行」；仍返回 technician 仅兼容单测直调，
    # 生产入口必须先走 assert_known_api_key。
    return "technician"


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
    """是否可直提：读 ROLE_MATRIX.can_submit_direct（仅站长）。"""
    from app.policy.role_graph import role_can_submit_direct

    return role_can_submit_direct(role)


def can_create_draft(role: str) -> bool:
    """是否可出草稿：读 ROLE_MATRIX.can_draft（与矩阵单源，禁硬编码双轨）。"""
    from app.policy.role_graph import role_can_draft

    return role_can_draft(role)


def can_see_full_conflict(role: str) -> bool:
    # hr 仅知识查阅，冲突明细脱敏（与配件岗类似）
    return role in {"technician", "station_chief", "general", "finance"}


def evaluate_submit_eligible(state: dict[str, Any]) -> tuple[bool, list[str]]:
    from app.policy.hitl_layers import (
        LAYER_CONFLICT,
        LAYER_DEGRADE,
        LAYER_LEDGER,
        LAYER_SHORTAGE,
        LAYER_SLA,
        LAYER_STATION,
        LAYER_WEATHER,
        LAYER_INTENT,
        any_business_layer_confirmed,
        layer_confirmed,
    )

    blockers: list[str] = []
    role = state.get("role") or "technician"
    hitl = state.get("hitl") or {}
    critic = state.get("critic_report") or {}
    conflict = state.get("conflict_bundle") or {}
    parts = state.get("parts_check") or {}
    draft = state.get("work_order_draft") or {}
    ticket = state.get("service_ticket") or {}
    # 角色放行 ≠ 业务层放行：approve 仅过 POL-ROLE；冲突/缺料等须对应 confirmations
    role_approved = any_business_layer_confirmed(hitl)

    if not draft:
        blockers.append("尚无工单草稿")
    if critic and not critic.get("passed", True):
        blockers.append("质检未通过: " + "; ".join(critic.get("reasons") or []))
    if conflict.get("present") and not layer_confirmed(hitl, LAYER_CONFLICT):
        blockers.append(tag("POL-CONFLICT-01", "须 confirmations.conflict=true"))
    if parts.get("shortage") and not layer_confirmed(hitl, LAYER_SHORTAGE):
        blockers.append(tag("POL-PARTS-01", str(parts.get("note") or "须 confirmations.shortage=true")))
    if (parts.get("ledger_degraded") or parts.get("unknown_parts") or parts.get("model_mismatch")) and not layer_confirmed(
        hitl, LAYER_LEDGER
    ):
        blockers.append(tag("POL-PARTS-02", str(parts.get("note") or "须 confirmations.ledger=true")))
    if critic.get("force_hitl") and not role_approved:
        blockers.append(tag("POL-HITL-WAIT", "质检要求人确"))
    if state.get("rag_degraded") and not layer_confirmed(hitl, LAYER_DEGRADE):
        blockers.append(tag("POL-DEGRADE-01", "须 confirmations.degrade=true"))
    # SLA：以 service_ticket 为准（sla_flags 仅为展示派生，不在此双读）
    if ticket.get("second_visit") and not layer_confirmed(hitl, LAYER_SLA):
        blockers.append(tag("POL-SLA-01", "须 confirmations.sla=true"))
    if ticket.get("urgent") and not layer_confirmed(hitl, LAYER_SLA):
        blockers.append(tag("POL-SLA-02", "须 confirmations.sla=true"))
    if hitl.get("required") and not hitl.get("resolved"):
        blockers.append(tag("POL-HITL-WAIT"))
    if hitl.get("resolved") and hitl.get("decision") == "reject":
        blockers.append(tag("POL-HITL-REJECT", str(hitl.get("note") or "")))
    if hitl.get("resolved") and hitl.get("decision") in {"return", "edit"}:
        blockers.append(tag("POL-HITL-EDIT", str(hitl.get("note") or "退回补件，禁止提交")))
    if not (ticket.get("station") or "").strip() and not layer_confirmed(hitl, LAYER_STATION):
        blockers.append(tag("POL-STATION-01", "须 confirmations.station=true"))
    if ticket.get("outdoor_weather_risk"):
        from app.config import get_settings

        if get_settings().enable_weather_pol and not layer_confirmed(hitl, LAYER_WEATHER):
            blockers.append(tag("POL-WEATHER-01", "须 confirmations.weather=true"))
    conf = state.get("intent_confidence")
    from app.domain.intent_rules import resolve_intent_confidence_threshold

    intent_thr = resolve_intent_confidence_threshold()
    if (
        state.get("intent") == "fault_dispatch"
        and conf is not None
        and float(conf) < intent_thr
        and not layer_confirmed(hitl, LAYER_INTENT)
    ):
        blockers.append(tag("POL-INTENT-01", "须 confirmations.intent=true"))
    # POL-ROLE-01：非站长须 approve（不要求业务层 confirmations）
    if not can_submit(str(role)) and not role_approved:
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
