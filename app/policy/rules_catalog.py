"""门禁 / 质检策略 ID 目录（Policy-as-Code）。"""

from __future__ import annotations

POLICIES: dict[str, str] = {
    "POL-CONFLICT-01": "制度/质保冲突须并列展示且站长人确，不作自动裁决",
    "POL-CONFLICT-02": "冲突场景禁止单方裁决措辞",
    "POL-SLA-01": "二次进站须站长人确后方可提交",
    "POL-SLA-02": "紧急/首响窗口须站长确认响应安排",
    "POL-PARTS-01": "配件缺料须人确调拨或改约",
    "POL-ROLE-01": "非站长不可直接 submit，须站长人确批准",
    "POL-ROLE-02": "当前角色不可创建工单草稿",
    "POL-ACL-01": "越权主题（合同/薪酬）调度层拒绝",
    "POL-CHAT-01": "闲聊/注入拒绝，不检索不开单",
    "POL-GROUND-01": "依据不足或无引用；冲突题软化为 force_hitl，其余 hard reject",
    "POL-GROUND-02": "检索侧 ACL/注入/闲聊拦截",
    "POL-DRAFT-01": "纯查询意图不应生成工单",
    "POL-DRAFT-02": "故障开单缺故障码字段",
    "POL-DEGRADE-01": "RAG 降级时强制人确并禁止自动提交",
    "POL-HITL-EDIT": "人确选择改单，禁止提交",
    "POL-HITL-REJECT": "人确已拒绝",
    "POL-HITL-WAIT": "等待站长人确",
    "POL-STATION-01": "故障开单未识别服务站，须站长确认或补全站名",
}

POLICY_TRIGGERS: dict[str, str] = {
    "POL-CONFLICT-01": "RAG 返回 conflicts 或 conflict_review 意图",
    "POL-CONFLICT-02": "冲突场景 answer 含单方裁决措辞（force_hitl，不作硬拒）",
    "POL-SLA-01": "service_ticket.second_visit=true",
    "POL-SLA-02": "报修语境下含紧急/首响关键词",
    "POL-PARTS-01": "parts_check.shortage=true",
    "POL-ROLE-01": "非 station_chief 不可 submit（仅提交门禁，不单独 force HITL）",
    "POL-ROLE-02": "finance 等角色不可 draft",
    "POL-ACL-01": "acl_probe 意图，调度层拒绝",
    "POL-CHAT-01": "chitchat/injection 意图",
    "POL-GROUND-01": "grounded=false 或无 sources；冲突题改为 force_hitl",
    "POL-GROUND-02": "RAG blocked（仍硬拒）",
    "POL-DRAFT-01": "knowledge_only 却出现 draft",
    "POL-DRAFT-02": "fault_dispatch 缺 fault_codes",
    "POL-DEGRADE-01": "RAG retrieve_only / ollama 不可用",
    "POL-HITL-EDIT": "人确 decision=edit",
    "POL-HITL-REJECT": "人确 decision=reject",
    "POL-HITL-WAIT": "hitl.required 且未 resolved",
    "POL-STATION-01": "fault_dispatch 且 service_ticket.station 为空",
}


def list_policies() -> list[dict[str, str]]:
    return [
        {
            "id": pid,
            "label": label,
            "trigger": POLICY_TRIGGERS.get(pid, ""),
        }
        for pid, label in POLICIES.items()
    ]


def tag(policy_id: str, detail: str = "") -> str:
    label = POLICIES.get(policy_id, policy_id)
    if detail:
        return f"[{policy_id}] {label}: {detail}"
    return f"[{policy_id}] {label}"
