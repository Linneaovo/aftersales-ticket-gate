"""角色条件图：同题不同角色的预期路径（演示可视化）。"""

from __future__ import annotations

from typing import Any


ROLE_MATRIX: dict[str, dict[str, Any]] = {
    "technician": {
        "label": "技师",
        "can_draft": True,
        "can_submit_direct": False,
        "force_hitl_on_dispatch": True,
        "full_conflict": True,
        "rag_key_hint": "技师演示 Key（见 docs/ROLE_MATRIX.md）",
        "path_hint": "检索→质检→草稿→配件→站长人确→(可选提交)",
    },
    "parts_clerk": {
        "label": "配件员",
        "can_draft": True,
        "can_submit_direct": False,
        "force_hitl_on_dispatch": True,
        "full_conflict": False,
        "rag_key_hint": "配件员演示 Key（冲突明细脱敏）",
        "path_hint": "检索(配件语料倾向)→质检→草稿→缺料预核→站长人确",
    },
    "station_chief": {
        "label": "站长",
        "can_draft": True,
        "can_submit_direct": True,
        "force_hitl_on_dispatch": False,
        "full_conflict": True,
        "rag_key_hint": "站长演示 Key（人确/提交）",
        "path_hint": "检索→质检→草稿→配件；(冲突/缺料/SLA仍人确)→可提交",
    },
    "finance": {
        "label": "财务",
        "can_draft": False,
        "can_submit_direct": False,
        "force_hitl_on_dispatch": True,
        "full_conflict": True,
        "rag_key_hint": "财务演示 Key",
        "path_hint": "仅知识查阅；不可开单",
    },
    "general": {
        "label": "通用",
        "can_draft": True,
        "can_submit_direct": False,
        "force_hitl_on_dispatch": True,
        "full_conflict": True,
        "rag_key_hint": "通用演示 Key",
        "path_hint": "同技师默认路径",
    },
}


def expected_path_for_role(role: str, intent: str = "fault_dispatch") -> dict[str, Any]:
    row = dict(ROLE_MATRIX.get(role) or ROLE_MATRIX["technician"])
    row["role"] = role
    row["intent"] = intent
    if intent in {"chitchat", "injection", "acl_probe"}:
        row["path_hint"] = "调度层拒绝（不进检索/开单）"
    elif intent == "knowledge_only":
        row["path_hint"] = "检索→质检→结束（不开单）"
    elif intent == "conflict_review":
        row["path_hint"] = "检索→质检→冲突束→站长人确（不作裁决）"
    return row
