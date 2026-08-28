from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, get_settings


@lru_cache
def load_station_profile() -> dict[str, Any]:
    path = PROJECT_ROOT / "data" / "station_profile.json"
    if not path.exists():
        return {
            "primary_station": "长沙星沙服务站",
            "support_depot": "经开备件周转点",
            "urgent_response_hours": 4,
            "normal_response_hours": 24,
            "rainy_season_note": "雨季户外作业需备注防滑与电路防护",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def default_station_context() -> dict[str, Any]:
    profile = load_station_profile()
    return {
        "primary_station": profile.get("primary_station", "长沙星沙服务站"),
        "support_depot": profile.get("support_depot", "经开备件周转点"),
        "urgent_response_hours": int(profile.get("urgent_response_hours") or 4),
        "normal_response_hours": int(profile.get("normal_response_hours") or 24),
        "rainy_season_note": profile.get("rainy_season_note") or "",
        "station_aliases": profile.get("station_aliases") or {},
    }


def resolve_station_name(text: str, *, override: str | None = None) -> str | None:
    """从问句或 override 解析站点名（alias 外置在 station_profile.json）。"""
    if override:
        return override.strip() or None
    q = text or ""
    profile = load_station_profile()
    primary = profile.get("primary_station", "长沙星沙服务站")
    aliases = profile.get("station_aliases") or {}
    for alias in aliases.get("primary") or []:
        if alias and alias in q:
            return primary
    for alias in aliases.get("support") or []:
        if alias and alias in q:
            return str(profile.get("support_depot") or "经开备件周转点")
    return None
