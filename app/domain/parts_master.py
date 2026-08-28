"""配件 master data：以 parts_ledger.json 为准，归一化 RAG/草稿中的配件 hint。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.domain.parts_catalog import load_parts_catalog, reset_parts_catalog_cache

MASTER_SOURCE = "parts_ledger.json"


@lru_cache
def _load_ledger_items() -> list[dict[str, Any]]:
    items = load_parts_catalog().get("items") or []
    return [i for i in items if isinstance(i, dict)]


@lru_cache
def _catalog_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _load_ledger_items():
        for key in (row.get("name"), row.get("part_no")):
            if key:
                index[str(key).strip()] = row
    return index


def reset_parts_master_cache() -> None:
    reset_parts_catalog_cache()
    _load_ledger_items.cache_clear()
    _catalog_index.cache_clear()


def resolve_part_hint(hint: str) -> dict[str, Any] | None:
    """将 RAG/草稿 hint 映射到台账行；优先精确匹配再子串。"""
    hint = (hint or "").strip()
    if not hint:
        return None
    catalog = _catalog_index()
    if hint in catalog:
        return catalog[hint]
    for key, row in catalog.items():
        if hint in key or key in hint:
            return row
    return None


def normalize_part_hints(hints: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """返回台账 canonical 名称列表 + 映射明细（供 trace/面试说明 master 来源）。"""
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
            mapping.append(
                {
                    "raw_hint": raw,
                    "canonical_name": name,
                    "part_no": part_no,
                    "master_source": MASTER_SOURCE,
                    "matched": True,
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
                }
            )
            if raw not in seen:
                seen.add(raw)
                canonical.append(raw)
    return canonical, mapping
