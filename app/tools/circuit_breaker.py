"""出站 HTTP 轻量熔断：连续失败后短时开路，避免打满不可达依赖。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float = 0.0
    open: bool = False


_lock = threading.Lock()
_circuits: dict[str, CircuitState] = {}


def reset_circuits() -> None:
    with _lock:
        _circuits.clear()


def circuit_allow(name: str, *, failure_threshold: int = 3, cooldown_s: float = 15.0) -> bool:
    """返回 False 表示熔断开路，应直接失败而不发请求。"""
    now = time.time()
    with _lock:
        st = _circuits.setdefault(name, CircuitState())
        if not st.open:
            return True
        if now - st.opened_at >= cooldown_s:
            # half-open：放行一次探测
            st.open = False
            st.failures = 0
            return True
        return False


def circuit_record_success(name: str) -> None:
    with _lock:
        st = _circuits.setdefault(name, CircuitState())
        st.failures = 0
        st.open = False
        st.opened_at = 0.0


def circuit_record_failure(name: str, *, failure_threshold: int = 3) -> None:
    with _lock:
        st = _circuits.setdefault(name, CircuitState())
        st.failures += 1
        if st.failures >= failure_threshold:
            st.open = True
            st.opened_at = time.time()


def circuit_snapshot(name: str) -> dict[str, float | int | bool]:
    with _lock:
        st = _circuits.get(name) or CircuitState()
        return {"open": st.open, "failures": st.failures, "opened_at": st.opened_at}


def all_circuits_snapshot() -> dict[str, dict[str, float | int | bool]]:
    with _lock:
        return {
            name: {"open": st.open, "failures": st.failures, "opened_at": st.opened_at}
            for name, st in _circuits.items()
        }
