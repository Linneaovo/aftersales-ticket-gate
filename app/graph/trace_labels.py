"""Trace 节点展示名：明确 Worker/规则路由，避免「Agent 推理」误解。"""

from __future__ import annotations

TRACE_WORKERS: dict[str, str] = {
    "supervisor": "Supervisor(规则路由)",
    "rag": "RAG-HTTP",
    "quality": "规则质检",
    "quality_draft": "规则质检",
    "work_order": "开单-HTTP",
    "parts": "配件预核",
    "hitl": "站长人确",
    "submit": "提交-HTTP",
    "feedback": "反馈-HTTP",
    "engine_selected": "运行时",
}
