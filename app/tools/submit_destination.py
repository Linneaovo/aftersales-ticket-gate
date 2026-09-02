"""提交终点端口：默认可替换，禁止宣称 ERP。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from app.config import PROJECT_ROOT, get_settings


class SubmitDestination(Protocol):
    def submit(
        self,
        draft: dict[str, Any],
        *,
        run_id: str,
        note: str = "",
        submitted_by: str = "copilot",
        decision_certificate_phase: str = "resolved",
        source: str = "copilot_hitl",
        policy_ids: list[str] | None = None,
        hitl_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


def format_submit_error(
    exc: BaseException,
    *,
    error_code: str = "submit_failed",
    run_id: str = "",
    destination: str | None = None,
) -> dict[str, Any]:
    """稳定失败字段（A4）：供 submit_node / 调用方统一消费。"""
    return {
        "error_code": error_code,
        "error": str(exc),
        "run_id": run_id or None,
        "destination": destination,
        "is_production_ticket": False,
        "ok": False,
    }


def _boundary_fields(run_id: str, submitted: dict[str, Any], *, destination: str) -> dict[str, Any]:
    return {
        **submitted,
        "destination": submitted.get("destination") or destination,
        "is_production_ticket": False,
        "submit_boundary": destination,
        "submit_boundary_note": "报修开单门禁终点可替换；Standalone 常用 file_outbox，Live 常用 rag_mock_inbox；不含 ERP 派工/排程",
        "submitted_by": submitted.get("submitted_by") or "copilot",
        "run_id": submitted.get("run_id") or run_id,
        "decision_certificate_phase": submitted.get("decision_certificate_phase") or "resolved",
        "source": submitted.get("source") or "copilot_hitl",
        "idempotency_key": run_id,
    }


class RagMockInboxDestination:
    """默认实现：HTTP 提交到 enterprise-rag mock inbox。"""

    def __init__(self, client: Any) -> None:
        self.client = client

    def submit(
        self,
        draft: dict[str, Any],
        *,
        run_id: str,
        note: str = "",
        submitted_by: str = "copilot",
        decision_certificate_phase: str = "resolved",
        source: str = "copilot_hitl",
        policy_ids: list[str] | None = None,
        hitl_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        submitted = self.client.submit_work_order(
            draft,
            note=note or ("copilot:" + run_id),
            submitted_by=submitted_by,
            run_id=run_id or None,
            decision_certificate_phase=decision_certificate_phase,
            source=source,
        )
        if not isinstance(submitted, dict):
            submitted = {"raw": submitted}
        out = _boundary_fields(run_id, submitted, destination="rag_mock_inbox")
        # 与 file_outbox 同 envelope：治理字段始终存在，便于审计/对比
        out["policy_ids"] = list(policy_ids or [])
        out["hitl"] = dict(hitl_summary or {})
        return out


class FileOutboxDestination:
    """可选本地 outbox：证明端口可替换；仍非 ERP。"""

    def __init__(self, outbox_dir: Path | None = None) -> None:
        self.outbox_dir = outbox_dir or (PROJECT_ROOT / "data" / "outbox")

    def submit(
        self,
        draft: dict[str, Any],
        *,
        run_id: str,
        note: str = "",
        submitted_by: str = "copilot",
        decision_certificate_phase: str = "resolved",
        source: str = "copilot_hitl",
        policy_ids: list[str] | None = None,
        hitl_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        path = self.outbox_dir / f"{run_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing["idempotent_replay"] = True
            return existing
        ticket_id = f"file-{run_id}"
        payload = _boundary_fields(
            run_id,
            {
                "ticket_id": ticket_id,
                "destination": "file_outbox",
                "note": note,
                "submitted_by": submitted_by,
                "decision_certificate_phase": decision_certificate_phase,
                "source": source,
                "draft": draft,
                "policy_ids": list(policy_ids or []),
                "hitl": dict(hitl_summary or {}),
            },
            destination="file_outbox",
        )
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def list_tickets(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """演示用列表（非 ERP 查询）。按 mtime 新→旧。"""
        if not self.outbox_dir.exists():
            return []
        rows: list[tuple[float, dict[str, Any]]] = []
        for path in self.outbox_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict):
                rows.append((path.stat().st_mtime, data))
        rows.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in rows[: max(0, limit)]]

    def get_ticket(self, run_id: str) -> dict[str, Any] | None:
        path = self.outbox_dir / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None


def get_submit_destination(client: Any | None = None) -> SubmitDestination:
    settings = get_settings()
    mode = (getattr(settings, "submit_destination", None) or "file_outbox").strip().lower()
    if mode in {"file", "file_outbox"}:
        return FileOutboxDestination()
    if client is None:
        raise ValueError("rag_mock_inbox destination requires RagClient")
    return RagMockInboxDestination(client)
