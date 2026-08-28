"""结构化日志：节点级 run_id / node / latency 便于排障。"""

from __future__ import annotations

import logging
import sys
from typing import Any

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root = logging.getLogger("copilot")
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"copilot.{name}")


def log_node_event(
    logger: logging.Logger,
    *,
    run_id: str | None,
    node: str,
    ok: bool | None = None,
    latency_ms: int | None = None,
    **fields: Any,
) -> None:
    parts = [f"run_id={run_id or '-'}", f"node={node}"]
    if ok is not None:
        parts.append(f"ok={ok}")
    if latency_ms is not None:
        parts.append(f"latency_ms={latency_ms}")
    for k, v in fields.items():
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    msg = " ".join(parts)
    if ok is False:
        logger.warning(msg)
    else:
        logger.info(msg)
