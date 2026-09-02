"""角色条件图：同题不同角色的预期路径（演示可视化）。

唯一提交权字段：`can_submit_direct`（与 gates.can_submit 对齐）。
已删除与其同义空转的 `force_hitl_on_dispatch`——非站长不可直提；
`auto_submit` 拦截在 nodes._evaluate_hitl_gates（POL-ROLE-01），不另开矩阵字段。
"""

from __future__ import annotations

from typing import Any


ROLE_MATRIX: dict[str, dict[str, Any]] = {
    "technician": {
        "label": "技师",
        "can_draft": True,
        "can_submit_direct": False,
        "full_conflict": True,
        "demo_lane": "primary",
    },
    "parts_clerk": {
        "label": "配件员",
        "can_draft": True,
        "can_submit_direct": False,
        "full_conflict": False,
        "demo_lane": "primary",
    },
    "station_chief": {
        "label": "站长",
        "can_draft": True,
        "can_submit_direct": True,
        "full_conflict": True,
        "demo_lane": "primary",
    },
    "finance": {
        "label": "财务（RAG ACL 扩展，非站务主线）",
        "can_draft": False,
        "can_submit_direct": False,
        "full_conflict": True,
        "demo_lane": "rag_acl_extension",
    },
    "hr": {
        "label": "人事（RAG ACL 扩展，非站务主线）",
        "can_draft": False,
        "can_submit_direct": False,
        "full_conflict": False,
        "demo_lane": "rag_acl_extension",
    },
    "general": {
        "label": "通用",
        "can_draft": True,
        "can_submit_direct": False,
        "full_conflict": True,
        "demo_lane": "primary",
    },
}


def role_can_submit_direct(role: str) -> bool:
    """是否可直提 mock 收件箱（读 ROLE_MATRIX.can_submit_direct；仅站长）。"""
    row = ROLE_MATRIX.get(role) or ROLE_MATRIX["technician"]
    return bool(row.get("can_submit_direct", False))


def role_can_draft(role: str) -> bool:
    """是否可出工单草稿（读 ROLE_MATRIX.can_draft；与 gates.can_create_draft 单源）。"""
    row = ROLE_MATRIX.get(role) or ROLE_MATRIX["technician"]
    return bool(row.get("can_draft", False))


def role_requires_hitl_before_submit(role: str) -> bool:
    """开单提交前是否须站长人确（= not can_submit_direct；无独立 force_hitl 字段）。"""
    return not role_can_submit_direct(role)


# 兼容旧名（测试曾用）；语义 = not can_submit_direct
def role_requires_dispatch_hitl(role: str) -> bool:
    return role_requires_hitl_before_submit(role)


def expected_path_for_role(role: str, intent: str = "fault_dispatch") -> dict[str, Any]:
    """角色能力快照；path_hint 仅调试展示，非可执行策略图。"""
    row = dict(ROLE_MATRIX.get(role) or ROLE_MATRIX["technician"])
    row["role"] = role
    row["intent"] = intent
    row["intent_label"] = "报修开单" if intent == "fault_dispatch" else intent
    row["requires_hitl_before_submit"] = not bool(row.get("can_submit_direct", False))
    if intent in {"chitchat", "injection", "acl_probe"}:
        row["path_hint"] = "拒绝（不检索不开单）"
    elif intent == "knowledge_only":
        row["path_hint"] = "检索→质检→结束"
    elif intent == "conflict_review":
        row["path_hint"] = "检索→冲突并列→站长确认"
    elif row.get("demo_lane") == "rag_acl_extension":
        row["path_hint"] = "RAG ACL 扩展角色（非站务主线）：仅查阅，不可 draft/submit"
    elif not row.get("can_draft"):
        row["path_hint"] = "仅查阅"
    elif row.get("can_submit_direct"):
        row["path_hint"] = "草稿→配件→分层确认后可 mock 提交"
    else:
        row["path_hint"] = "草稿→配件→站长分层人确→mock 收件箱"
    return row
