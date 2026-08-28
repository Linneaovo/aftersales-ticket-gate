"""离线 RAG 客户端唯一实现；DemoRag / EvalRag / 测试 Stub 均复用此模块。"""

from __future__ import annotations

from typing import Any

from app.tools.rag_client import RagToolError

_CONFLICT_MARKERS = ("质保", "哪个为准", "新旧", "不一致")


def build_stub_ask_payload(question: str = "") -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    if question and any(x in question for x in _CONFLICT_MARKERS):
        conflicts = [
            {"doc_a": "质保制度2023旧版.txt", "doc_b": "质保制度修订稿.txt", "metric": "质保月数"}
        ]
    return {
        "answer": "两版制度数字不一致，并列展示，不作裁决。"
        if conflicts
        else "H103 与液压压力相关，建议检查主控阀。",
        "sources": [{"chunk": {"source": "故障码对照表.txt", "text": "H103 液压"}, "score": 0.9}],
        "grounded": True,
        "grounding_score": 0.82 if not conflicts else 0.85,
        "blocked": False,
        "block_reason": None,
        "conflicts": conflicts,
        "request_id": "stub-offline",
    }


def build_stub_draft(parts: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "draft": {
            "ticket_type": "fault",
            "machine_model": "SY215C",
            "fault_codes": ["H103"],
            "recommended_parts": list(parts or ["液压泵总成"]),
            "fill_fields": [{"field": "fault_codes", "value": "H103", "source": "from_retrieval"}],
        },
    }


class RagStubClient:
    """enterprise-rag 离线替身；行为一致，避免 Demo/Eval/Test 三份漂移。"""

    offline = True

    def __init__(
        self,
        ask_payload: dict[str, Any] | None = None,
        *,
        fail: bool = False,
        fail_on: str | None = None,
        parts: list[str] | None = None,
        ticket_id: str = "T-STUB-OFFLINE",
        request_id: str = "stub-offline",
    ) -> None:
        self._explicit_ask = ask_payload is not None
        base = dict(ask_payload or build_stub_ask_payload())
        base.setdefault("request_id", request_id)
        self.ask_payload = base
        self.fail = fail
        self.fail_on = fail_on  # "ask" | "retrieve" | "draft" | "submit"
        self.parts = parts or ["液压泵总成"]
        self.ticket_id = ticket_id
        self.draft_calls = 0
        self.submit_calls = 0

    def _maybe_fail(self, op: str) -> None:
        if self.fail or self.fail_on == op:
            raise RagToolError(f"stub rag fail on {op}", 500)

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "mode": "stub_offline"}

    def ask(self, question: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail("ask")
        # 显式 ask_payload 优先生效，便于单测注入 Live 差异（如 ungrounded）
        if self._explicit_ask:
            return dict(self.ask_payload)
        q = question or str(kwargs.get("question") or "")
        if q and any(x in q for x in _CONFLICT_MARKERS):
            return build_stub_ask_payload(q)
        return dict(self.ask_payload)

    def retrieve(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail("retrieve")
        return {"sources": self.ask_payload.get("sources") or [], "results": self.ask_payload.get("sources") or []}

    def draft_work_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail("draft")
        self.draft_calls += 1
        return build_stub_draft(self.parts)

    def submit_work_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail("submit")
        self.submit_calls += 1
        return {"ok": True, "ticket_id": self.ticket_id}

    def submit_feedback(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "id": f"fb-{self.ticket_id}"}

    def list_inbox(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"items": [], "count": 0}

    def get_ticket(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "ticket_id": self.ticket_id}

    def metrics(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"mode": "stub_offline"}
