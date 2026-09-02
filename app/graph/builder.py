"""LangGraph 主装配：Supervisor → Workers；人确节点可 interrupt 暂停。"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.graph.nodes import (
    hitl_node,
    parts_node,
    quality_node,
    rag_node,
    submit_node,
    supervisor_node,
    work_order_node,
)
from app.graph.state import CopilotState

_checkpointer = None


def get_checkpointer() -> Any:
    """SQLite 持久化 checkpoint；不可用时降级 MemorySaver（测试环境）。"""
    global _checkpointer
    if _checkpointer is None:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = Path(get_settings().checkpoint_db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            saver = SqliteSaver(conn)
            if hasattr(saver, "setup"):
                saver.setup()
            _checkpointer = saver
        except ImportError:
            from langgraph.checkpoint.memory import MemorySaver

            _checkpointer = MemorySaver()
    return _checkpointer


def reset_graph_cache() -> None:
    """测试或切换 checkpoint 路径时清缓存；关闭 SQLite 连接以便 Windows 删除 db 文件。"""
    global _checkpointer
    if _checkpointer is not None:
        conn = getattr(_checkpointer, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    _checkpointer = None
    get_compiled_graph.cache_clear()


def clear_checkpoint_thread(thread_id: str) -> None:
    import sqlite3

    path = Path(get_settings().checkpoint_db_path)
    if not path.exists():
        return
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        try:
            conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()


def checkpoint_exists(thread_id: str) -> bool:
    """检查 LangGraph checkpoint 线程是否存在（SQLite 或当前 MemorySaver）。"""
    path = Path(get_settings().checkpoint_db_path)
    if path.exists():
        conn = sqlite3.connect(str(path), check_same_thread=False)
        try:
            row = conn.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
                (thread_id,),
            ).fetchone()
            if row is not None:
                return True
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
    # MemorySaver / InMemorySaver：进程内仍可 resume（测试无 sqlite 包时）
    cp = _checkpointer
    if cp is not None:
        storage = getattr(cp, "storage", None)
        if isinstance(storage, dict) and thread_id in storage:
            return True
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            if cp.get_tuple(cfg) is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def list_checkpoint_thread_ids() -> set[str]:
    path = Path(get_settings().checkpoint_db_path)
    if not path.exists():
        return set()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
        return {str(r[0]) for r in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def route_after_supervisor(
    state: CopilotState,
) -> Literal["rag", "quality", "work_order", "parts", "human_confirm", "submit", "__end__"]:
    action = state.get("next_action") or "end"
    if action == "hitl":
        return "human_confirm"
    if action in {"rag", "quality", "work_order", "parts", "submit"}:
        return action  # type: ignore[return-value]
    return "__end__"


def build_langgraph(*, checkpointer: Any | None = None) -> Any:
    """编译 LangGraph。主运行时使用 SqliteSaver 以支持人确 resume。"""
    from langgraph.graph import END, START, StateGraph

    g: StateGraph = StateGraph(CopilotState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("rag", rag_node)
    g.add_node("quality", quality_node)
    g.add_node("work_order", work_order_node)
    g.add_node("parts", parts_node)
    g.add_node("human_confirm", hitl_node)
    g.add_node("submit", submit_node)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "rag": "rag",
            "quality": "quality",
            "work_order": "work_order",
            "parts": "parts",
            "human_confirm": "human_confirm",
            "submit": "submit",
            "__end__": END,
        },
    )
    for name in ("rag", "quality", "work_order", "parts", "submit"):
        g.add_edge(name, "supervisor")
    g.add_edge("human_confirm", "supervisor")
    cp = checkpointer if checkpointer is not None else get_checkpointer()
    return g.compile(checkpointer=cp)


@lru_cache
def get_compiled_graph() -> Any:
    return build_langgraph()
