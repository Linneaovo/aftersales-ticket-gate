"""持久化 repair / TTL / orphan 计数。"""

from __future__ import annotations

import time

import pytest

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.graph.state import merge_state
from app.tracing.store import (
    audit_persistence,
    expire_stale_hitl_waits,
    init_db,
    repair_persistence,
    reset_all_persistence,
    save_run_snapshot,
)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    runs = tmp_path / "runs.db"
    cp = tmp_path / "cp.db"
    monkeypatch.setenv("RUNS_DB_PATH", str(runs))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(cp))
    monkeypatch.setenv("TRACES_DIR", str(tmp_path / "traces"))
    get_settings.cache_clear()
    reset_graph_cache()
    reset_all_persistence()
    yield tmp_path
    get_settings.cache_clear()
    reset_graph_cache()


def _insert_orphan_checkpoint(thread_id: str) -> None:
    import sqlite3
    from pathlib import Path

    from app.config import get_settings

    path = Path(get_settings().checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
              thread_id TEXT NOT NULL,
              checkpoint_ns TEXT NOT NULL DEFAULT '',
              checkpoint_id TEXT NOT NULL,
              parent_checkpoint_id TEXT,
              type TEXT,
              checkpoint BLOB,
              metadata BLOB,
              PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO checkpoints
            (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
            VALUES (?, '', 'test-cp', NULL, 'test', ?, ?)
            """,
            (thread_id, b"{}", b"{}"),
        )
        conn.commit()
    finally:
        conn.close()


def test_audit_persistence_orphan_counts(isolated_db):
    init_db()
    state = merge_state(
        {"run_id": "r-orphan", "status": "succeeded", "api_key": "demo-key", "role": "technician"},
        run_id="r-orphan",
    )
    save_run_snapshot(state)  # type: ignore[arg-type]
    _insert_orphan_checkpoint("orphan-cp-only")
    report = audit_persistence()
    assert report["orphan_count"] >= 1
    assert "orphan-cp-only" in report["orphan_checkpoints"]


def test_repair_clears_orphan_checkpoint(isolated_db):
    _insert_orphan_checkpoint("orphan-only")
    before = audit_persistence()
    assert before["orphan_count"] >= 1
    out = repair_persistence()
    assert out.get("repaired") is True
    after = audit_persistence()
    assert after["orphan_count"] == 0


def test_expire_stale_hitl_waits(isolated_db, monkeypatch):
    monkeypatch.setenv("HITL_WAIT_TTL_HOURS", "0.001")  # ~3.6s
    get_settings.cache_clear()
    init_db()
    state = merge_state(
        {"run_id": "r-stale", "status": "waiting_hitl", "api_key": "demo-key", "role": "technician"},
        run_id="r-stale",
    )
    save_run_snapshot(state)  # type: ignore[arg-type]
    # 回写旧 updated_at
    import sqlite3

    from app.tracing.store import _db_path

    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            "UPDATE runs SET updated_at=? WHERE run_id=?",
            (time.time() - 7200, "r-stale"),
        )
        conn.commit()
    report = expire_stale_hitl_waits()
    assert "r-stale" in report.get("expired", [])
    from app.tracing.store import load_run

    loaded = load_run("r-stale")
    assert loaded is not None
    assert loaded.get("status") == "failed"


def test_waiting_hitl_without_checkpoint_marked_failed(isolated_db):
    init_db()
    state = merge_state(
        {"run_id": "r-nocp", "status": "waiting_hitl", "api_key": "demo-key", "role": "technician"},
        run_id="r-nocp",
    )
    save_run_snapshot(state)  # type: ignore[arg-type]
    out = repair_persistence()
    assert any("mark_hitl_unrecoverable:r-nocp" in a for a in out.get("actions") or [])


def test_terminal_with_cp_degraded_then_unhealthy(isolated_db, monkeypatch):
    """终态残留 CP：未达阈值 → degraded；达阈值 → healthy=false。"""
    monkeypatch.setenv("TERMINAL_CHECKPOINT_THRESHOLD", "2")
    get_settings.cache_clear()
    init_db()

    state = merge_state(
        {"run_id": "t1", "status": "succeeded", "api_key": "demo-key", "role": "technician"},
        run_id="t1",
    )
    save_run_snapshot(state)  # type: ignore[arg-type]
    _insert_orphan_checkpoint("t1")

    mid = audit_persistence()
    assert mid["terminal_with_cp_count"] == 1
    assert mid.get("degraded") is True
    assert mid.get("healthy") is True

    state2 = merge_state(
        {"run_id": "t2", "status": "failed", "api_key": "demo-key", "role": "technician"},
        run_id="t2",
    )
    save_run_snapshot(state2)  # type: ignore[arg-type]
    _insert_orphan_checkpoint("t2")

    over = audit_persistence()
    assert over["terminal_with_cp_count"] >= 2
    assert over.get("healthy") is False
    assert over.get("degraded") is False
