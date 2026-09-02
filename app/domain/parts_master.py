"""配件 master data：以 parts_ledger.json 为准，归一化 RAG/草稿中的配件 hint。

匹配顺序（禁止自由子串误命中）：
1. 件号精确（大小写不敏感）
2. 名称精确
3. 台账 aliases 精确映射
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.domain.parts_catalog import load_parts_catalog, reset_parts_catalog_cache

MASTER_SOURCE = "parts_ledger.json"


_master_mtime: float | None = None
_items_cache: list[dict[str, Any]] | None = None
_alias_cache: dict[str, str] | None = None
_by_no_cache: dict[str, dict[str, Any]] | None = None
_by_name_cache: dict[str, dict[str, Any]] | None = None


def _ledger_mtime() -> float:
    from pathlib import Path

    from app.config import get_settings

    path = Path(get_settings().parts_ledger_path)
    return path.stat().st_mtime if path.exists() else 0.0


def _ensure_master_indexes() -> None:
    """台账文件变更时重建索引（避免 :8002 长驻进程读到旧 stock）。"""
    global _master_mtime, _items_cache, _alias_cache, _by_no_cache, _by_name_cache
    mtime = _ledger_mtime()
    if (
        _items_cache is not None
        and _alias_cache is not None
        and _by_no_cache is not None
        and _by_name_cache is not None
        and _master_mtime == mtime
    ):
        return
    reset_parts_catalog_cache()
    catalog = load_parts_catalog()
    items = [i for i in (catalog.get("items") or []) if isinstance(i, dict)]
    aliases: dict[str, str] = {}
    raw = catalog.get("aliases") or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k and v:
                aliases[str(k).strip()] = str(v).strip()
    by_no: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for row in items:
        pn = str(row.get("part_no") or "").strip()
        if pn:
            by_no[pn.upper()] = row
        name = str(row.get("name") or "").strip()
        if name:
            by_name[name] = row
    _items_cache = items
    _alias_cache = aliases
    _by_no_cache = by_no
    _by_name_cache = by_name
    _master_mtime = mtime


def _load_ledger_items() -> list[dict[str, Any]]:
    _ensure_master_indexes()
    return list(_items_cache or [])


def _alias_map() -> dict[str, str]:
    _ensure_master_indexes()
    return dict(_alias_cache or {})


def _by_part_no() -> dict[str, dict[str, Any]]:
    _ensure_master_indexes()
    return dict(_by_no_cache or {})


def _by_name() -> dict[str, dict[str, Any]]:
    _ensure_master_indexes()
    return dict(_by_name_cache or {})


def reset_parts_master_cache() -> None:
    global _master_mtime, _items_cache, _alias_cache, _by_no_cache, _by_name_cache
    reset_parts_catalog_cache()
    _master_mtime = None
    _items_cache = None
    _alias_cache = None
    _by_no_cache = None
    _by_name_cache = None


def resolve_part_hint(hint: str) -> dict[str, Any] | None:
    """将 RAG/草稿 hint 映射到台账行；件号/名称/别名精确匹配，不做自由子串。"""
    hint = (hint or "").strip()
    if not hint:
        return None
    by_no = _by_part_no()
    hit = by_no.get(hint.upper())
    if hit:
        return hit
    by_name = _by_name()
    if hint in by_name:
        return by_name[hint]
    alias = _alias_map().get(hint)
    if alias and alias in by_name:
        return by_name[alias]
    return None


def normalize_part_hints(hints: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """返回台账 canonical 名称列表 + 映射明细（trace / master 来源）。"""
    canonical: list[str] = []
    mapping: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in hints:
        raw = str(raw or "").strip()
        if not raw:
            continue
        row = resolve_part_hint(raw)
        if row:
            name = str(row.get("name") or raw)
            part_no = row.get("part_no")
            canonical_key = str(part_no or name)
            match_via = "part_no" if str(part_no or "").upper() == raw.upper() else (
                "name" if name == raw else "alias"
            )
            mapping.append(
                {
                    "raw_hint": raw,
                    "canonical_name": name,
                    "part_no": part_no,
                    "master_source": MASTER_SOURCE,
                    "matched": True,
                    "match_via": match_via,
                }
            )
            if canonical_key not in seen:
                seen.add(canonical_key)
                canonical.append(name)
        else:
            mapping.append(
                {
                    "raw_hint": raw,
                    "canonical_name": raw,
                    "part_no": None,
                    "master_source": MASTER_SOURCE,
                    "matched": False,
                    "match_via": None,
                }
            )
            if raw not in seen:
                seen.add(raw)
                canonical.append(raw)
    return canonical, mapping
