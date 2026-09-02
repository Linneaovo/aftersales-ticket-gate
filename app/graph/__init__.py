from __future__ import annotations

"""Lazy submodule exports to avoid store ↔ runner circular import."""

from typing import Any

__all__ = ["builder", "nodes", "runner", "state"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        import importlib

        return importlib.import_module(f"app.graph.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
