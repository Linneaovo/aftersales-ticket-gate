"""配件 catalog 只读加载（domain 层，不依赖 tools）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.station import load_station_profile

_cache_mtime: float | None = None
_cache_data: dict[str, Any] | None = None


def load_parts_catalog_raw() -> dict[str, Any]:
    """按文件 mtime 缓存；改 parts_ledger.json 后无需重启进程即可生效。"""
    global _cache_mtime, _cache_data
    settings = get_settings()
    ledger_path = Path(settings.parts_ledger_path)
    if not ledger_path.exists():
        profile = load_station_profile()
        return {
            "station": profile.get("primary_station", "长沙星沙服务站"),
            "support_depot": profile.get("support_depot", "经开备件周转点"),
            "items": [],
        }
    mtime = ledger_path.stat().st_mtime
    if _cache_data is not None and _cache_mtime == mtime:
        return _cache_data
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    _cache_data = data
    _cache_mtime = mtime
    return data


def load_parts_catalog() -> dict[str, Any]:
    """返回带站点默认值的台账 dict（供配件预核与 hint 归一化共用）。"""
    data = dict(load_parts_catalog_raw())
    profile = load_station_profile()
    data.setdefault("station", profile.get("primary_station"))
    data.setdefault("support_depot", profile.get("support_depot"))
    return data


def reset_parts_catalog_cache() -> None:
    global _cache_mtime, _cache_data
    _cache_mtime = None
    _cache_data = None


def parts_ledger_fingerprint(path: str | Path | None = None) -> dict[str, Any]:
    """台账文件指纹（始终读盘，不经进程缓存）供 /health · preflight 核对。"""
    ledger_path = Path(path) if path else Path(get_settings().parts_ledger_path)
    if not ledger_path.exists():
        return {
            "parts_ledger_path": str(ledger_path),
            "parts_ledger_mtime": 0.0,
            "parts_ledger_sha256": "",
            "parts_item_count": 0,
            "exists": False,
        }
    raw = ledger_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        count = len(items) if isinstance(items, list) else 0
    except (json.JSONDecodeError, UnicodeDecodeError):
        count = 0
    return {
        "parts_ledger_path": str(ledger_path),
        "parts_ledger_mtime": ledger_path.stat().st_mtime,
        "parts_ledger_sha256": digest[:12],
        "parts_item_count": count,
        "exists": True,
    }
