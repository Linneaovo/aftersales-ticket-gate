"""门禁 / 质检策略 ID 目录（Policy-as-Code）。"""

from __future__ import annotations

import re

# 冲突策略写死：仅并列展示、不作自动裁决（已删除可切换死配置）
CONFLICT_POLICY = "no_arbitration"

# 变更 POL 语义或触发条件时 bump；写入 Decision Certificate / trace
POLICY_CATALOG_VERSION = "2026-08-28.opt2"

# 主推策略（对外主路径）；其余为扩展能力
CORE_POLICIES: tuple[str, ...] = (
    "POL-ROLE-01",
    "POL-CONFLICT-01",
    "POL-PARTS-01",
    "POL-SLA-01",
    "POL-DEGRADE-01",
)

# 改 CORE 策略文案时：先 bump POLICY_CATALOG_VERSION，再更新本锁的 version + core_fingerprint
# fingerprint = sha256("\\n".join(f"{id}={text}" for id in CORE_POLICIES))[:16]
POLICY_CATALOG_LOCK: dict[str, str] = {
    "version": "2026-08-28.opt2",
    "core_fingerprint": "dfd7c1966aac95a0",
}
# 兼容旧名（勿在新代码引用）
# 兼容旧导出名
PRIMARY_CORE_POLICIES = CORE_POLICIES
INTERVIEW_CORE_POLICIES = CORE_POLICIES  # deprecated alias

POLICIES: dict[str, str] = {
    "POL-CONFLICT-01": "制度/质保冲突须并列展示且站长人确，不作自动裁决",
    "POL-CONFLICT-02": "冲突场景禁止单方裁决措辞",
    "POL-SLA-01": "二次进站须站长人确后方可提交",
    "POL-SLA-02": "紧急/首响窗口须站长确认响应安排",
    "POL-PARTS-01": "配件缺料须人确调拨或改约",
    "POL-PARTS-02": "配件台账降级、未知件号或机型不匹配须单独确认，禁止按缺料静默调拨",
    "POL-ROLE-01": "非站长不可直接 submit，须站长人确批准",
    "POL-ROLE-02": "当前角色不可创建工单草稿",
    "POL-ACL-01": "越权主题（合同/薪酬）调度层拒绝",
    "POL-CHAT-01": "闲聊/注入拒绝，不检索不开单",
    "POL-GROUND-01": "依据不足或无引用；冲突题软化为 force_hitl，其余 hard reject",
    "POL-GROUND-02": "检索侧 ACL/注入/闲聊拦截",
    "POL-DRAFT-01": "纯查询意图不应生成工单",
    "POL-DRAFT-02": "故障开单缺故障码字段",
    "POL-DEGRADE-01": "RAG 降级时强制人确并禁止自动提交",
    "POL-HITL-EDIT": "站长退回补件（须备注；不改草稿字段，须重新开单后提交）",
    "POL-HITL-REJECT": "人确已拒绝",
    "POL-HITL-WAIT": "等待站长人确",
    "POL-STATION-01": "故障开单未识别服务站，须站长确认或补全站名",
    "POL-WEATHER-01": "雨季/户外作业风险须站长确认防护备注",
    "POL-INTENT-01": "报修开单意图置信度偏低，须站长确认或补全话术",
}

_POLICY_ID_RE = re.compile(r"POL-[A-Z0-9-]+")

POLICY_TRIGGERS: dict[str, str] = {
    "POL-CONFLICT-01": "RAG 返回 conflicts 或 conflict_review 意图",
    "POL-CONFLICT-02": "冲突场景 answer 含单方裁决措辞（force_hitl，不作硬拒）",
    "POL-SLA-01": "service_ticket.second_visit=true",
    "POL-SLA-02": "报修语境下含紧急/首响关键词",
    "POL-PARTS-01": "parts_check.shortage=true",
    "POL-PARTS-02": "parts_check.ledger_degraded / unknown_parts / model_mismatch",
    "POL-ROLE-01": "非 station_chief 不可 submit（仅提交门禁，不单独 force HITL）",
    "POL-ROLE-02": "finance/hr 等角色不可 draft",
    "POL-ACL-01": "acl_probe 意图，调度层拒绝",
    "POL-CHAT-01": "chitchat/injection 意图",
    "POL-GROUND-01": "grounded=false 或无 sources；冲突题改为 force_hitl",
    "POL-GROUND-02": "RAG blocked（ACL/注入/闲聊硬拒；冲突题 ungrounded 走 GROUND-01 软化）",
    "POL-DRAFT-01": "knowledge_only 却出现 draft",
    "POL-DRAFT-02": "fault_dispatch 缺 fault_codes",
    "POL-DEGRADE-01": "RAG retrieve_only / ollama 不可用",
    "POL-HITL-EDIT": "人确 decision=return|edit（退回补件终止，不改 draft）",
    "POL-HITL-REJECT": "人确 decision=reject",
    "POL-HITL-WAIT": "hitl.required 且未 resolved",
    "POL-STATION-01": "fault_dispatch 且 service_ticket.station 为空",
    "POL-WEATHER-01": "service_ticket.outdoor_weather_risk=true（雨季/户外关键词）",
    "POL-INTENT-01": "intent=fault_dispatch 且 intent_confidence < 阈值",
}


def list_policies() -> list[dict[str, str]]:
    return [
        {
            "id": pid,
            "label": label,
            "trigger": POLICY_TRIGGERS.get(pid, ""),
            "core": pid in CORE_POLICIES,
            "interview_core": pid in CORE_POLICIES,  # 兼容旧字段名
        }
        for pid, label in POLICIES.items()
    ]


def extract_policy_ids(text: str) -> list[str]:
    seen: list[str] = []
    for m in _POLICY_ID_RE.finditer(text or ""):
        pid = m.group(0)
        if pid not in seen:
            seen.append(pid)
    return seen


def tag(policy_id: str, detail: str = "") -> str:
    label = POLICIES.get(policy_id, policy_id)
    if detail:
        return f"[{policy_id}] {label}: {detail}"
    return f"[{policy_id}] {label}"


def core_policies_fingerprint() -> str:
    """CORE 策略文案指纹；与 POLICY_CATALOG_LOCK 对照，防改语义未 bump。"""
    import hashlib

    blob = "\n".join(f"{pid}={POLICIES[pid]}" for pid in CORE_POLICIES)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
