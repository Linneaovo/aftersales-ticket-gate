"""配件 catalog 只读加载（domain 层，不依赖 tools）。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.station import load_station_profile


@lru_cache
def load_parts_catalog_raw() -> dict[str, Any]:
    settings = get_settings()
    ledger_path = Path(settings.parts_ledger_path)
    if not ledger_path.exists():
        profile = load_station_profile()
        return {
            "station": profile.get("primary_station", "长沙星沙服务站"),
            "support_depot": profile.get("support_depot", "经开备件周转点"),
            "items": [],
        }
    return json.loads(ledger_path.read_text(encoding="utf-8"))


def load_parts_catalog() -> dict[str, Any]:
    """返回带站点默认值的台账 dict（供配件预核与 hint 归一化共用）。"""
    data = dict(load_parts_catalog_raw())
    profile = load_station_profile()
    data.setdefault("station", profile.get("primary_station"))
    data.setdefault("support_depot", profile.get("support_depot"))
    return data


def reset_parts_catalog_cache() -> None:
    load_parts_catalog_raw.cache_clear()
