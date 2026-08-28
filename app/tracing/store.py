from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.graph.builder import clear_checkpoint_thread, list_checkpoint_thread_ids
from app.graph.state import CopilotState, copy_state, merge_state
from app.policy.gates import ROLE_DEFAULT_KEYS

_lock = threading.Lock()
_REDACTED_MARKER = "__redacted__"


def fingerprint_api_key(api_key: str | None) -> str:
    key = (api_key or "").strip()
    if not key:
        return ""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def restore_api_key_from_fingerprint(fp: str | None, role: str | None = None) -> str:
    """从指纹还原演示 Key（非明文落库）。"""
    from app.policy.gates import _key_role_map

    target = (fp or "").strip()
    if target:
        for k in _key_role_map():
            if fingerprint_api_key(k) == target:
                return k
    return ROLE_DEFAULT_KEYS.get(str(role or "technician"), "demo-key")


def _traces_dir() -> Path:
    path = Path(get_settings().traces_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db_path() -> Path:
    path = Path(get_settings().runs_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db() -> None:
    with _lock:
        conn = sqlite3.connect(_db_path())
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT,
                    updated_at REAL,
                    payload TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def _sanitize_state_for_persist(state: CopilotState) -> dict[str, Any]:
    out = copy_state(state)
    if out.get("api_key"):
        if not out.get("api_key_fp"):
            out["api_key_fp"] = fingerprint_api_key(str(out.get("api_key")))
        out["api_key"] = _REDACTED_MARKER
    mode = get_settings().persist_mode
    if mode == "slim":
        out = _slim_state(out)
    return out


def _slim_state(state: dict[str, Any]) -> dict[str, Any]:
    """落库快照：保留 resume/HITL 必需字段，截断大 payload。"""
    out = copy_state(state)  # type: ignore[arg-type]
    rag = dict(out.get("rag_result") or {})
    if rag:
        answer = str(rag.get("answer") or "")
        if len(answer) > 500:
            rag["answer"] = answer[:500] + "…"
        sources = list(rag.get("sources") or [])[:5]
        rag["sources"] = sources
        out["rag_result"] = rag
    hits = list(out.get("retrieve_hits") or [])
    if len(hits) > 5:
        out["retrieve_hits"] = hits[:5]
    draft = dict(out.get("work_order_draft") or {})
    if draft:
        inner = dict(draft.get("draft") or draft)
        for key in ("notes", "description", "summary"):
            val = inner.get(key)
            if isinstance(val, str) and len(val) > 300:
                inner[key] = val[:300] + "…"
        if "draft" in draft:
            draft["draft"] = inner
        else:
            draft = inner
        out["work_order_draft"] = draft
    history = list(out.get("history") or [])
    if len(history) > 10:
        out["history"] = history[-10:]
    return out


def _restore_state_secrets(state: CopilotState) -> CopilotState:
    if state.get("api_key") != _REDACTED_MARKER:
        return state
    restored_key = restore_api_key_from_fingerprint(
        str(state.get("api_key_fp") or ""),
        str(state.get("role") or "technician"),
    )
    restored = merge_state(state, api_key=restored_key)
    return restored  # type: ignore[return-value]


def append_trace_file(state: CopilotState) -> Path:
    run_id = str(state.get("run_id") or "unknown")
    path = _traces_dir() / f"{run_id}.jsonl"
    events = state.get("trace_events") or []
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def save_run_snapshot(state: CopilotState) -> None:
    init_db()
    run_id = str(state.get("run_id") or "")
    import time

    payload = json.dumps(_sanitize_state_for_persist(state), ensure_ascii=False, default=str)
    with _lock:
        conn = sqlite3.connect(_db_path())
        try:
            conn.execute(
                """
                INSERT INTO runs(run_id, status, updated_at, payload)
                VALUES(?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                  status=excluded.status,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (run_id, state.get("status"), time.time(), payload),
            )
            conn.commit()
        finally:
            conn.close()


def load_run(run_id: str) -> CopilotState | None:
    init_db()
    with _lock:
        conn = sqlite3.connect(_db_path())
        try:
            row = conn.execute(
                "SELECT payload FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    data = json.loads(row[0])
    return _restore_state_secrets(data)  # type: ignore[return-value]


def list_recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    with _lock:
        conn = sqlite3.connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT run_id, status, updated_at FROM runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    return [
        {"run_id": r[0], "status": r[1], "updated_at": r[2]} for r in rows
    ]


def run_status_counts() -> dict[str, int]:
    """按 status 聚合 run 计数，供 /metrics 与 /health 摘要。"""
    init_db()
    with _lock:
        conn = sqlite3.connect(_db_path())
        try:
            rows = conn.execute("SELECT status, COUNT(*) FROM runs GROUP BY status").fetchall()
        finally:
            conn.close()
    return {str(r[0] or "unknown"): int(r[1]) for r in rows}


def reset_all_persistence() -> dict[str, int]:
    """清理 runs / traces / checkpoints（演示重置）。"""
    from app.graph.builder import reset_graph_cache

    settings = get_settings()
    reset_graph_cache()
    removed_traces = 0
    traces = Path(settings.traces_dir)
    if traces.exists():
        for p in traces.glob("*.jsonl"):
            p.unlink(missing_ok=True)
            removed_traces += 1
    runs_db = Path(settings.runs_db_path)
    if runs_db.exists():
        runs_db.unlink()
    cp_db = Path(settings.checkpoint_db_path)
    if cp_db.exists():
        cp_db.unlink()
    init_db()
    return {"traces_removed": removed_traces, "runs_db_cleared": 1, "checkpoints_cleared": 1}


def audit_persistence() -> dict[str, Any]:
    """检测 runs.db 与 checkpoints.db 不一致（orphan run / orphan checkpoint）。"""
    init_db()
    run_rows: list[tuple[str, str]] = []
    with _lock:
        conn = sqlite3.connect(_db_path())
        try:
            run_rows = conn.execute("SELECT run_id, status FROM runs").fetchall()
        finally:
            conn.close()

    run_ids = {r[0] for r in run_rows}
    waiting_hitl = {r[0] for r in run_rows if r[1] == "waiting_hitl"}
    cp_ids = list_checkpoint_thread_ids()

    orphan_checkpoints = sorted(cp_ids - run_ids)
    waiting_without_cp = sorted(waiting_hitl - cp_ids)
    terminal_with_cp = sorted(
        rid for rid in cp_ids if rid in run_ids and rid not in waiting_hitl
    )

    return {
        "run_count": len(run_ids),
        "checkpoint_thread_count": len(cp_ids),
        "waiting_hitl_count": len(waiting_hitl),
        "orphan_checkpoints": orphan_checkpoints,
        "waiting_hitl_without_checkpoint": waiting_without_cp,
        "terminal_runs_with_checkpoint": terminal_with_cp,
        "healthy": not (orphan_checkpoints or waiting_without_cp),
    }


def repair_persistence(*, dry_run: bool = False) -> dict[str, Any]:
    """修复持久化不一致：清理 orphan checkpoint；waiting_hitl 无 checkpoint 时标记 failed。"""
    report = audit_persistence()
    actions: list[str] = []

    for tid in report["orphan_checkpoints"]:
        actions.append(f"clear_orphan_checkpoint:{tid}")
        if not dry_run:
            clear_checkpoint_thread(tid)

    for rid in report["terminal_runs_with_checkpoint"]:
        actions.append(f"clear_stale_checkpoint:{rid}")
        if not dry_run:
            clear_checkpoint_thread(rid)

    for rid in report["waiting_hitl_without_checkpoint"]:
        actions.append(f"mark_hitl_unrecoverable:{rid}")
        if not dry_run:
            state = load_run(rid)
            if state:
                st = merge_state(
                    state,
                    status="failed",
                    engine="fallback",
                    engine_degraded=True,
                    error="HITL checkpoint 丢失，无法 resume；请重新发起 run",
                    final_summary="HITL checkpoint 丢失，无法 resume；请重新发起 run",
                )
                save_run_snapshot(st)  # type: ignore[arg-type]

    report["actions"] = actions
    report["dry_run"] = dry_run
    report["repaired"] = not dry_run and bool(actions)
    if not dry_run:
        report.update(audit_persistence())
    return report
